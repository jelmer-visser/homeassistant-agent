"""DataUpdateCoordinator for HA Energy Agent.

Orchestrates the full analysis cycle:
  1. Rebuild SensorGroups from user-selected entities
  2. Fetch historical data from HA Recorder
  3. Build PricingContext from live state + options
  4. Call AI provider API
  5. Optionally push a persistent notification to HA
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from homeassistant.components.persistent_notification import async_create
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from custom_components.ha_energy_agent.analysis.base import AnalysisClient
from custom_components.ha_energy_agent.analysis.claude import ClaudeAnalysisClient
from custom_components.ha_energy_agent.analysis.openai_client import OpenAIAnalysisClient
from custom_components.ha_energy_agent.const import (
    CONF_AI_API_KEY,
    CONF_AI_PROVIDER,
    CONF_ANTHROPIC_API_KEY,
    DEFAULT_ANTHROPIC_MODEL,
    DEFAULT_FIXED_DAY_RATE,
    DEFAULT_FIXED_NIGHT_RATE,
    DEFAULT_HISTORY_HOURS,
    DEFAULT_INTERVAL_MINUTES,
    DEFAULT_MAX_HISTORY_POINTS,
    DEFAULT_NOTIFY_HA,
    DEFAULT_TARIFF_TYPE,
    DOMAIN,
    NOTIFICATION_ID,
    DEFAULT_OPENAI_MODEL,
    OPT_AI_MODEL,
    OPT_FIXED_DAY_RATE,
    OPT_FIXED_NIGHT_RATE,
    OPT_HISTORY_HOURS,
    OPT_INTERVAL_MINUTES,
    OPT_NORDPOOL_ENTITY_ID,
    OPT_NOTIFY_HA,
    OPT_SELECTED_ENTITIES,
    OPT_TARIFF_TYPE,
    PROVIDER_ANTHROPIC,
    PROVIDER_OPENAI,
)
from custom_components.ha_energy_agent.discovery import build_sensor_groups
from custom_components.ha_energy_agent.models import (
    AgentCycleResult,
    AnalysisResult,
    PricingContext,
)
from custom_components.ha_energy_agent.processing.history import fetch_history_bundles

_LOGGER = logging.getLogger(__name__)


def _build_ai_client(entry: ConfigEntry) -> AnalysisClient:
    """Instantiate the right AI client from config entry data.

    Handles backward compat: entries created before multi-provider support
    only have CONF_ANTHROPIC_API_KEY in entry.data.
    """
    # Legacy entries
    if CONF_AI_PROVIDER not in entry.data:
        api_key = entry.data[CONF_ANTHROPIC_API_KEY]
        model = entry.options.get(OPT_AI_MODEL, DEFAULT_ANTHROPIC_MODEL)
        return ClaudeAnalysisClient(api_key=api_key, model=model)

    provider = entry.data[CONF_AI_PROVIDER]
    api_key = entry.data[CONF_AI_API_KEY]

    if provider == PROVIDER_ANTHROPIC:
        model = entry.options.get(OPT_AI_MODEL, DEFAULT_ANTHROPIC_MODEL)
        return ClaudeAnalysisClient(api_key=api_key, model=model)

    if provider == PROVIDER_OPENAI:
        model = entry.options.get(OPT_AI_MODEL, DEFAULT_OPENAI_MODEL)
        return OpenAIAnalysisClient(api_key=api_key, model=model)

    raise ValueError(f"Unknown AI provider: {provider!r}")


class EnergyAgentCoordinator(DataUpdateCoordinator[AgentCycleResult]):
    """Coordinates periodic energy analysis cycles."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.entry = entry
        interval_minutes: int = entry.options.get(OPT_INTERVAL_MINUTES, DEFAULT_INTERVAL_MINUTES)
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=interval_minutes),
        )
        self._ai_client: AnalysisClient = _build_ai_client(entry)

    # ------------------------------------------------------------------
    # Coordinator contract
    # ------------------------------------------------------------------

    async def _async_update_data(self) -> AgentCycleResult:
        return await self._run_cycle()

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    async def async_run_now(self) -> None:
        """Trigger an immediate analysis outside the normal schedule."""
        await self.async_refresh()

    # ------------------------------------------------------------------
    # Internal cycle
    # ------------------------------------------------------------------

    async def _run_cycle(self) -> AgentCycleResult:
        started_at = datetime.now(timezone.utc)
        opts = self.entry.options

        history_hours: int = int(opts.get(OPT_HISTORY_HOURS, DEFAULT_HISTORY_HOURS))
        notify_ha: bool = bool(opts.get(OPT_NOTIFY_HA, DEFAULT_NOTIFY_HA))

        # 1. Build sensor groups from user selection
        selected: dict[str, list[str]] = opts.get(OPT_SELECTED_ENTITIES, {})
        groups = build_sensor_groups(selected, self.hass)

        if not groups:
            _LOGGER.warning("No sensor groups configured — skipping analysis cycle")
            raise UpdateFailed("No sensor groups configured")

        # 2. Fetch history
        bundles = await fetch_history_bundles(
            self.hass,
            groups,
            history_hours=history_hours,
            max_points=DEFAULT_MAX_HISTORY_POINTS,
        )

        # 3. Build pricing context
        pricing = self._build_pricing_context(opts)

        # 4. Call AI provider
        try:
            analysis: AnalysisResult = await self._ai_client.analyse(
                bundles, pricing, history_hours
            )
        except Exception as exc:
            completed_at = datetime.now(timezone.utc)
            return AgentCycleResult(
                started_at=started_at,
                completed_at=completed_at,
                duration_seconds=(completed_at - started_at).total_seconds(),
                analysis=AnalysisResult(
                    summary="Analysis failed — see logs for details.",
                    efficiency_score=0,
                ),
                error=str(exc),
            )

        completed_at = datetime.now(timezone.utc)
        duration = (completed_at - started_at).total_seconds()
        _LOGGER.info(
            "Analysis complete in %.1fs — score %d, %d tips",
            duration,
            analysis.efficiency_score,
            len(analysis.tips),
        )

        # 5. Persistent notification
        if notify_ha:
            self._send_notification(analysis)

        return AgentCycleResult(
            started_at=started_at,
            completed_at=completed_at,
            duration_seconds=duration,
            analysis=analysis,
            notification_sent=notify_ha,
        )

    # ------------------------------------------------------------------
    # Pricing context
    # ------------------------------------------------------------------

    def _build_pricing_context(self, opts: dict) -> PricingContext:
        tariff_type: str = opts.get(OPT_TARIFF_TYPE, DEFAULT_TARIFF_TYPE)
        day_rate: float = float(opts.get(OPT_FIXED_DAY_RATE, DEFAULT_FIXED_DAY_RATE))
        night_rate: float = float(opts.get(OPT_FIXED_NIGHT_RATE, DEFAULT_FIXED_NIGHT_RATE))

        # Determine day/night
        hour = datetime.now(timezone.utc).hour
        is_night = hour < 7 or hour >= 23
        current_tariff_period = "night" if is_night else "day"
        current_rate = night_rate if is_night else day_rate

        nord_pool_current: Optional[float] = None
        nordpool_entity_id: str = opts.get(OPT_NORDPOOL_ENTITY_ID, "")
        if nordpool_entity_id:
            state = self.hass.states.get(nordpool_entity_id)
            if state and state.state not in ("unavailable", "unknown"):
                try:
                    nord_pool_current = float(state.state)
                    if tariff_type == "dynamic":
                        current_rate = nord_pool_current
                except (TypeError, ValueError):
                    pass

        return PricingContext(
            tariff_type=tariff_type,
            current_rate_eur_kwh=current_rate,
            day_rate_eur_kwh=day_rate,
            night_rate_eur_kwh=night_rate,
            nord_pool_current=nord_pool_current,
            current_tariff_period=current_tariff_period,
        )

    # ------------------------------------------------------------------
    # Notification
    # ------------------------------------------------------------------

    def _send_notification(self, analysis: AnalysisResult) -> None:
        high = [t for t in analysis.tips if t.priority == "high"]
        lines = [
            f"**Efficiency score: {analysis.efficiency_score}/100**",
            "",
            analysis.summary,
        ]
        if high:
            lines += ["", "**High priority tips:**"]
            for tip in high[:3]:
                saving = f" ({tip.estimated_saving})" if tip.estimated_saving else ""
                lines.append(f"• {tip.title}{saving}")

        async_create(
            self.hass,
            message="\n".join(lines),
            title="HA Energy Agent Analysis",
            notification_id=NOTIFICATION_ID,
        )
