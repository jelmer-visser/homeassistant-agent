"""Dynamic prompt builder for HA Energy Agent.

Assembles a system prompt + structured user message from live sensor data,
adapting to whichever categories the user has configured.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from custom_components.ha_energy_agent.models import (
    GroupHistoryBundle,
    PricingContext,
)


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are an expert home energy management AI embedded in Home Assistant.
Your role is to analyse real-time and historical energy data from the user's home
and provide actionable, prioritised optimisation tips.

Guidelines:
- Be specific and data-driven. Reference actual values (e.g. "your battery reached 95% at 10:30").
- Prioritise tips by financial impact (high/medium/low).
- Provide realistic estimated savings in EUR where possible.
- When you suggest a Home Assistant automation, output valid YAML.
- Acknowledge data gaps honestly; do not fabricate readings.
- Keep the summary concise (2–4 sentences) and conversational.
- Return ONLY valid JSON matching the schema below — no prose outside the JSON.

Response schema (strict):
{
  "summary": "<2-4 sentence overview>",
  "efficiency_score": <integer 0-100>,
  "tips": [
    {
      "id": "<slug>",
      "priority": "high|medium|low",
      "category": "solar|battery|heat_pump|grid|pricing|cross_system",
      "title": "<short title>",
      "description": "<actionable description>",
      "estimated_saving": "<e.g. €2-5/month or empty string>",
      "automation_yaml": "<HA automation YAML or empty string>"
    }
  ],
  "automations": [
    {
      "id": "<slug>",
      "name": "<name>",
      "description": "<what it does>",
      "yaml": "<full HA automation YAML>"
    }
  ],
  "data_quality_notes": ["<note>"],
  "notable_observations": ["<observation>"]
}
"""


# ---------------------------------------------------------------------------
# User message builder
# ---------------------------------------------------------------------------

def _format_ts(ts: datetime) -> str:
    return ts.strftime("%H:%M")


def _bundle_section(bundle: "GroupHistoryBundle") -> str:
    """Render one category group as a markdown-style text block."""
    lines: list[str] = [f"\n### {bundle.group.label.replace('_', ' ').upper()}"]

    for sb in bundle.bundles:
        s = sb.sensor
        header = f"**{s.name}** (`{s.entity_id}`)"
        if s.unit:
            header += f" [{s.unit}]"
        if s.role:
            header += f" — role: {s.role}"
        lines.append(header)

        lines.append(f"  Current: {sb.current_state}")

        if sb.stats:
            st = sb.stats
            lines.append(
                f"  Stats ({len(sb.resampled)} pts): "
                f"min={st.min:.2f}, max={st.max:.2f}, "
                f"mean={st.mean:.2f}, total={st.total:.2f}"
            )

        if sb.resampled:
            # Show up to 12 sample points inline
            sample = sb.resampled[:: max(1, len(sb.resampled) // 12)]
            pairs = ", ".join(f"{_format_ts(p.ts)}={p.value:.1f}" for p in sample)
            lines.append(f"  Samples: {pairs}")

        for anomaly in sb.anomalies:
            lines.append(f"  ⚠ ANOMALY: {anomaly}")

    return "\n".join(lines)


def _pricing_section(ctx: Optional[PricingContext]) -> str:
    if ctx is None:
        return "\n### PRICING\nNo pricing data configured."

    lines = ["\n### PRICING"]
    lines.append(f"  Tariff type: {ctx.tariff_type}")
    if ctx.current_rate_eur_kwh is not None:
        lines.append(f"  Current rate: €{ctx.current_rate_eur_kwh:.4f}/kWh ({ctx.current_tariff_period})")
    if ctx.day_rate_eur_kwh is not None:
        lines.append(f"  Day rate: €{ctx.day_rate_eur_kwh:.4f}/kWh")
    if ctx.night_rate_eur_kwh is not None:
        lines.append(f"  Night rate: €{ctx.night_rate_eur_kwh:.4f}/kWh")
    if ctx.nord_pool_current is not None:
        lines.append(f"  Nord Pool spot: €{ctx.nord_pool_current:.4f}/kWh")
    if ctx.co2_intensity_g_kwh is not None:
        lines.append(f"  CO₂ intensity: {ctx.co2_intensity_g_kwh:.0f} g/kWh")
    return "\n".join(lines)


def build_user_message(
    bundles: list["GroupHistoryBundle"],
    pricing: Optional[PricingContext],
    history_hours: int,
) -> str:
    """Assemble the full user message sent to Claude."""
    now = datetime.now(timezone.utc)
    lines: list[str] = [
        f"## Home Energy Analysis Request",
        f"Timestamp: {now.strftime('%Y-%m-%d %H:%M UTC')}",
        f"Analysis window: last {history_hours} hours",
        "",
        "Below is sensor data collected from the home energy system.",
        "Please analyse and return your response as JSON per the schema.",
        "",
    ]

    for bundle in bundles:
        lines.append(_bundle_section(bundle))

    lines.append(_pricing_section(pricing))

    lines.append(
        "\n\nProvide your full JSON analysis now. "
        "Focus on the most impactful optimisations."
    )

    return "\n".join(lines)
