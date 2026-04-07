"""Tests for analysis/prompts.py — prompt building."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from ha_agent.analysis.prompts import (
    SYSTEM_PROMPT,
    build_pricing_context_block,
    build_user_message,
    _format_stats,
)
from ha_agent.models import (
    GroupHistoryBundle,
    HistoryPoint,
    PricingContext,
    SensorDefinition,
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
def pricing_negative_nordpool() -> PricingContext:
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
    bundle = SensorHistoryBundle(
        sensor=solar_sensor,
        current_state="1200",
        current_value=1200.0,
        resampled=points,
        stats=stats,
        anomalies=[],
    )
    group = SensorGroup(label="solar", sensors=[solar_sensor])
    return GroupHistoryBundle(group=group, bundles=[bundle])


class TestFormatStats:
    def test_none(self):
        assert _format_stats(None) == "no data"

    def test_basic(self):
        stats = SensorStats(min=1.0, max=5.0, mean=3.0, total=15.0, data_points=5)
        result = _format_stats(stats)
        assert "min=1.00" in result
        assert "max=5.00" in result
        assert "mean=3.00" in result
        assert "n=5" in result


class TestPricingContextBlock:
    def test_fixed_contains_rates(self, pricing_fixed):
        block = build_pricing_context_block(pricing_fixed)
        assert "0.359" in block
        assert "0.303" in block
        assert "fixed" in block

    def test_negative_nordpool_flagged(self, pricing_negative_nordpool):
        block = build_pricing_context_block(pricing_negative_nordpool)
        assert "NEGATIVE" in block or "FREE" in block or "opportunity" in block.lower()


class TestBuildUserMessage:
    def test_contains_group_label(self, simple_bundle, pricing_fixed):
        msg = build_user_message([simple_bundle], pricing_fixed)
        assert "SOLAR" in msg

    def test_contains_entity_id(self, simple_bundle, pricing_fixed):
        msg = build_user_message([simple_bundle], pricing_fixed)
        assert "sensor.opendtu_07869c_ac_power" in msg

    def test_contains_current_state(self, simple_bundle, pricing_fixed):
        msg = build_user_message([simple_bundle], pricing_fixed)
        assert "1200" in msg

    def test_contains_pricing_section(self, simple_bundle, pricing_fixed):
        msg = build_user_message([simple_bundle], pricing_fixed)
        assert "PRICING CONTEXT" in msg

    def test_ends_with_json_instruction(self, simple_bundle, pricing_fixed):
        msg = build_user_message([simple_bundle], pricing_fixed)
        assert "JSON" in msg

    def test_system_prompt_is_string(self):
        assert isinstance(SYSTEM_PROMPT, str)
        assert len(SYSTEM_PROMPT) > 100

    def test_anomaly_appears_in_message(self, solar_sensor, pricing_fixed):
        """Anomalies in a bundle should be visible in the generated message."""
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
        msg = build_user_message([gb], pricing_fixed)
        assert "Solar power near-zero" in msg
