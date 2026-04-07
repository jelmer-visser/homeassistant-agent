"""Anthropic Claude API client wrapper for HA Energy Agent."""
from __future__ import annotations

import logging
from typing import Optional

from custom_components.ha_energy_agent.models import (
    AnalysisResult,
    GroupHistoryBundle,
    PricingContext,
)
from custom_components.ha_energy_agent.analysis.parser import parse_claude_response
from custom_components.ha_energy_agent.analysis.prompts import (
    SYSTEM_PROMPT,
    build_user_message,
)

_LOGGER = logging.getLogger(__name__)

_MAX_TOKENS = 4096


class ClaudeAnalysisClient:
    """Thin async wrapper around the Anthropic Python SDK."""

    def __init__(self, api_key: str, model: str) -> None:
        import anthropic

        self._model = model
        self._client = anthropic.AsyncAnthropic(api_key=api_key)

    async def analyse(
        self,
        bundles: list[GroupHistoryBundle],
        pricing: Optional[PricingContext],
        history_hours: int,
    ) -> AnalysisResult:
        """Run one analysis cycle and return a validated AnalysisResult."""
        user_message = build_user_message(bundles, pricing, history_hours)

        _LOGGER.debug("Sending %d chars to Claude (%s)", len(user_message), self._model)

        response = await self._client.messages.create(
            model=self._model,
            max_tokens=_MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )

        raw_text: str = response.content[0].text
        _LOGGER.debug("Received %d chars from Claude", len(raw_text))

        try:
            return parse_claude_response(raw_text)
        except ValueError as exc:
            _LOGGER.error("Failed to parse Claude response: %s\nRaw: %.500s", exc, raw_text)
            raise
