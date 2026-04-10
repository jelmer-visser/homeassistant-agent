"""Shared test fixtures."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from custom_components.ha_energy_agent.models import (
    DiscoveredSensor,
    HistoryPoint,
    SensorStats,
)


@pytest.fixture
def solar_sensor() -> DiscoveredSensor:
    return DiscoveredSensor(
        entity_id="sensor.opendtu_07869c_ac_power",
        name="Solar total AC power",
        unit="W",
        role="power",
        category="solar",
    )


@pytest.fixture
def battery_soc_sensor() -> DiscoveredSensor:
    return DiscoveredSensor(
        entity_id="sensor.zendure_2400_ac_laadpercentage",
        name="Battery combined SoC",
        unit="%",
        role="soc",
        category="battery",
    )


@pytest.fixture
def grid_sensor() -> DiscoveredSensor:
    return DiscoveredSensor(
        entity_id="sensor.p1_meter_power",
        name="Grid power",
        unit="W",
        role="power",
        category="grid",
    )


@pytest.fixture
def now() -> datetime:
    return datetime(2024, 6, 15, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def start(now) -> datetime:
    return now - timedelta(hours=24)


@pytest.fixture
def sample_points(start) -> list[HistoryPoint]:
    """48 synthetic history points spaced 30 min apart."""
    return [
        HistoryPoint(ts=start + timedelta(minutes=30 * i), value=float(100 + i * 10))
        for i in range(48)
    ]
