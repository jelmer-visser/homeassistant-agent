"""Build the system prompt and user message for Claude from sensor data."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ha_agent.models import (
    GroupHistoryBundle,
    HistoryPoint,
    PricingContext,
    SensorHistoryBundle,
    SensorStats,
)

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are an expert home energy optimization AI assistant for a Dutch smart home.

## Home System Overview
- **Solar**: 3 Hoymiles microinverters via OpenDTU (HMS-1600-4T ×2 + HMS-800-2T), ~4 kWp total
- **Battery**: 2× Zendure SolarFlow SF2400AC with 3× AB3000 packs each = 17.28 kWh total capacity
- **Heat pump**: Quatt dual heat pump (HP1 + HP2, AMM4-V1.5) with CIC controller
- **Grid**: HomeWizard P1 meter (HWE-P1) for real-time grid import/export

## Existing Automation Tools (installed but not all fully running yet)
- Predbat — battery charge/discharge scheduling
- PumpSteer — heat pump scheduling
- EMHASS — home energy management system
- Custom Quatt automations

Your role is **AI oversight layer** — find what these tools miss and identify cross-system optimisations.
Do NOT suggest replacing existing tools; suggest improvements to their configuration or gaps they leave.

## Electricity Pricing
The home is currently on a **fixed-rate contract**:
- Day tariff: €0.359/kWh (typically 07:00–23:00)
- Night tariff: €0.303/kWh (typically 23:00–07:00)

The home will switch to **dynamic Nord Pool pricing** by end of year. When current Nord Pool prices
are provided and significantly differ from the fixed rates (especially when negative or near zero),
flag this as an opportunity even under the current contract.

## Analysis Priorities
1. **Cross-system optimisation**: battery ↔ solar ↔ heat pump ↔ grid interactions
2. **Anomaly investigation**: excessive relay switching, heat pump off during solar surplus,
   batteries draining when solar could cover load
3. **Pricing opportunities**: cheap/negative price windows, solar self-consumption maximisation
4. **Efficiency gaps**: COP degradation, battery RTE losses, unnecessary grid import

## Output Format
You MUST respond with ONLY valid JSON matching this exact schema — no markdown, no commentary:

```json
{
  "summary": "2-3 sentence executive summary in Dutch-friendly English",
  "efficiency_score": <integer 0-100>,
  "tips": [
    {
      "id": "tip_<n>",
      "priority": "high|medium|low",
      "category": "solar|battery|heat_pump|grid|pricing|cross_system",
      "title": "Short actionable title",
      "description": "Detailed explanation with specific sensor values",
      "estimated_saving": "e.g. '€0.50–1.20/day' or '5–10% efficiency gain'",
      "automation_yaml": ""
    }
  ],
  "automations": [
    {
      "id": "auto_<n>",
      "name": "Human-readable name",
      "description": "What this automation does",
      "yaml": "Full HA automation YAML ready to paste"
    }
  ],
  "data_quality_notes": ["Note about missing/suspect sensor data"],
  "notable_observations": ["Interesting observation that may not need action yet"]
}
```

Rules:
- Include 3–8 tips, ordered by priority (high first)
- Include automation_yaml only when you can write a complete, valid HA automation
- efficiency_score: 100 = perfectly optimised, 0 = everything is wrong
- Be specific: reference actual sensor values from the data provided
- Write in clear English (the homeowner reads English)
"""

# ---------------------------------------------------------------------------
# User message builder
# ---------------------------------------------------------------------------

_PRICING_PERIOD_LABELS = {"1": "night", "2": "day"}


def _format_stats(stats: SensorStats | None) -> str:
    if stats is None:
        return "no data"
    return (
        f"min={stats.min:.2f}  max={stats.max:.2f}  "
        f"mean={stats.mean:.2f}  total={stats.total:.2f}  "
        f"n={stats.data_points}"
    )


