"""Tests for slot-based discovery helpers."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.ha_energy_agent.const import SENSOR_SLOTS, SLOTS_BY_KEY
from custom_components.ha_energy_agent.discovery import (
    _pre_populate_slots,
    build_sensor_groups,
)
from custom_components.ha_energy_agent.models import DiscoveredSensor


def _make_sensor(entity_id: str, category: str, role: str, score: int = 80) -> DiscoveredSensor:
    return DiscoveredSensor(
        entity_id=entity_id,
        name=entity_id,
        unit="W",
        role=role,
        category=category,
        is_binary=False,
        score=score,
    )


class TestPrePopulateSlots:
    def test_fills_matching_role_and_category(self):
        discovered = {
            "grid": [
                _make_sensor("sensor.grid_power", "grid", "power", 90),
                _make_sensor("sensor.grid_energy", "grid", "energy", 85),
            ],
            "solar": [
                _make_sensor("sensor.solar_power", "solar", "power", 95),
            ],
        }
        result = _pre_populate_slots(discovered)

        assert result["grid_power_import"] == "sensor.grid_power"
        assert result["grid_power_export"] == "sensor.grid_power"
        assert result["grid_energy_import"] == "sensor.grid_energy"
        assert result["solar_power"] == "sensor.solar_power"

    def test_existing_assignments_take_precedence(self):
        discovered = {
            "solar": [_make_sensor("sensor.new_solar", "solar", "power", 99)],
        }
        existing = {"solar_power": "sensor.old_solar"}
        result = _pre_populate_slots(discovered, existing)

        assert result["solar_power"] == "sensor.old_solar"

    def test_prefers_highest_score(self):
        discovered = {
            "battery": [
                _make_sensor("sensor.bat_low", "battery", "soc", 50),
                _make_sensor("sensor.bat_high", "battery", "soc", 95),
            ]
        }
        result = _pre_populate_slots(discovered)
        assert result["battery_soc"] == "sensor.bat_high"

    def test_missing_category_leaves_slot_absent(self):
        result = _pre_populate_slots({})
        assert "heat_pump_power" not in result

    def test_empty_existing_is_safe(self):
        result = _pre_populate_slots({}, existing={})
        assert isinstance(result, dict)


class TestBuildSensorGroups:
    def _make_hass(self, entities: dict[str, dict]) -> MagicMock:
        """Return a mock hass where states.get returns state objects."""
        hass = MagicMock()

        def get_state(entity_id):
            if entity_id not in entities:
                return None
            state = MagicMock()
            state.attributes = entities[entity_id]
            return state

        hass.states.get.side_effect = get_state
        return hass

    def test_maps_slot_to_group(self):
        hass = self._make_hass({
            "sensor.pv": {"friendly_name": "PV Power", "unit_of_measurement": "W"},
        })
        groups = build_sensor_groups({"solar_power": "sensor.pv"}, hass)

        assert len(groups) == 1
        assert groups[0].label == "solar"
        assert groups[0].sensors[0].entity_id == "sensor.pv"
        assert groups[0].sensors[0].role == "power"

    def test_skips_missing_entity(self):
        hass = self._make_hass({})
        groups = build_sensor_groups({"solar_power": "sensor.missing"}, hass)
        assert groups == []

    def test_skips_empty_slot(self):
        hass = self._make_hass({})
        groups = build_sensor_groups({"solar_power": ""}, hass)
        assert groups == []

    def test_unknown_slot_key_ignored(self):
        hass = self._make_hass({"sensor.x": {}})
        groups = build_sensor_groups({"not_a_real_slot": "sensor.x"}, hass)
        assert groups == []

    def test_multiple_slots_same_category_merge(self):
        hass = self._make_hass({
            "sensor.import": {"unit_of_measurement": "W"},
            "sensor.export": {"unit_of_measurement": "W"},
        })
        groups = build_sensor_groups(
            {"grid_power_import": "sensor.import", "grid_power_export": "sensor.export"},
            hass,
        )
        assert len(groups) == 1
        assert groups[0].label == "grid"
        assert len(groups[0].sensors) == 2
