"""Parse and validate Claude's JSON response into AnalysisResult."""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from custom_components.ha_energy_agent.models import (
    AnalysisResult,
    AnalysisTip,
    AutomationSuggestion,
)

_LOGGER = logging.getLogger(__name__)

_VALID_PRIORITIES = {"high", "medium", "low"}
_VALID_CATEGORIES = {"solar", "battery", "heat_pump", "grid", "pricing", "cross_system"}


def _extract_json(text: str) -> str:
    """Extract the first JSON object from a Claude response that may contain prose."""
    # Strip markdown code fences
    stripped = re.sub(r"```(?:json)?\s*", "", text).strip()
    # Find outermost { ... }
    start = stripped.find("{")
    if start == -1:
        raise ValueError("No JSON object found in response")
    depth = 0
    for i, ch in enumerate(stripped[start:], start=start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return stripped[start : i + 1]
    raise ValueError("Unclosed JSON object in response")


def _parse_tip(raw: Any, idx: int) -> AnalysisTip | None:
    if not isinstance(raw, dict):
        return None
    priority = str(raw.get("priority", "low")).lower()
    if priority not in _VALID_PRIORITIES:
        priority = "low"
    category = str(raw.get("category", "grid")).lower()
    if category not in _VALID_CATEGORIES:
        category = "grid"
    tip_id = str(raw.get("id") or f"tip_{idx}")
    title = str(raw.get("title") or "Untitled tip")
    description = str(raw.get("description") or "")
    estimated_saving = str(raw.get("estimated_saving") or "")
    automation_yaml = str(raw.get("automation_yaml") or "")
    return AnalysisTip(
        id=tip_id,
        priority=priority,
        category=category,
        title=title,
        description=description,
        estimated_saving=estimated_saving,
        automation_yaml=automation_yaml,
    )


def _parse_automation(raw: Any, idx: int) -> AutomationSuggestion | None:
    if not isinstance(raw, dict):
        return None
    return AutomationSuggestion(
        id=str(raw.get("id") or f"auto_{idx}"),
        name=str(raw.get("name") or "Unnamed automation"),
        description=str(raw.get("description") or ""),
        yaml=str(raw.get("yaml") or ""),
    )


def parse_claude_response(raw_text: str) -> AnalysisResult:
    """
    Parse Claude's raw text response into a validated AnalysisResult.

    Raises ValueError if the response cannot be parsed at all.
    """
    json_str = _extract_json(raw_text)
    try:
        data: dict = json.loads(json_str)
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON decode error: {exc}") from exc

    summary = str(data.get("summary") or "No summary provided.")

    raw_score = data.get("efficiency_score", 50)
    try:
        score = max(0, min(100, int(raw_score)))
    except (TypeError, ValueError):
        score = 50

    tips: list[AnalysisTip] = []
    for i, raw_tip in enumerate(data.get("tips") or []):
        tip = _parse_tip(raw_tip, i)
        if tip:
            tips.append(tip)

    automations: list[AutomationSuggestion] = []
    for i, raw_auto in enumerate(data.get("automations") or []):
        auto = _parse_automation(raw_auto, i)
        if auto:
            automations.append(auto)

    data_quality_notes = [str(n) for n in (data.get("data_quality_notes") or [])]
    notable_observations = [str(o) for o in (data.get("notable_observations") or [])]

    return AnalysisResult(
        summary=summary,
        efficiency_score=score,
        tips=tips,
        automations=automations,
        data_quality_notes=data_quality_notes,
        notable_observations=notable_observations,
    )
