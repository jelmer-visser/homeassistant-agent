"""Sensor platform for HA Energy Agent — exposes 4 read-only sensor entities."""
from __future__ import annotations

import logging
from typing import Any, Optional

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from custom_components.ha_energy_agent.const import (
    DOMAIN,
    SENSOR_EFFICIENCY_SCORE,
    SENSOR_HIGH_PRIORITY_TIPS,
    SENSOR_LAST_ANALYSIS,
    SENSOR_TIPS_COUNT,
)
from custom_components.ha_energy_agent.coordinator import EnergyAgentCoordinator
from custom_components.ha_energy_agent.models import AgentCycleResult

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: EnergyAgentCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            EnergyScoreSensor(coordinator, entry),
            LastAnalysisSensor(coordinator, entry),
            TipsCountSensor(coordinator, entry),
            HighPriorityTipsSensor(coordinator, entry),
        ]
    )


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------

class _EnergyAgentSensor(CoordinatorEntity[EnergyAgentCoordinator], SensorEntity):
    """Base sensor — shares coordinator and entry metadata."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: EnergyAgentCoordinator,
        entry: ConfigEntry,
        suffix: str,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{suffix}"

    @property
    def _result(self) -> Optional[AgentCycleResult]:
        return self.coordinator.data

    @property
    def device_info(self) -> dict:
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": "HA Energy Agent",
            "manufacturer": "Anthropic / Claude",
            "model": "Energy Optimization AI",
            "entry_type": "service",
        }


# ---------------------------------------------------------------------------
# Sensor 1: Efficiency Score (0–100)
# ---------------------------------------------------------------------------

class EnergyScoreSensor(_EnergyAgentSensor):
    _attr_name = "Efficiency Score"
    _attr_icon = "mdi:speedometer"
    _attr_native_unit_of_measurement = "%"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: EnergyAgentCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, SENSOR_EFFICIENCY_SCORE)

    @property
    def native_value(self) -> Optional[int]:
        if self._result and not self._result.error:
            return self._result.analysis.efficiency_score
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        if not self._result or self._result.error:
            return {}
        analysis = self._result.analysis
        return {
            "summary": analysis.summary,
            "notable_observations": analysis.notable_observations,
            "data_quality_notes": analysis.data_quality_notes,
        }


# ---------------------------------------------------------------------------
# Sensor 2: Last Analysis Timestamp
# ---------------------------------------------------------------------------

class LastAnalysisSensor(_EnergyAgentSensor):
    _attr_name = "Last Analysis"
    _attr_icon = "mdi:clock-check-outline"
    _attr_device_class = "timestamp"

    def __init__(self, coordinator: EnergyAgentCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, SENSOR_LAST_ANALYSIS)

    @property
    def native_value(self):
        if self._result:
            return self._result.completed_at
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        if not self._result:
            return {}
        return {
            "duration_seconds": round(self._result.duration_seconds, 1),
            "error": self._result.error,
        }


# ---------------------------------------------------------------------------
# Sensor 3: Total Tips Count
# ---------------------------------------------------------------------------

class TipsCountSensor(_EnergyAgentSensor):
    _attr_name = "Tips Count"
    _attr_icon = "mdi:lightbulb-group-outline"
    _attr_native_unit_of_measurement = "tips"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: EnergyAgentCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, SENSOR_TIPS_COUNT)

    @property
    def native_value(self) -> Optional[int]:
        if self._result and not self._result.error:
            return len(self._result.analysis.tips)
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        if not self._result or self._result.error:
            return {}
        tips = self._result.analysis.tips
        return {
            "high": sum(1 for t in tips if t.priority == "high"),
            "medium": sum(1 for t in tips if t.priority == "medium"),
            "low": sum(1 for t in tips if t.priority == "low"),
            "tips": [
                {
                    "id": t.id,
                    "priority": t.priority,
                    "category": t.category,
                    "title": t.title,
                    "description": t.description,
                    "estimated_saving": t.estimated_saving,
                }
                for t in tips
            ],
        }


# ---------------------------------------------------------------------------
# Sensor 4: High Priority Tips Count
# ---------------------------------------------------------------------------

class HighPriorityTipsSensor(_EnergyAgentSensor):
    _attr_name = "High Priority Tips"
    _attr_icon = "mdi:alert-circle-outline"
    _attr_native_unit_of_measurement = "tips"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: EnergyAgentCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, SENSOR_HIGH_PRIORITY_TIPS)

    @property
    def native_value(self) -> Optional[int]:
        if self._result and not self._result.error:
            return sum(1 for t in self._result.analysis.tips if t.priority == "high")
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        if not self._result or self._result.error:
            return {}
        high_tips = [t for t in self._result.analysis.tips if t.priority == "high"]
        return {
            "tips": [
                {
                    "id": t.id,
                    "category": t.category,
                    "title": t.title,
                    "description": t.description,
                    "estimated_saving": t.estimated_saving,
                    "automation_yaml": t.automation_yaml,
                }
                for t in high_tips
            ]
        }
