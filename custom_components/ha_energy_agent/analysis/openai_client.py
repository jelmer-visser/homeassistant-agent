"""OpenAI ChatGPT API client wrapper for HA Energy Agent."""
from __future__ import annotations

import logging
from typing import Optional

from custom_components.ha_energy_agent.const import OPENAI_REASONING_MODELS
from custom_components.ha_energy_agent.models import (
    AnalysisResult,
    GroupHistoryBundle,
    LongTermContext,
    PricingContext,
)
from custom_components.ha_energy_agent.analysis.parser import parse_claude_response
from custom_components.ha_energy_agent.analysis.prompts import (
    SYSTEM_PROMPT,
    build_user_message,
)

_LOGGER = logging.getLogger(__name__)

_MAX_TOKENS = 4096


def _is_reasoning_model(model: str) -> bool:
    """Return True for o-series reasoning models that don't support response_format."""
    return any(model == m or model.startswith(m + "-") for m in OPENAI_REASONING_MODELS)


class OpenAIAnalysisClient:
    """Thin async wrapper around the OpenAI Python SDK."""

    def __init__(self, api_key: str, model: str) -> None:
        self._api_key = api_key
        self._model = model
        self._client = None

    def _create_client(self):
        import openai
        return openai.AsyncOpenAI(api_key=self._api_key)

    async def _get_client(self):
        if self._client is None:
            import asyncio
            loop = asyncio.get_running_loop()
            self._client = await loop.run_in_executor(None, self._create_client)
        return self._client

    async def analyse(
        self,
        bundles: list[GroupHistoryBundle],
        pricing: Optional[PricingContext],
        history_hours: int,
        long_term: Optional[LongTermContext] = None,
    ) -> AnalysisResult:
        """Run one analysis cycle and return a validated AnalysisResult."""
        user_message = build_user_message(bundles, pricing, history_hours, long_term)

        _LOGGER.debug("Sending %d chars to OpenAI (%s)", len(user_message), self._model)

        kwargs: dict = dict(
            model=self._model,
            max_completion_tokens=_MAX_TOKENS,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
        )

        # Reasoning models (o1/o3/o4 family) don't support response_format
        if not _is_reasoning_model(self._model):
            kwargs["response_format"] = {"type": "json_object"}

        client = await self._get_client()
        response = await client.chat.completions.create(**kwargs)

        raw_text: str = response.choices[0].message.content or ""
        _LOGGER.debug("Received %d chars from OpenAI", len(raw_text))

        try:
            return parse_claude_response(raw_text)
        except ValueError as exc:
            _LOGGER.error("Failed to parse OpenAI response: %s\nRaw: %.500s", exc, raw_text)
            raise
