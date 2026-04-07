"""
Optional FastAPI web dashboard (enabled via ENABLE_WEB_UI=true).

Provides a minimal read-only UI showing the last analysis result.
No external template files required — HTML is rendered inline.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

from ha_agent.agent import get_last_result

_CSS = """
body { font-family: system-ui, sans-serif; max-width: 900px; margin: 2rem auto; padding: 0 1rem; background: #f8f9fa; color: #212529; }
h1 { color: #0d6efd; }
.score { font-size: 3rem; font-weight: bold; }
.score.high { color: #198754; }
.score.mid  { color: #ffc107; }
.score.low  { color: #dc3545; }
.tip { background: white; border-left: 4px solid #0d6efd; border-radius: 4px; padding: 1rem; margin: 0.75rem 0; box-shadow: 0 1px 3px rgba(0,0,0,.1); }
.tip.high { border-color: #dc3545; }
.tip.medium { border-color: #ffc107; }
.tip.low { border-color: #198754; }
.badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: .75rem; font-weight: bold; color: white; margin-right: 4px; }
.badge.high { background: #dc3545; }
.badge.medium { background: #ffc107; color: #212529; }
.badge.low { background: #198754; }
.badge.cat { background: #6c757d; }
pre { background: #f1f3f5; padding: 1rem; border-radius: 4px; overflow-x: auto; font-size: .85rem; }
.obs { background: white; padding: .5rem 1rem; border-radius: 4px; margin: .4rem 0; }
.meta { color: #6c757d; font-size: .85rem; margin-bottom: 1.5rem; }
"""


def _score_class(score: int) -> str:
    if score >= 75:
        return "high"
    if score >= 50:
        return "mid"
    return "low"


def _render_dashboard(result: Any) -> str:
    """Render the full HTML dashboard from the last AgentCycleResult."""
    analysis = result.analysis
    score_cls = _score_class(analysis.efficiency_score)

    tips_html = ""
    for tip in analysis.tips:
        automation_section = ""
        if tip.automation_yaml:
            automation_section = f"<details><summary>Automation YAML</summary><pre>{tip.automation_yaml}</pre></details>"
        saving = f"<em>Saving: {tip.estimated_saving}</em><br>" if tip.estimated_saving else ""
        tips_html += f"""
        <div class="tip {tip.priority}">
          <span class="badge {tip.priority}">{tip.priority.upper()}</span>
          <span class="badge cat">{tip.category}</span>
          <strong>{tip.title}</strong><br>
          <p>{tip.description}</p>
          {saving}
          {automation_section}
        </div>
        """

    obs_html = "".join(
        f'<div class="obs">• {o}</div>' for o in analysis.notable_observations
    )
    notes_html = "".join(
        f'<div class="obs">⚠ {n}</div>' for n in analysis.data_quality_notes
    )

    automations_html = ""
    for auto in analysis.automations:
        automations_html += f"""
        <div class="tip">
          <strong>{auto.name}</strong><br>
          <p>{auto.description}</p>
          <details><summary>YAML</summary><pre>{auto.yaml}</pre></details>
        </div>
        """

    ts = result.completed_at.strftime("%Y-%m-%d %H:%M UTC")
    duration = f"{result.duration_seconds:.1f}s"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>HA Energy Agent</title>
  <style>{_CSS}</style>
  <meta http-equiv="refresh" content="300">
</head>
<body>
  <h1>🏠 Home Energy Agent</h1>
  <div class="meta">Last analysis: {ts} &nbsp;|&nbsp; Duration: {duration} &nbsp;|&nbsp;
    Notification sent: {"✅" if result.notification_sent else "❌"}
  </div>

  <div class="score {score_cls}">{analysis.efficiency_score}<span style="font-size:1.5rem">/100</span></div>
  <p>{analysis.summary}</p>

  <h2>Recommendations ({len(analysis.tips)})</h2>
  {tips_html if tips_html else "<p>No tips generated.</p>"}

  {"<h2>Notable Observations</h2>" + obs_html if analysis.notable_observations else ""}

  {"<h2>Suggested Automations</h2>" + automations_html if analysis.automations else ""}

  {"<h2>Data Quality Notes</h2>" + notes_html if analysis.data_quality_notes else ""}
</body>
</html>"""


def create_app() -> FastAPI:
    app = FastAPI(title="HA Energy Agent", version="0.1.0", docs_url=None, redoc_url=None)

    @app.get("/", response_class=HTMLResponse)
    async def dashboard() -> HTMLResponse:
        result = get_last_result()
        if result is None:
            html = (
                "<html><body>"
                "<h2>No analysis available yet.</h2>"
                "<p>The first cycle runs on startup — check back in a moment.</p>"
                '<meta http-equiv="refresh" content="15">'
                "</body></html>"
            )
            return HTMLResponse(content=html, status_code=202)
        return HTMLResponse(content=_render_dashboard(result))

    @app.get("/api/latest")
    async def latest_json() -> JSONResponse:
        result = get_last_result()
        if result is None:
            return JSONResponse({"error": "No analysis available yet"}, status_code=404)
        return JSONResponse(result.model_dump(mode="json"))

    @app.get("/health")
    async def health() -> dict:
        result = get_last_result()
        return {
            "status": "ok",
            "last_analysis": (
                result.completed_at.isoformat() if result else None
            ),
        }

    return app
