"""Tests for multi-provider AI client support."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.ha_energy_agent.analysis.openai_client import (
    OpenAIAnalysisClient,
    _is_reasoning_model,
)
from custom_components.ha_energy_agent.const import (
    ANTHROPIC_MODELS,
    DEFAULT_ANTHROPIC_MODEL,
    DEFAULT_OPENAI_MODEL,
    OPENAI_MODELS,
    PROVIDER_ANTHROPIC,
    PROVIDER_OPENAI,
)
from custom_components.ha_energy_agent.models import AnalysisResult


# ---------------------------------------------------------------------------
# Model lists
# ---------------------------------------------------------------------------

class TestModelLists:
    def test_anthropic_models_non_empty(self):
        assert len(ANTHROPIC_MODELS) >= 3

    def test_openai_models_non_empty(self):
        assert len(OPENAI_MODELS) >= 3

    def test_defaults_are_in_their_lists(self):
        assert DEFAULT_ANTHROPIC_MODEL in ANTHROPIC_MODELS
        assert DEFAULT_OPENAI_MODEL in OPENAI_MODELS

    def test_no_overlap_in_model_names(self):
        # Anthropic and OpenAI model names should be distinct
        assert not (set(ANTHROPIC_MODELS) & set(OPENAI_MODELS))


# ---------------------------------------------------------------------------
# Reasoning model detection
# ---------------------------------------------------------------------------

class TestIsReasoningModel:
    def test_o4_mini_is_reasoning(self):
        assert _is_reasoning_model("o4-mini") is True

    def test_o1_is_reasoning(self):
        assert _is_reasoning_model("o1") is True

    def test_o3_mini_is_reasoning(self):
        assert _is_reasoning_model("o3-mini") is True

    def test_gpt4o_is_not_reasoning(self):
        assert _is_reasoning_model("gpt-4o") is False

    def test_gpt4o_mini_is_not_reasoning(self):
        assert _is_reasoning_model("gpt-4o-mini") is False

    def test_gpt41_is_not_reasoning(self):
        assert _is_reasoning_model("gpt-4.1") is False

    def test_claude_is_not_reasoning(self):
        assert _is_reasoning_model("claude-sonnet-4-6") is False


# ---------------------------------------------------------------------------
# OpenAIAnalysisClient
# ---------------------------------------------------------------------------

_VALID_RESPONSE = json.dumps({
    "summary": "All systems nominal.",
    "efficiency_score": 80,
    "tips": [],
    "automations": [],
    "data_quality_notes": [],
    "notable_observations": [],
})


class TestOpenAIAnalysisClient:
    def _make_mock_response(self, content: str) -> MagicMock:
        msg = MagicMock()
        msg.content = content
        choice = MagicMock()
        choice.message = msg
        resp = MagicMock()
        resp.choices = [choice]
        return resp

    @pytest.mark.asyncio
    async def test_gpt_model_sends_response_format(self):
        """GPT models should include response_format=json_object."""
        mock_response = self._make_mock_response(_VALID_RESPONSE)

        with patch("openai.AsyncOpenAI") as mock_cls:
            mock_client = MagicMock()
            mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
            mock_cls.return_value = mock_client

            client = OpenAIAnalysisClient(api_key="sk-test", model="gpt-4o")
            result = await client.analyse([], None, 24)

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs.get("response_format") == {"type": "json_object"}
        assert isinstance(result, AnalysisResult)
        assert result.efficiency_score == 80

    @pytest.mark.asyncio
    async def test_reasoning_model_omits_response_format(self):
        """Reasoning models (o4-mini etc.) must NOT get response_format."""
        mock_response = self._make_mock_response(_VALID_RESPONSE)

        with patch("openai.AsyncOpenAI") as mock_cls:
            mock_client = MagicMock()
            mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
            mock_cls.return_value = mock_client

            client = OpenAIAnalysisClient(api_key="sk-test", model="o4-mini")
            await client.analyse([], None, 24)

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert "response_format" not in call_kwargs

    @pytest.mark.asyncio
    async def test_system_message_included(self):
        """System prompt should be the first message."""
        mock_response = self._make_mock_response(_VALID_RESPONSE)

        with patch("openai.AsyncOpenAI") as mock_cls:
            mock_client = MagicMock()
            mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
            mock_cls.return_value = mock_client

            client = OpenAIAnalysisClient(api_key="sk-test", model="gpt-4o")
            await client.analyse([], None, 24)

        messages = mock_client.chat.completions.create.call_args.kwargs["messages"]
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"

    @pytest.mark.asyncio
    async def test_parse_error_raises(self):
        """ValueError from parser should propagate."""
        bad_response = self._make_mock_response("not json at all")

        with patch("openai.AsyncOpenAI") as mock_cls:
            mock_client = MagicMock()
            mock_client.chat.completions.create = AsyncMock(return_value=bad_response)
            mock_cls.return_value = mock_client

            client = OpenAIAnalysisClient(api_key="sk-test", model="gpt-4o")
            with pytest.raises(ValueError):
                await client.analyse([], None, 24)


# ---------------------------------------------------------------------------
# ClaudeAnalysisClient — model param forwarded
# ---------------------------------------------------------------------------

class TestClaudeAnalysisClientModelParam:
    @pytest.mark.asyncio
    async def test_model_passed_to_api(self):
        """The model passed at construction should be forwarded to the API call."""
        from custom_components.ha_energy_agent.analysis.claude import ClaudeAnalysisClient

        mock_content = MagicMock()
        mock_content.text = _VALID_RESPONSE
        mock_response = MagicMock()
        mock_response.content = [mock_content]

        with patch("anthropic.AsyncAnthropic") as mock_cls:
            mock_client = MagicMock()
            mock_client.messages.create = AsyncMock(return_value=mock_response)
            mock_cls.return_value = mock_client

            client = ClaudeAnalysisClient(api_key="sk-ant-test", model="claude-haiku-4-5-20251001")
            await client.analyse([], None, 24)

        call_kwargs = mock_client.messages.create.call_args.kwargs
        assert call_kwargs["model"] == "claude-haiku-4-5-20251001"
