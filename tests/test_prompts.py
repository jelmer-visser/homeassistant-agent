"""Tests for analysis/prompts.py — prompt building."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from custom_components.ha_energy_agent.analysis.prompts import (
    SYSTEM_PROMPT,
    build_user_message,
)
from custom_components.ha_energy_agent.models import (
    DiscoveredSensor,
    GroupHistoryBundle,
    HistoryPoint,
    PricingContext,
    SensorGroup,
    SensorHistoryBundle,
    SensorStats,
)


@pytest.fixture
def pricing_fixed() -> PricingContext:
    return PricingContext(
        tariff_type="fixed",
        current_rate_eur_kwh=0.359,
        day_rate_eur_kwh=0.359,
        night_rate_eur_kwh=0.303,
        nord_pool_current=None,
        current_tariff_period="day",
    )


@pytest.fixture
def pricing_dynamic() -> PricingContext:
    return PricingContext(
        tariff_type="dynamic",
        current_rate_eur_kwh=-0.01,
        day_rate_eur_kwh=0.359,
        night_rate_eur_kwh=0.303,
        nord_pool_current=-0.01,
        current_tariff_period="day",
    )


@pytest.fixture
def simple_bundle(solar_sensor) -> GroupHistoryBundle:
    start = datetime(2024, 6, 15, 0, 0, tzinfo=timezone.utc)
    points = [HistoryPoint(ts=start + timedelta(minutes=30 * i), value=float(i * 50)) for i in range(4)]
    stats = SensorStats(min=0.0, max=150.0, mean=75.0, total=300.0, data_points=4)
    sensor_bundle = SensorHistoryBundle(
        sensor=solar_sensor,
        current_state="1200",
        current_value=1200.0,
        resampled=points,
        stats=stats,
        anomalies=[],
    )
    group = SensorGroup(label="solar", sensors=[solar_sensor])
    return GroupHistoryBundle(group=group, bundles=[sensor_bundle])


class TestBuildUserMessage:
    def test_contains_group_label(self, simple_bundle, pricing_fixed):
        msg = build_user_message([simple_bundle], pricing_fixed, history_hours=24)
        assert "SOLAR" in msg

    def test_contains_entity_id(self, simple_bundle, pricing_fixed):
        msg = build_user_message([simple_bundle], pricing_fixed, history_hours=24)
        assert "sensor.opendtu_07869c_ac_power" in msg

    def test_contains_current_state(self, simple_bundle, pricing_fixed):
        msg = build_user_message([simple_bundle], pricing_fixed, history_hours=24)
        assert "1200" in msg

    def test_contains_pricing_section(self, simple_bundle, pricing_fixed):
        msg = build_user_message([simple_bundle], pricing_fixed, history_hours=24)
        assert "PRICING" in msg

    def test_contains_fixed_rate(self, simple_bundle, pricing_fixed):
        msg = build_user_message([simple_bundle], pricing_fixed, history_hours=24)
        assert "0.359" in msg or "0.3590" in msg

    def test_contains_json_instruction(self, simple_bundle, pricing_fixed):
        msg = build_user_message([simple_bundle], pricing_fixed, history_hours=24)
        assert "JSON" in msg

    def test_anomaly_appears_in_message(self, solar_sensor, pricing_fixed):
        start = datetime(2024, 6, 15, 0, 0, tzinfo=timezone.utc)
        points = [HistoryPoint(ts=start + timedelta(minutes=30 * i), value=0.0) for i in range(4)]
        stats = SensorStats(min=0.0, max=0.0, mean=0.0, total=0.0, data_points=4)
        bundle = SensorHistoryBundle(
            sensor=solar_sensor,
            current_state="0",
            current_value=0.0,
            resampled=points,
            stats=stats,
            anomalies=["Solar power near-zero all day"],
        )
        group = SensorGroup(label="solar", sensors=[solar_sensor])
        gb = GroupHistoryBundle(group=group, bundles=[bundle])
        msg = build_user_message([gb], pricing_fixed, history_hours=24)
        assert "Solar power near-zero" in msg

    def test_dynamic_pricing_section(self, simple_bundle, pricing_dynamic):
        msg = build_user_message([simple_bundle], pricing_dynamic, history_hours=24)
        assert "dynamic" in msg.lower() or "-0.01" in msg

    def test_history_hours_mentioned(self, simple_bundle, pricing_fixed):
        msg = build_user_message([simple_bundle], pricing_fixed, history_hours=24)
        assert "24" in msg

    def test_stats_included(self, simple_bundle, pricing_fixed):
        msg = build_user_message([simple_bundle], pricing_fixed, history_hours=24)
        assert "150" in msg or "75" in msg

    def test_no_pricing_context(self, simple_bundle):
        msg = build_user_message([simple_bundle], None, history_hours=24)
        assert "PRICING" in msg

    def test_system_prompt_is_non_empty_string(self):
        assert isinstance(SYSTEM_PROMPT, str)
        assert len(SYSTEM_PROMPT) > 100

    def test_system_prompt_contains_json_schema(self):
        assert "efficiency_score" in SYSTEM_PROMPT
        assert "tips" in SYSTEM_PROMPT
