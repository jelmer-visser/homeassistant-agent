"""Shared test fixtures."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from ha_agent.models import HistoryPoint, SensorDefinition, SensorStats


@pytest.fixture
def solar_sensor() -> SensorDefinition:
    return SensorDefinition(
        entity_id="sensor.opendtu_07869c_ac_power",
        name="Solar total AC power",
        unit="W",
        role="power",
        group="solar",
    )


@pytest.fixture
def battery_soc_sensor() -> SensorDefinition:
    return SensorDefinition(
        entity_id="sensor.zendure_2400_ac_laadpercentage",
        name="Battery combined SoC",
        unit="%",
        role="soc",
        group="battery",
    )


@pytest.fixture
def relay_sensor() -> SensorDefinition:
    return SensorDefinition(
        entity_id="sensor.zendure_2400_ac_relais_schakelingen_totaal_vandaag",
        name="Battery relay switches today",
        unit="count",
        role="counter",
        group="battery",
    )


@pytest.fixture
def now() -> datetime:
    return datetime(2024, 6, 15, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def start(now) -> datetime:
    return now - timedelta(hours=24)


@pytest.fixture
def sample_raw_history(start) -> list[dict]:
    """48 synthetic HA history points spaced 30 min apart."""
    points = []
    for i in range(48):
        ts = start + timedelta(minutes=30 * i)
        points.append({
            "state": str(100 + i * 10),
            "last_changed": ts.isoformat(),
        })
    return points
