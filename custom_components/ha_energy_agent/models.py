"""Pydantic data models for HA Energy Agent."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Sensor config — built from dynamic discovery (replaces sensors.yaml)
# ---------------------------------------------------------------------------

class DiscoveredSensor(BaseModel):
    """A single HA entity discovered and categorised during setup."""
    entity_id: str
    name: str                   # friendly_name from HA attributes
    unit: str = ""              # unit_of_measurement
    role: str = ""              # power | energy | soc | temperature | binary | mode | price | etc.
    category: str = ""          # grid | solar | battery | heat_pump | temperature | pricing
    is_binary: bool = False     # True for binary_sensor.* entities
    score: int = 0              # Discovery confidence score (higher = more certain)


class SensorGroup(BaseModel):
    """Grouped discovered sensors for one energy category."""
    label: str
    sensors: list[DiscoveredSensor] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Backward-compatible alias so processing/history.py can import SensorDefinition
# ---------------------------------------------------------------------------
SensorDefinition = DiscoveredSensor


# ---------------------------------------------------------------------------
# Raw HA data
# ---------------------------------------------------------------------------

class HistoryPoint(BaseModel):
    ts: datetime
    value: float


# ---------------------------------------------------------------------------
# Processed sensor data
# ---------------------------------------------------------------------------

class SensorStats(BaseModel):
    min: float
    max: float
    mean: float
    total: float
    data_points: int


class SensorHistoryBundle(BaseModel):
    sensor: DiscoveredSensor
    current_state: str
    current_value: Optional[float] = None
    resampled: list[HistoryPoint] = Field(default_factory=list)
    stats: Optional[SensorStats] = None
    anomalies: list[str] = Field(default_factory=list)


class GroupHistoryBundle(BaseModel):
    group: SensorGroup
    bundles: list[SensorHistoryBundle] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Claude analysis output
# ---------------------------------------------------------------------------

class AnalysisTip(BaseModel):
    id: str
    priority: str               # "high" | "medium" | "low"
    category: str               # "solar" | "battery" | "heat_pump" | "grid" | "pricing" | "cross_system"
    title: str
    description: str
    estimated_saving: str = ""
    automation_yaml: str = ""


class AutomationSuggestion(BaseModel):
    id: str
    name: str
    description: str
    yaml: str


class AnalysisResult(BaseModel):
    summary: str
    efficiency_score: int = Field(ge=0, le=100)
    tips: list[AnalysisTip] = Field(default_factory=list)
    automations: list[AutomationSuggestion] = Field(default_factory=list)
    data_quality_notes: list[str] = Field(default_factory=list)
    notable_observations: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Orchestration metadata
# ---------------------------------------------------------------------------

class PricingContext(BaseModel):
    tariff_type: str                        # "fixed" | "dynamic"
    current_rate_eur_kwh: Optional[float] = None
    day_rate_eur_kwh: Optional[float] = None
    night_rate_eur_kwh: Optional[float] = None
    nord_pool_current: Optional[float] = None
    gas_rate_eur_m3: Optional[float] = None
    co2_intensity_g_kwh: Optional[float] = None
    current_tariff_period: str = ""         # "day" | "night"


class AgentCycleResult(BaseModel):
    started_at: datetime
    completed_at: datetime
    duration_seconds: float
    analysis: AnalysisResult
    notification_sent: bool = False
    error: Optional[str] = None
