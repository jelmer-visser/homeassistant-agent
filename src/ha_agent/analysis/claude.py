"""Anthropic API integration — calls claude-sonnet-4-6 and returns raw JSON string."""
from __future__ import annotations

import structlog

import anthropic

from ha_agent.analysis.prompts import SYSTEM_PROMPT, build_user_message
from ha_agent.config import Settings
from ha_agent.models import GroupHistoryBundle, PricingContext

log = structlog.get_logger(__name__)

_MODEL = "claude-sonnet-4-6"
_MAX_TOKENS = 4096


async def call_claude(
    group_bundles: list[GroupHistoryBundle],
    pricing: PricingContext,
    settings: Settings,
) -> str:
    """
    Build the prompt from sensor data, call Claude, return the raw response text.
    Raises on API errors.
    """
    user_message = build_user_message(group_bundles, pricing)

    log.info(
        "claude_request",
        model=_MODEL,
        prompt_chars=len(user_message),
        sensor_groups=len(group_bundles),
    )

    # anthropic.Anthropic is synchronous; wrap in asyncio executor to avoid blocking
    import asyncio

    def _sync_call() -> str:
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        message = client.messages.create(
            model=_MODEL,
            max_tokens=_MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
        return message.content[0].text

    loop = asyncio.get_event_loop()
    raw = await loop.run_in_executor(None, _sync_call)

    log.info("claude_response", chars=len(raw))
    return raw
