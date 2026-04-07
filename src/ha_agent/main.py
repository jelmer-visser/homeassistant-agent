"""CLI entry point and APScheduler bootstrap."""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from ha_agent.config import get_settings
from ha_agent.agent import run_cycle


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(message)s",
        stream=sys.stdout,
    )
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
    )


log = structlog.get_logger(__name__)


async def _run_once() -> int:
    """Run a single analysis cycle and exit. Returns exit code."""
    settings = get_settings()
    _configure_logging(settings.log_level)
    log.info("run_once_start")
    try:
        result = await run_cycle(settings)
        log.info(
            "run_once_done",
            score=result.analysis.efficiency_score,
            tips=len(result.analysis.tips),
            log_path=result.log_path,
        )
        # Print a human-readable summary to stdout
        print("\n" + "=" * 60)
        print(f"Efficiency score: {result.analysis.efficiency_score}/100")
        print(f"Summary: {result.analysis.summary}")
        print(f"\nTop tips ({len(result.analysis.tips)} total):")
        for tip in result.analysis.tips[:5]:
            print(f"  [{tip.priority.upper()}] {tip.title}")
        print(f"\nFull result: {result.log_path}")
        print("=" * 60 + "\n")
        return 0
    except Exception as exc:
        log.error("run_once_failed", error=str(exc), exc_info=True)
        return 1


async def _run_scheduled() -> None:
    """Run the agent on a schedule until interrupted."""
    settings = get_settings()
    _configure_logging(settings.log_level)
    log.info(
        "scheduler_start",
        interval_minutes=settings.agent_interval_minutes,
    )

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        run_cycle,
        "interval",
        minutes=settings.agent_interval_minutes,
        args=[settings],
        id="energy_analysis",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()

    # Run once immediately on startup
    log.info("running_initial_cycle")
    try:
        await run_cycle(settings)
    except Exception as exc:
        log.error("initial_cycle_failed", error=str(exc))

    # Keep running until SIGINT / SIGTERM
    log.info("scheduler_running", press_ctrl_c="CTRL+C to stop")
    try:
        while True:
            await asyncio.sleep(60)
    except (KeyboardInterrupt, asyncio.CancelledError):
        log.info("scheduler_stopping")
        scheduler.shutdown(wait=False)


def cli() -> None:
    """Entry point for the `ha-agent` CLI command."""
    parser = argparse.ArgumentParser(
        description="Home Assistant Energy Optimization AI Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  ha-agent --run-once          # Single analysis cycle\n"
            "  ha-agent                     # Scheduled mode (every 30 min)\n"
        ),
    )
    parser.add_argument(
        "--run-once",
        action="store_true",
        help="Run a single analysis cycle and exit",
    )
    parser.add_argument(
        "--web-ui",
        action="store_true",
        help="Enable the optional web dashboard (overrides ENABLE_WEB_UI env var)",
    )
    args = parser.parse_args()

    if args.web_ui:
        import os
        os.environ["ENABLE_WEB_UI"] = "true"

    if args.run_once:
        exit_code = asyncio.run(_run_once())
        sys.exit(exit_code)
    else:
        # Scheduled mode — also start web UI if configured
        settings = get_settings()
        if settings.enable_web_ui or args.web_ui:
            _run_with_web_ui(settings)
        else:
            asyncio.run(_run_scheduled())


def _run_with_web_ui(settings) -> None:
    """Run scheduler + FastAPI web UI concurrently."""
    try:
        import uvicorn
        from ha_agent.ui.web import create_app
    except ImportError:
        print(
            "Web UI dependencies not installed. "
            "Run: pip install ha-agent[web]",
            file=sys.stderr,
        )
        sys.exit(1)

    app = create_app()

    async def _main() -> None:
        config = uvicorn.Config(
            app,
            host="0.0.0.0",
            port=settings.web_ui_port,
            log_level="warning",
        )
        server = uvicorn.Server(config)
        await asyncio.gather(
            _run_scheduled(),
            server.serve(),
        )

    asyncio.run(_main())


if __name__ == "__main__":
    cli()