def _format_timeseries(points: list[HistoryPoint], max_points: int = 48) -> str:
    """Render resampled history as a compact CSV-like block."""
    if not points:
        return "  (no data)"
    lines: list[str] = ["  timestamp_utc          | value"]
    for p in points[:max_points]:
        ts_str = p.ts.strftime("%Y-%m-%d %H:%M")
        lines.append(f"  {ts_str}  | {p.value:.2f}")
    return "\n".join(lines)


def _sensor_block(bundle: SensorHistoryBundle) -> str:
    """Render a single sensor's data as a readable text block."""
    s = bundle.sensor
    lines: list[str] = [
        f"### {s.name} ({s.entity_id})",
        f"  Unit: {s.unit or '—'}  |  Role: {s.role or '—'}  |  Binary: {s.is_binary}",
        f"  Current state: {bundle.current_state}"
        + (f"  ({bundle.current_value:.2f} {s.unit})" if bundle.current_value is not None else ""),
    ]

    if bundle.stats:
        lines.append(f"  Stats (24h): {_format_stats(bundle.stats)}")

    if bundle.anomalies:
        lines.append("  ⚠ ANOMALIES:")
        for a in bundle.anomalies:
            lines.append(f"    - {a}")

    if bundle.resampled:
        lines.append("  History (30-min buckets):")
        lines.append(_format_timeseries(bundle.resampled))

    return "\n".join(lines)


def _group_block(group_bundle: GroupHistoryBundle) -> str:
    lines: list[str] = [
        f"## Group: {group_bundle.group.label.upper()}",
        "",
    ]
    for bundle in group_bundle.bundles:
        lines.append(_sensor_block(bundle))
        lines.append("")
    return "\n".join(lines)


def build_pricing_context_block(pricing: PricingContext) -> str:
    now_utc = datetime.now(tz=timezone.utc)
    lines: list[str] = [
        "## PRICING CONTEXT",
        f"  Tariff type: {pricing.tariff_type}",
        f"  Current tariff period: {pricing.current_tariff_period or 'unknown'}",
    ]
    if pricing.day_rate_eur_kwh is not None:
        lines.append(f"  Fixed day rate: €{pricing.day_rate_eur_kwh:.3f}/kWh")
    if pricing.night_rate_eur_kwh is not None:
        lines.append(f"  Fixed night rate: €{pricing.night_rate_eur_kwh:.3f}/kWh")
    if pricing.current_rate_eur_kwh is not None:
        lines.append(f"  Effective current rate: €{pricing.current_rate_eur_kwh:.3f}/kWh")
    if pricing.nord_pool_current is not None:
        lines.append(
            f"  Nord Pool spot price (NL): €{pricing.nord_pool_current:.4f}/kWh "
            f"{'⚡ NEARLY FREE / NEGATIVE — major opportunity!' if pricing.nord_pool_current <= 0.01 else ''}"
        )
    if pricing.gas_rate_eur_m3 is not None:
        lines.append(f"  Gas rate: €{pricing.gas_rate_eur_m3:.3f}/m³")
    if pricing.co2_intensity_g_kwh is not None:
        lines.append(f"  Grid CO2 intensity: {pricing.co2_intensity_g_kwh:.0f} gCO2eq/kWh")
    lines.append(f"  Analysis timestamp: {now_utc.strftime('%Y-%m-%d %H:%M UTC')}")
    return "\n".join(lines)


def build_user_message(
    group_bundles: list[GroupHistoryBundle],
    pricing: PricingContext,
) -> str:
    """Assemble the full user message sent to Claude."""
    sections: list[str] = [
        "# Home Energy Data — Last 24 Hours",
        "",
        build_pricing_context_block(pricing),
        "",
        "---",
        "",
    ]

    for gb in group_bundles:
        sections.append(_group_block(gb))
        sections.append("---")
        sections.append("")

    sections.append(
        "Please analyse the data above and respond with ONLY the JSON object as specified."
    )
    return "\n".join(sections)
