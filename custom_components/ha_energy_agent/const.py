"""Constants for HA Energy Agent integration."""
from __future__ import annotations

DOMAIN = "ha_energy_agent"
VERSION = "1.0.0"

# Config entry keys (stored in entry.data — encrypted by HA)
CONF_ANTHROPIC_API_KEY = "anthropic_api_key"

# Options keys (stored in entry.options)
OPT_SELECTED_ENTITIES = "selected_entities"
OPT_INTERVAL_MINUTES = "interval_minutes"
OPT_HISTORY_HOURS = "history_hours"
OPT_TARIFF_TYPE = "tariff_type"
OPT_FIXED_DAY_RATE = "fixed_day_rate"
OPT_FIXED_NIGHT_RATE = "fixed_night_rate"
OPT_NORDPOOL_ENTITY_ID = "nordpool_entity_id"
OPT_NOTIFY_HA = "notify_ha"

# Defaults
DEFAULT_INTERVAL_MINUTES = 30
DEFAULT_HISTORY_HOURS = 24
DEFAULT_MAX_HISTORY_POINTS = 48
DEFAULT_TARIFF_TYPE = "fixed"
DEFAULT_FIXED_DAY_RATE = 0.259
DEFAULT_FIXED_NIGHT_RATE = 0.259
DEFAULT_NORDPOOL_ENTITY_ID = ""
DEFAULT_NOTIFY_HA = True

# Sensor entity unique ID suffixes
SENSOR_EFFICIENCY_SCORE = "efficiency_score"
SENSOR_LAST_ANALYSIS = "last_analysis"
SENSOR_TIPS_COUNT = "tips_count"
SENSOR_HIGH_PRIORITY_TIPS = "high_priority_tips"

# Notification ID in HA
NOTIFICATION_ID = "ha_energy_agent_analysis"

# Service names
SERVICE_RUN_NOW = "run_analysis_now"

# Discovery category labels
CAT_GRID = "grid"
CAT_SOLAR = "solar"
CAT_BATTERY = "battery"
CAT_HEAT_PUMP = "heat_pump"
CAT_TEMPERATURE = "temperature"
CAT_PRICING = "pricing"

ALL_CATEGORIES = [CAT_GRID, CAT_SOLAR, CAT_BATTERY, CAT_HEAT_PUMP, CAT_TEMPERATURE, CAT_PRICING]
