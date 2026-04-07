"""Tests for analysis/parser.py — JSON extraction and model validation."""
from __future__ import annotations

import json

import pytest

from custom_components.ha_energy_agent.analysis.parser import (
    _extract_json,
    parse_claude_response,
)
from custom_components.ha_energy_agent.models import AnalysisResult


_MINIMAL_VALID = {
    "summary": "All systems operating nominally.",
    "efficiency_score": 72,
    "tips": [
        {
            "id": "tip_1",
            "priority": "high",
            "category": "solar",
            "title": "Enable solar self-consumption mode",
            "description": "Battery is idle while solar is exporting.",
            "estimated_saving": "€0.50/day",
            "automation_yaml": "",
        }
    ],
    "automations": [],
    "data_quality_notes": [],
    "notable_observations": ["Nord Pool price near zero"],
}


class TestExtractJson:
    def test_bare_json(self):
        raw = json.dumps(_MINIMAL_VALID)
        extracted = _extract_json(raw)
        assert json.loads(extracted)["efficiency_score"] == 72

    def test_fenced_json(self):
        raw = f"```json\n{json.dumps(_MINIMAL_VALID)}\n```"
        extracted = _extract_json(raw)
        assert json.loads(extracted)["efficiency_score"] == 72

    def test_fenced_no_language(self):
        raw = f"```\n{json.dumps(_MINIMAL_VALID)}\n```"
        extracted = _extract_json(raw)
        assert json.loads(extracted)["efficiency_score"] == 72

    def test_json_with_surrounding_text(self):
        raw = f"Here is the analysis:\n{json.dumps(_MINIMAL_VALID)}\nDone."
        extracted = _extract_json(raw)
        assert json.loads(extracted)["efficiency_score"] == 72

    def test_no_json_raises(self):
        with pytest.raises(ValueError, match="No JSON"):
            _extract_json("This is just plain text with no JSON.")


class TestParseClaudeResponse:
    def test_valid_minimal(self):
        raw = json.dumps(_MINIMAL_VALID)
        result = parse_claude_response(raw)
        assert isinstance(result, AnalysisResult)
        assert result.efficiency_score == 72
        assert len(result.tips) == 1
        assert result.tips[0].priority == "high"

    def test_fenced_response(self):
        raw = f"```json\n{json.dumps(_MINIMAL_VALID)}\n```"
        result = parse_claude_response(raw)
        assert result.efficiency_score == 72

    def test_invalid_json_raises(self):
        with pytest.raises(ValueError):
            parse_claude_response("{not valid json}")

    def test_score_clamped_to_100(self):
        data = dict(_MINIMAL_VALID)
        data["efficiency_score"] = 150
        result = parse_claude_response(json.dumps(data))
        assert result.efficiency_score == 100

    def test_score_clamped_to_0(self):
        data = dict(_MINIMAL_VALID)
        data["efficiency_score"] = -10
        result = parse_claude_response(json.dumps(data))
        assert result.efficiency_score == 0

    def test_missing_summary_uses_default(self):
        data = {k: v for k, v in _MINIMAL_VALID.items() if k != "summary"}
        result = parse_claude_response(json.dumps(data))
        assert "No summary" in result.summary

    def test_empty_tips_allowed(self):
        data = dict(_MINIMAL_VALID)
        data["tips"] = []
        result = parse_claude_response(json.dumps(data))
        assert result.tips == []

    def test_multiple_tips(self):
        data = dict(_MINIMAL_VALID)
        data["tips"] = [
            {**_MINIMAL_VALID["tips"][0], "id": f"tip_{i}", "priority": p}
            for i, p in enumerate(["high", "medium", "low"], start=1)
        ]
        result = parse_claude_response(json.dumps(data))
        assert len(result.tips) == 3

    def test_notable_observations_preserved(self):
        result = parse_claude_response(json.dumps(_MINIMAL_VALID))
        assert "Nord Pool price near zero" in result.notable_observations

    def test_invalid_priority_coerced_to_low(self):
        data = dict(_MINIMAL_VALID)
        data["tips"] = [{**_MINIMAL_VALID["tips"][0], "priority": "CRITICAL"}]
        result = parse_claude_response(json.dumps(data))
        assert result.tips[0].priority == "low"

    def test_invalid_category_coerced_to_grid(self):
        data = dict(_MINIMAL_VALID)
        data["tips"] = [{**_MINIMAL_VALID["tips"][0], "category": "unknown_category"}]
        result = parse_claude_response(json.dumps(data))
        assert result.tips[0].category == "grid"

    def test_automation_parsed(self):
        data = dict(_MINIMAL_VALID)
        data["automations"] = [
            {
                "id": "auto_1",
                "name": "Charge at night",
                "description": "Starts battery charging at night rate",
                "yaml": "automation:\n  trigger: ...",
            }
        ]
        result = parse_claude_response(json.dumps(data))
        assert len(result.automations) == 1
        assert result.automations[0].id == "auto_1"
