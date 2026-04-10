"""Dynamic entity discovery and categorisation engine.

Scans all entities in Home Assistant and assigns each to an energy category
(grid, solar, battery, heat_pump, temperature, pricing) using a scoring system
based on entity_id keywords, device_class, unit_of_measurement, and friendly name.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant, State

from custom_components.ha_energy_agent.const import (
    ALL_CATEGORIES,
    CAT_BATTERY,
    CAT_GRID,
    CAT_HEAT_PUMP,
    CAT_PRICING,
    CAT_SOLAR,
    CAT_TEMPERATURE,
    SENSOR_SLOTS,
    SLOTS_BY_KEY,
)
from custom_components.ha_energy_agent.models import DiscoveredSensor, SensorGroup

# ---------------------------------------------------------------------------
# Scoring rules — (pattern, category, score)
# Pattern is matched against the FULL entity_id (lower-cased).
# Friendly name keywords are matched separately at lower weight.
# ---------------------------------------------------------------------------

@dataclass
class Rule:
    pattern: str          # regex applied to entity_id (lower-cased)
    category: str
    score: int
    role: str = ""

# High-confidence entity_id keyword rules
_ENTITY_ID_RULES: list[Rule] = [
    # ── Grid ──────────────────────────────────────────────────────────────
    Rule(r"p1_meter", CAT_GRID, 90, "power"),
    Rule(r"homewizard", CAT_GRID, 80, "power"),
    Rule(r"netstroom", CAT_GRID, 85, "energy"),
    Rule(r"grid.*(import|export|power|energy)", CAT_GRID, 85, "energy"),
    Rule(r"(import|export).*(kwh|vandaag|today)", CAT_GRID, 70, "energy"),
    Rule(r"tariff|tarief", CAT_GRID, 85, "mode"),
    Rule(r"meter.*power", CAT_GRID, 60, "power"),

    # ── Solar ─────────────────────────────────────────────────────────────
    Rule(r"opendtu", CAT_SOLAR, 95, "power"),
    Rule(r"hms_\d+_\d+t", CAT_SOLAR, 95, "power"),        # HMS-1600-4T etc.
    Rule(r"solcast", CAT_SOLAR, 95, "energy"),
    Rule(r"solar.*(power|energy|yield|production)", CAT_SOLAR, 85, "power"),
    Rule(r"pv.*(power|energy|yield|production)", CAT_SOLAR, 85, "power"),
    Rule(r"(yield|production).*day", CAT_SOLAR, 75, "energy"),
    Rule(r"inverter.*(power|energy)", CAT_SOLAR, 80, "power"),
    Rule(r"zon(ne)?.*(vermogen|energie)", CAT_SOLAR, 80, "power"),  # Dutch

    # ── Battery ───────────────────────────────────────────────────────────
    Rule(r"zendure", CAT_BATTERY, 95, "soc"),
    Rule(r"sf2400", CAT_BATTERY, 95, "soc"),
    Rule(r"ab3000", CAT_BATTERY, 95, "soc"),
    Rule(r"battery.*(soc|level|charge|percent|power)", CAT_BATTERY, 85, "soc"),
    Rule(r"(soc|state_of_charge)", CAT_BATTERY, 80, "soc"),
    Rule(r"laadpercentage|electric_level", CAT_BATTERY, 90, "soc"),
    Rule(r"bat.*(in|out|power|level)", CAT_BATTERY, 80, "power"),
    Rule(r"relais", CAT_BATTERY, 85, "mode"),
    Rule(r"(rte|round.trip)", CAT_BATTERY, 80, "efficiency"),
    Rule(r"accu|batterij", CAT_BATTERY, 75, "soc"),         # Dutch

    # ── Heat pump ─────────────────────────────────────────────────────────
    Rule(r"heatpump|heat_pump", CAT_HEAT_PUMP, 95, "power"),
    Rule(r"quatt", CAT_HEAT_PUMP, 95, "power"),
    Rule(r"warmtepomp", CAT_HEAT_PUMP, 90, "power"),         # Dutch
    Rule(r"(hp1|hp2).*_(power|cop|temp|on)", CAT_HEAT_PUMP, 90, "power"),
    Rule(r"boiler.*(temp|flame|water)", CAT_HEAT_PUMP, 85, "temperature"),
    Rule(r"dhw|domestic_hot_water", CAT_HEAT_PUMP, 85, "binary"),
    Rule(r"flowmeter|flow_rate|flowrate", CAT_HEAT_PUMP, 80, "flow"),
    Rule(r"\bcop\b", CAT_HEAT_PUMP, 80, "efficiency"),
    Rule(r"thermostat.*(room|setpoint|control)", CAT_HEAT_PUMP, 80, "temperature"),
    Rule(r"insights.*(cop|heat|electric)", CAT_HEAT_PUMP, 85, "efficiency"),
    Rule(r"defrost", CAT_HEAT_PUMP, 85, "binary"),

    # ── Temperature ───────────────────────────────────────────────────────
    Rule(r"(outdoor|outside|buiten).*temp", CAT_TEMPERATURE, 90, "temperature"),
    Rule(r"buitenmeter.*temp", CAT_TEMPERATURE, 95, "temperature"),
    Rule(r"indoor.*temp|room.*temp|woonkamer.*temp", CAT_TEMPERATURE, 85, "temperature"),
    Rule(r"co2.*(monitor|sensor|level|carbon)", CAT_TEMPERATURE, 85, "air_quality"),
    Rule(r"carbon_dioxide", CAT_TEMPERATURE, 85, "air_quality"),
    Rule(r"humidity|vochtigheid", CAT_TEMPERATURE, 80, "humidity"),
    Rule(r"thermostaat.*temperature", CAT_TEMPERATURE, 80, "temperature"),

    # ── Pricing ───────────────────────────────────────────────────────────
    Rule(r"nordpool|nord_pool", CAT_PRICING, 95, "price"),
    Rule(r"electricity.*(price|tariff|rate)", CAT_PRICING, 90, "price"),
    Rule(r"(day|night).*price|price.*(day|night)", CAT_PRICING, 85, "price"),
    Rule(r"gas.*(price|tariff|rate)", CAT_PRICING, 85, "price"),
    Rule(r"co2.*(intensity|grid)", CAT_PRICING, 80, "co2"),
    Rule(r"electricity_maps", CAT_PRICING, 85, "co2"),
    Rule(r"cic.*(electricity|gas|tariff|price)", CAT_PRICING, 85, "price"),
    Rule(r"tibber|energyzero|anwb", CAT_PRICING, 85, "price"),  # common NL providers
]

# Device class → (category, role, score) mappings
_DEVICE_CLASS_MAP: dict[str, tuple[str, str, int]] = {
    "energy":              (CAT_GRID,        "energy",      50),
    "power":               (CAT_GRID,        "power",       40),  # low — many devices have power
    "battery":             (CAT_BATTERY,     "soc",         70),
    "temperature":         (CAT_TEMPERATURE, "temperature", 60),
    "humidity":            (CAT_TEMPERATURE, "humidity",    60),
    "carbon_dioxide":      (CAT_TEMPERATURE, "air_quality", 65),
    "monetary":            (CAT_PRICING,     "price",       70),
    "frequency":           (CAT_GRID,        "power",       35),
    "current":             (CAT_GRID,        "power",       35),
    "voltage":             (CAT_GRID,        "power",       35),
    "reactive_power":      (CAT_GRID,        "power",       50),
    "apparent_power":      (CAT_GRID,        "power",       50),
    "illuminance":         ("",              "",            0),
    "signal_strength":     ("",              "",            0),
    "timestamp":           ("",              "",            0),
}

# Unit → (category, role, score)
_UNIT_MAP: dict[str, tuple[str, str, int]] = {
    "W":      (CAT_GRID,     "power",  30),
    "kW":     (CAT_GRID,     "power",  30),
    "Wh":     (CAT_SOLAR,    "energy", 30),
    "kWh":    (CAT_GRID,     "energy", 30),
    "°C":     (CAT_TEMPERATURE, "temperature", 40),
    "%":      (CAT_BATTERY,  "soc",    20),   # very generic, low score
    "€/kWh":  (CAT_PRICING,  "price",  70),
    "€/m³":   (CAT_PRICING,  "price",  70),
    "ppm":    (CAT_TEMPERATURE, "air_quality", 60),
    "L/h":    (CAT_HEAT_PUMP, "flow",  65),
    "lpm":    (CAT_HEAT_PUMP, "flow",  65),
}

# Friendly name keyword → (category, score)
_FRIENDLY_NAME_KEYWORDS: list[tuple[str, str, int]] = [
    ("solar",     CAT_SOLAR,       30),
    ("zon",       CAT_SOLAR,       30),   # Dutch
    ("battery",   CAT_BATTERY,     30),
    ("batterij",  CAT_BATTERY,     30),   # Dutch
    ("heat pump", CAT_HEAT_PUMP,   35),
    ("warmtepomp",CAT_HEAT_PUMP,   35),   # Dutch
    ("grid",      CAT_GRID,        25),
    ("net",       CAT_GRID,        20),   # Dutch "net"
    ("price",     CAT_PRICING,     30),
    ("prijs",     CAT_PRICING,     30),   # Dutch
    ("temperature",CAT_TEMPERATURE,30),
    ("temperatuur",CAT_TEMPERATURE,30),   # Dutch
    ("outdoor",   CAT_TEMPERATURE, 35),
    ("buiten",    CAT_TEMPERATURE, 35),   # Dutch
    ("indoor",    CAT_TEMPERATURE, 30),
    ("binnen",    CAT_TEMPERATURE, 30),   # Dutch
]

# Score threshold to include an entity
_MIN_SCORE = 30

# Entities explicitly excluded (generic status, availability, uptime etc.)
_EXCLUDE_PATTERNS = [
    r"_availability$",
    r"_uptime$",
    r"_rssi$",
    r"_signal",
    r"_lqi$",
    r"_linkquality$",
    r"_battery$",      # device battery level — not energy battery
    r"update\.",       # update entities
    r"_firmware",
    r"_version$",
    r"_status$",
    r"_ip_",
    r"_mac_",
    r"_ssid",
]
_EXCLUDE_RE = re.compile("|".join(_EXCLUDE_PATTERNS))

# Device platforms that should always be excluded
_EXCLUDE_PLATFORMS = {"update", "button", "scene", "script", "automation"}


def _should_exclude(entity_id: str, platform: str) -> bool:
    """Return True if this entity should be skipped entirely."""
    if platform in _EXCLUDE_PLATFORMS:
        return True
    if _EXCLUDE_RE.search(entity_id):
        return True
    return False


def _score_entity(
    entity_id: str,
    friendly_name: str,
    device_class: Optional[str],
    unit: Optional[str],
    platform: str,
) -> dict[str, int]:
    """Return a score-per-category dict for one entity."""
    scores: dict[str, int] = {c: 0 for c in ALL_CATEGORIES}
    eid_lower = entity_id.lower()
    fn_lower = (friendly_name or "").lower()

    # 1. Entity ID keyword rules
    for rule in _ENTITY_ID_RULES:
        if re.search(rule.pattern, eid_lower):
            scores[rule.category] += rule.score

    # 2. Device class
    if device_class and device_class in _DEVICE_CLASS_MAP:
        cat, _, sc = _DEVICE_CLASS_MAP[device_class]
        if cat:
            scores[cat] += sc

    # 3. Unit
    if unit and unit in _UNIT_MAP:
        cat, _, sc = _UNIT_MAP[unit]
        if cat:
            scores[cat] += sc

    # 4. Friendly name keywords
    for kw, cat, sc in _FRIENDLY_NAME_KEYWORDS:
        if kw in fn_lower:
            scores[cat] += sc

    return scores


def _infer_role(entity_id: str, category: str, device_class: Optional[str], unit: Optional[str]) -> str:
    """Infer a semantic role for an entity."""
    eid = entity_id.lower()

    # Check entity ID rules for specific role
    for rule in _ENTITY_ID_RULES:
        if rule.role and re.search(rule.pattern, eid):
            return rule.role

    # Fallback by device_class
    if device_class in _DEVICE_CLASS_MAP:
        _, role, _ = _DEVICE_CLASS_MAP[device_class]
        if role:
            return role

    # Fallback by unit
    if unit in _UNIT_MAP:
        _, role, _ = _UNIT_MAP[unit]
        if role:
            return role

    # Fallback by entity domain
    if entity_id.startswith("binary_sensor."):
        return "binary"

    return ""


def discover_entities(hass: "HomeAssistant") -> dict[str, list[DiscoveredSensor]]:
    """
    Scan all HA states and categorise entities.

    Returns a dict: category → list[DiscoveredSensor], sorted by score descending.
    Only includes entities scoring >= _MIN_SCORE for at least one category.
    """
    from homeassistant.helpers import entity_registry as er

    entity_reg = er.async_get(hass)
    all_states: list["State"] = hass.states.async_all()

    result: dict[str, list[DiscoveredSensor]] = {c: [] for c in ALL_CATEGORIES}

    for state in all_states:
        entity_id = state.entity_id
        attrs = state.attributes or {}

        # Determine platform from entity registry
        entry = entity_reg.async_get(entity_id)
        platform = (entry.platform or "") if entry else ""

        if _should_exclude(entity_id, platform):
            continue

        friendly_name: str = attrs.get("friendly_name") or _entity_id_to_name(entity_id)
        device_class: Optional[str] = attrs.get("device_class")
        unit: Optional[str] = attrs.get("unit_of_measurement") or ""
        is_binary = entity_id.startswith("binary_sensor.")

        scores = _score_entity(entity_id, friendly_name, device_class, unit, platform)
        best_cat = max(scores, key=lambda c: scores[c])
        best_score = scores[best_cat]

        if best_score < _MIN_SCORE:
            continue

        role = _infer_role(entity_id, best_cat, device_class, unit)

        sensor = DiscoveredSensor(
            entity_id=entity_id,
            name=friendly_name,
            unit=unit,
            role=role,
            category=best_cat,
            is_binary=is_binary,
            score=best_score,
        )
        result[best_cat].append(sensor)

    # Sort each category by score descending
    for cat in ALL_CATEGORIES:
        result[cat].sort(key=lambda s: s.score, reverse=True)

    return result


def _entity_id_to_name(entity_id: str) -> str:
    """Convert entity_id to a human-readable name as fallback."""
    # "sensor.opendtu_07869c_ac_power" → "Opendtu 07869c Ac Power"
    parts = entity_id.split(".", 1)
    name_part = parts[1] if len(parts) > 1 else entity_id
    return name_part.replace("_", " ").title()


def _pre_populate_slots(
    discovered: dict[str, list[DiscoveredSensor]],
    existing: Optional[dict[str, str]] = None,
) -> dict[str, str]:
    """
    Return a slot_key → entity_id mapping pre-filled from discovery results.

    For each slot, pick the highest-scoring sensor in the matching category
    whose role matches the slot role. Existing assignments always take precedence
    and are never overwritten.
    """
    result: dict[str, str] = {}
    existing = existing or {}

    for slot in SENSOR_SLOTS:
        if slot.key in existing and existing[slot.key]:
            result[slot.key] = existing[slot.key]
            continue

        candidates = discovered.get(slot.category, [])
        # Find best match: role must match, then highest score
        best: Optional[DiscoveredSensor] = None
        for sensor in candidates:
            if sensor.role == slot.role:
                if best is None or sensor.score > best.score:
                    best = sensor
        if best is not None:
            result[slot.key] = best.entity_id

    return result


def build_sensor_groups(
    selected: dict[str, str],
    hass: "HomeAssistant",
) -> list[SensorGroup]:
    """
    Build SensorGroup list from the user-confirmed slot assignments.

    `selected` maps slot_key → entity_id.
    Role and category are read from SLOTS_BY_KEY — no inference needed.
    Missing or unavailable entities are silently skipped.
    """
    groups_map: dict[str, list[DiscoveredSensor]] = {c: [] for c in ALL_CATEGORIES}

    for slot_key, entity_id in selected.items():
        if not entity_id:
            continue
        slot = SLOTS_BY_KEY.get(slot_key)
        if slot is None:
            continue
        state = hass.states.get(entity_id)
        if state is None:
            continue
        attrs = state.attributes or {}
        friendly_name = attrs.get("friendly_name") or _entity_id_to_name(entity_id)
        unit = attrs.get("unit_of_measurement") or slot.unit_hint
        is_binary = entity_id.startswith("binary_sensor.")

        groups_map[slot.category].append(DiscoveredSensor(
            entity_id=entity_id,
            name=friendly_name,
            unit=unit,
            role=slot.role,
            category=slot.category,
            is_binary=is_binary,
            score=0,
        ))

    return [
        SensorGroup(label=cat, sensors=sensors)
        for cat, sensors in groups_map.items()
        if sensors
    ]


def discovery_summary(
    discovered: dict[str, list[DiscoveredSensor]],
    pre_populated: Optional[dict[str, str]] = None,
) -> str:
    """Human-readable summary of discovery results for the config flow UI."""
    parts = []
    for cat in ALL_CATEGORIES:
        n = len(discovered.get(cat, []))
        if n > 0:
            label = cat.replace("_", " ").title()
            parts.append(f"{n} {label}")
    if not parts:
        return "No relevant energy entities found."
    summary = "Found: " + ", ".join(parts) + "."
    if pre_populated is not None:
        filled = sum(1 for v in pre_populated.values() if v)
        summary += f" Pre-filled {filled}/{len(SENSOR_SLOTS)} slots."
    return summary
