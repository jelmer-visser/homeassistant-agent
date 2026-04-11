"""Dynamic prompt builder for HA Energy Agent.

Assembles a system prompt + structured user message from live sensor data,
adapting to whichever categories the user has configured.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from custom_components.ha_energy_agent.models import (
    GroupHistoryBundle,
    LongTermContext,
    PricingContext,
    StatAggregate,
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
- COP/efficiency sensors often report 0 when the device is idle and occasionally spike negative (defrost-cycle artefacts). Treat negative COP values as invalid sensor noise — never cite them as real efficiency readings or use them in averages. When the long-term context flags excluded artefact months, trust the exclusion and report the valid months only.
- You receive both fine-grained recent data (last 24–48h) and long-term aggregates (daily last 30 days, monthly last 12 months). Use seasonal and weekly patterns to inform your efficiency score and tips.
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
      "automation_yaml": "<HA automation YAML or empty string>",
      "reasoning": "<1-2 sentences citing the specific sensor values or patterns that triggered this tip>"
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
            if s.role == "power_net":
                header += " (positive = import from grid, negative = export to grid)"
        lines.append(header)

        lines.append(f"  Current: {sb.current_state}")

        if sb.stats:
            st = sb.stats
            if s.role == "energy":
                # Cumulative / daily-reset sensor: max = total produced in the window;
                # sum of sample points is meaningless so we omit it.
                lines.append(
                    f"  Stats ({len(sb.resampled)} pts): "
                    f"peak={st.max:.2f} {s.unit or ''} (= total produced in window), "
                    f"mean={st.mean:.2f}"
                )
            else:
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


def _long_term_section(ctx: LongTermContext) -> str:
    """Render daily/monthly aggregates as a compact text block."""
    if not ctx.bundles:
        return ""

    lines = ["\n### LONG-TERM CONTEXT (daily last 30 days / monthly last 12 months)"]

    for b in ctx.bundles:
        lines.append(f"\n**{b.name}** [{b.unit}] — {b.role}")

        if b.daily:
            recent = b.daily[-7:]
            if b.role == "energy":
                def _energy_val(a: "StatAggregate") -> str:
                    # `change` is correct for total_increasing sensors (e.g. Yield Total).
                    # For daily-reset sensors (e.g. Yield Day), change ≈ 0 because the
                    # recorder sees first≈0 and last≈0 at midnight boundaries — fall back
                    # to max which equals the day's peak/total production.
                    if a.change is not None and a.change > 0:
                        return f"{a.date}={a.change:.1f}kWh"
                    if a.max is not None and a.max > 0:
                        return f"{a.date}={a.max:.1f}kWh (peak)"
                    return f"{a.date}=?"
                pairs = ", ".join(_energy_val(a) for a in recent)
                lines.append(f"  Daily (last 7d): {pairs}")
            elif b.role == "efficiency":
                # Negative daily means are sensor artifacts (e.g. defrost-cycle glitches).
                # Exclude them and flag so the AI does not treat them as real COP drops.
                valid  = [(a.date, a.mean) for a in recent if a.mean is not None and a.mean >= 0]
                skipped = sum(1 for a in recent if a.mean is not None and a.mean < 0)
                pairs = ", ".join(f"{d}={m:.1f}" for d, m in valid) if valid else "no valid data"
                artifact_note = (
                    f" [WARNING: {skipped} day(s) had negative mean — pre-aggregated artifact "
                    f"from defrost-cycle spikes, excluded; do NOT cite these as real COP values]"
                    if skipped else ""
                )
                lines.append(f"  Daily mean active COP (last 7d): {pairs}{artifact_note}")
            elif b.role in ("power", "power_net", "soc", "temperature"):
                pairs = ", ".join(
                    f"{a.date}={a.mean:.1f}" if a.mean is not None else f"{a.date}=?"
                    for a in recent
                )
                note = " (+import/−export)" if b.role == "power_net" else ""
                lines.append(f"  Daily mean (last 7d){note}: {pairs}")

        if b.monthly:
            if b.role == "energy":
                def _energy_val_m(a: "StatAggregate") -> str:
                    if a.change is not None and a.change > 0:
                        return f"{a.date}={a.change:.0f}kWh"
                    if a.max is not None and a.max > 0:
                        return f"{a.date}={a.max:.0f}kWh (peak)"
                    return f"{a.date}=?"
                pairs = ", ".join(_energy_val_m(a) for a in b.monthly)
                lines.append(f"  Monthly: {pairs}")
            elif b.role == "efficiency":
                # Same artifact filtering for monthly aggregates.
                valid_m   = [(a.date, a.mean) for a in b.monthly if a.mean is not None and a.mean >= 0]
                skipped_m = sum(1 for a in b.monthly if a.mean is not None and a.mean < 0)
                pairs = ", ".join(f"{d}={m:.1f}" for d, m in valid_m) if valid_m else "no valid data"
                artifact_note = (
                    f" [WARNING: {skipped_m} month(s) excluded — pre-aggregated mean skewed by "
                    f"negative defrost-cycle spikes; actual active COP was higher]"
                    if skipped_m else ""
                )
                lines.append(f"  Monthly active COP: {pairs}{artifact_note}")
            else:
                pairs = ", ".join(
                    f"{a.date}={a.mean:.1f}" if a.mean is not None else f"{a.date}=?"
                    for a in b.monthly
                )
                lines.append(f"  Monthly: {pairs}")

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
    long_term: Optional[LongTermContext] = None,
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

    if long_term:
        lines.append(_long_term_section(long_term))

    lines.append(_pricing_section(pricing))

    lines.append(
        "\n\nProvide your full JSON analysis now. "
        "Focus on the most impactful optimisations."
    )

    return "\n".join(lines)
