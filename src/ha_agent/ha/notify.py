"""Deliver analysis results back to Home Assistant and write local JSON log."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import structlog

from ha_agent.config import Settings
from ha_agent.ha.client import HAClient
from ha_agent.models import AgentCycleResult, AnalysisResult

log = structlog.get_logger(__name__)

_NOTIFICATION_ID = "ha_energy_agent_analysis"
_INPUT_TEXT_ENTITY = "input_text.ha_agent_efficiency_score"


def _format_notification(result: AnalysisResult) -> tuple[str, str]:
    """Return (title, message) for the HA persistent notification."""
    score_emoji = "🟢" if result.efficiency_score >= 75 else ("🟡" if result.efficiency_score >= 50 else "🔴")
    title = f"{score_emoji} Energy Agent — Score {result.efficiency_score}/100"

    lines: list[str] = [
        result.summary,
        "",
        f"**Efficiency score: {result.efficiency_score}/100**",
        "",
    ]

    # Top 3 tips
    high_tips = [t for t in result.tips if t.priority == "high"]
    other_tips = [t for t in result.tips if t.priority != "high"]
    top_tips = (high_tips + other_tips)[:3]

    if top_tips:
        lines.append("### Top recommendations")
        for tip in top_tips:
            priority_label = {"high": "🔴 HIGH", "medium": "🟡 MEDIUM", "low": "🟢 LOW"}.get(
                tip.priority, tip.priority.upper()
            )
            lines.append(f"**{tip.title}** [{priority_label}]")
            lines.append(tip.description)
            if tip.estimated_saving:
                lines.append(f"_Estimated saving: {tip.estimated_saving}_")
            lines.append("")

    if result.notable_observations:
        lines.append("### Notable observations")
        for obs in result.notable_observations[:3]:
            lines.append(f"- {obs}")
        lines.append("")

    return title, "\n".join(lines)


def _write_json_log(cycle_result: AgentCycleResult, log_dir: Path) -> str:
    """Write full analysis JSON to logs/ and return the file path."""
    log_dir.mkdir(parents=True, exist_ok=True)
    ts = cycle_result.started_at.strftime("%Y%m%d_%H%M%S")
    path = log_dir / f"analysis_{ts}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cycle_result.model_dump(mode="json"), f, indent=2, default=str)
    return str(path)


async def deliver_results(
    client: HAClient,
    cycle_result: AgentCycleResult,
    settings: Settings,
) -> AgentCycleResult:
    """
    Send notification to HA and write JSON log.
    Returns an updated AgentCycleResult with notification_sent and log_path set.
    """
    notification_sent = False
    log_path = ""

    # Write local JSON log (always)
    try:
        log_path = _write_json_log(cycle_result, settings.log_dir)
        log.info("json_log_written", path=log_path)
    except Exception as exc:
        log.error("json_log_failed", error=str(exc))

    # Send HA persistent notification
    if settings.notify_ha:
        try:
            title, message = _format_notification(cycle_result.analysis)
            await client.send_persistent_notification(title, message, _NOTIFICATION_ID)
            notification_sent = True
            log.info("notification_sent", title=title)
        except Exception as exc:
            log.error("notification_failed", error=str(exc))

        # Optionally update an input_text entity with the score
        try:
            score_str = str(cycle_result.analysis.efficiency_score)
            await client.set_input_text(_INPUT_TEXT_ENTITY, score_str)
        except Exception:
            pass  # input_text entity may not exist; non-critical

    return cycle_result.model_copy(
        update={"notification_sent": notification_sent, "log_path": log_path}
    )
