"""All Pydantic data models for the HA energy agent."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Sensor configuration (from sensors.yaml)
# ---------------------------------------------------------------------------

class SensorDefinition(BaseModel):
    entity_id: str
    name: str
    unit: str = ""
    role: str = ""
    group: str = ""
    is_binary: bool = False


class SensorGroup(BaseModel):
    label: str
    sensors: list[SensorDefinition]


# ---------------------------------------------------------------------------
# Raw HA data
# ---------------------------------------------------------------------------

class EntityState(BaseModel):
    entity_id: str
    state: str
    last_changed: Optional[datetime] = None
    unit: str = ""
    friendly_name: str = ""


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
    total: float          # sum of all values (useful for energy sensors)
    data_points: int


class SensorHistoryBundle(BaseModel):
    sensor: SensorDefinition
    current_state: str
    current_value: Optional[float] = None
    resampled: list[HistoryPoint] = Field(default_factory=list)
    stats: Optional[SensorStats] = None
    anomalies: list[str] = Field(default_factory=list)


class GroupHistoryBundle(BaseModel):
    group: SensorGroup
    bundles: list[SensorHistoryBundle]


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
# Agent cycle metadata
# ---------------------------------------------------------------------------

class AgentCycleResult(BaseModel):
    started_at: datetime
    completed_at: datetime
    duration_seconds: float
    analysis: AnalysisResult
    notification_sent: bool = False
    log_path: str = ""
    error: Optional[str] = None


class PricingContext(BaseModel):
    tariff_type: str                        # "fixed" or "dynamic"
    current_rate_eur_kwh: Optional[float] = None
    day_rate_eur_kwh: Optional[float] = None
    night_rate_eur_kwh: Optional[float] = None
    nord_pool_current: Optional[float] = None
    gas_rate_eur_m3: Optional[float] = None
    co2_intensity_g_kwh: Optional[float] = None
    current_tariff_period: str = ""         # "day" or "night"
