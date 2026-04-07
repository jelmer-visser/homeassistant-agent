"""Core orchestration loop — one analysis cycle."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import structlog
import yaml

from ha_agent.analysis.claude import call_claude
from ha_agent.analysis.parser import parse_analysis
from ha_agent.config import Settings
from ha_agent.ha.client import HAClient
from ha_agent.ha.history import build_all_bundles
from ha_agent.ha.notify import deliver_results
from ha_agent.models import (
    AgentCycleResult,
    AnalysisResult,
    PricingContext,
    SensorDefinition,
    SensorGroup,
)

log = structlog.get_logger(__name__)

# Keep last result in memory so the optional web UI can serve it
_last_result: Optional[AgentCycleResult] = None


def get_last_result() -> Optional[AgentCycleResult]:
    return _last_result


def load_sensor_groups(config_path: Path) -> list[SensorGroup]:
    """Parse sensors.yaml into a list of SensorGroup objects."""
    with open(config_path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    groups: list[SensorGroup] = []
    for group_data in raw.get("groups", []):
        sensors = [SensorDefinition(**s) for s in group_data.get("sensors", [])]
        groups.append(SensorGroup(label=group_data["label"], sensors=sensors))
    return groups


def _build_pricing_context(settings: Settings, states: dict) -> PricingContext:
    """
    Build a PricingContext from settings and live entity states.
    `states` maps entity_id → raw HA state dict.
    """

    def _float(entity_id: str) -> Optional[float]:
        raw = states.get(entity_id, {}).get("state", "")
        try:
            return float(raw)
        except (ValueError, TypeError):
            return None

    nord_pool = _float(settings.nordpool_entity_id)
    tariff_raw = states.get("sensor.p1_meter_tariff", {}).get("state", "")
    tariff_period = "night" if tariff_raw == "1" else ("day" if tariff_raw == "2" else "")

    if settings.tariff_type == "fixed":
        current_rate = (
            settings.fixed_night_rate if tariff_period == "night" else settings.fixed_day_rate
        )
    else:
        current_rate = nord_pool

    return PricingContext(
        tariff_type=settings.tariff_type,
        current_rate_eur_kwh=current_rate,
        day_rate_eur_kwh=settings.fixed_day_rate,
        night_rate_eur_kwh=settings.fixed_night_rate,
        nord_pool_current=nord_pool,
        gas_rate_eur_m3=_float("sensor.cic_gas_price"),
        co2_intensity_g_kwh=_float("sensor.electricity_maps_co2_intensity"),
        current_tariff_period=tariff_period,
    )


async def run_cycle(settings: Settings) -> AgentCycleResult:
    """
    Execute one full analysis cycle:
      1. Load sensor config
      2. Fetch current states (for pricing context)
      3. Fetch + process 24h history for all sensors
      4. Call Claude
      5. Parse response
      6. Deliver (HA notification + JSON log)
    """
    global _last_result
    started_at = datetime.now(tz=timezone.utc)
    log.info("cycle_start", started_at=started_at.isoformat())

    async with HAClient(settings) as client:
        # --- 1. Verify connectivity ---
        try:
            ha_version = await client.check_connectivity()
            log.info("ha_connected", version=ha_version)
        except Exception as exc:
            log.error("ha_connectivity_failed", error=str(exc))
            raise

        # --- 2. Load sensor groups ---
        sensor_groups = load_sensor_groups(settings.sensors_config_path)
        log.info("sensors_loaded", groups=len(sensor_groups))

        # --- 3. Fetch pricing-relevant states for context ---
        pricing_entity_ids = [
            settings.nordpool_entity_id,
            "sensor.p1_meter_tariff",
            "sensor.cic_gas_price",
            "sensor.electricity_maps_co2_intensity",
        ]
        pricing_states = await client.get_states_bulk(pricing_entity_ids)
        pricing = _build_pricing_context(settings, pricing_states)
        log.info(
            "pricing_context",
            tariff=pricing.tariff_type,
            period=pricing.current_tariff_period,
            rate=pricing.current_rate_eur_kwh,
            nord_pool=pricing.nord_pool_current,
        )

        # --- 4. Fetch + process all sensor history ---
        log.info("fetching_history", history_hours=settings.history_hours)
        group_bundles = await build_all_bundles(client, sensor_groups, settings)
        total_sensors = sum(len(gb.bundles) for gb in group_bundles)
        log.info("history_fetched", sensors=total_sensors)

        # --- 5. Call Claude ---
        raw_response = await call_claude(group_bundles, pricing, settings)

        # --- 6. Parse response ---
        analysis = parse_analysis(raw_response)
        log.info(
            "analysis_complete",
            score=analysis.efficiency_score,
            tips=len(analysis.tips),
            automations=len(analysis.automations),
        )

        # --- 7. Build cycle result ---
        completed_at = datetime.now(tz=timezone.utc)
        cycle_result = AgentCycleResult(
            started_at=started_at,
            completed_at=completed_at,
            duration_seconds=(completed_at - started_at).total_seconds(),
            analysis=analysis,
        )

        # --- 8. Deliver ---
        cycle_result = await deliver_results(client, cycle_result, settings)

    _last_result = cycle_result
    log.info(
        "cycle_complete",
        duration_seconds=cycle_result.duration_seconds,
        score=cycle_result.analysis.efficiency_score,
        notification_sent=cycle_result.notification_sent,
        log_path=cycle_result.log_path,
    )
    return cycle_result
