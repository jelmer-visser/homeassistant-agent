"""Parse and validate Claude's JSON response into an AnalysisResult."""
from __future__ import annotations

import json
import re

import structlog

from ha_agent.models import AnalysisResult

log = structlog.get_logger(__name__)

# Regex to extract a JSON object even if Claude wraps it in markdown fences
_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_BARE_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def _extract_json(text: str) -> str:
    """Extract the first JSON object from text, stripping markdown fences if present."""
    # Try fenced code block first
    m = _JSON_BLOCK_RE.search(text)
    if m:
        return m.group(1)
    # Fall back to bare JSON object
    m = _BARE_JSON_RE.search(text)
    if m:
        return m.group(0)
    raise ValueError("No JSON object found in Claude response")


def parse_analysis(raw: str) -> AnalysisResult:
    """
    Parse the raw Claude response string into a validated AnalysisResult.
    Raises ValueError if the response cannot be parsed or fails Pydantic validation.
    """
    json_str = _extract_json(raw)
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON decode error: {exc}") from exc

    # Assign sequential IDs to tips/automations if missing (Claude sometimes omits them)
    for i, tip in enumerate(data.get("tips", []), start=1):
        if not tip.get("id"):
            tip["id"] = f"tip_{i}"
    for i, auto in enumerate(data.get("automations", []), start=1):
        if not auto.get("id"):
            auto["id"] = f"auto_{i}"

    try:
        return AnalysisResult.model_validate(data)
    except Exception as exc:
        log.warning("analysis_validation_error", error=str(exc), raw_snippet=raw[:500])
        raise ValueError(f"AnalysisResult validation failed: {exc}") from exc
