"""Fetch and process historical sensor data from HA Recorder.

Uses the homeassistant.components.recorder.history API to pull
time-series data for each selected entity, resample it to a fixed
number of points, compute stats, and flag simple anomalies.
"""
from __future__ import annotations

import logging
import statistics
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

from custom_components.ha_energy_agent.models import (
    DiscoveredSensor,
    GroupHistoryBundle,
    HistoryPoint,
    LongTermContext,
    SensorGroup,
    SensorHistoryBundle,
    SensorLongTermBundle,
    SensorStats,
    StatAggregate,
)

_LOGGER = logging.getLogger(__name__)

_DEFAULT_MAX_POINTS = 48
_UNAVAILABLE = {"unavailable", "unknown", "none", ""}
# If state-history returns fewer points than this, fall back to 5-minute statistics.
_MIN_POINTS_THRESHOLD = 5


def _parse_numeric(value: str) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _resample(points: list[HistoryPoint], target_points: int) -> list[HistoryPoint]:
    """Downsample or return as-is if already short enough."""
    if len(points) <= target_points:
        return points
    step = len(points) / target_points
    return [points[int(i * step)] for i in range(target_points)]


def _compute_stats(values: list[float]) -> Optional[SensorStats]:
    if not values:
        return None
    return SensorStats(
        min=min(values),
        max=max(values),
        mean=statistics.mean(values),
        total=sum(values),
        data_points=len(values),
    )


def _detect_anomalies(sensor: DiscoveredSensor, values: list[float], stats: SensorStats) -> list[str]:
    """Return list of human-readable anomaly strings."""
    anomalies: list[str] = []
    if not values or stats is None:
        return anomalies

    # Flat-line: all values identical (stuck sensor)
    if len(set(values)) == 1:
        anomalies.append(f"{sensor.name}: constant value {values[0]} {sensor.unit} — sensor may be stuck")
        return anomalies

    # SOC spike (battery went from low to full instantly)
    if sensor.role == "soc":
        for i in range(1, len(values)):
            delta = abs(values[i] - values[i - 1])
            if delta > 50:
                anomalies.append(
                    f"{sensor.name}: SOC jumped {delta:.0f}% — possible data gap or sensor reset"
                )
                break

    # Implausible power spike (> 100 kW for a home sensor)
    if sensor.role == "power" and sensor.unit in ("W", "kW"):
        multiplier = 1000.0 if sensor.unit == "W" else 1.0
        limit_kw = 100.0
        if stats.max * (1 / multiplier) > limit_kw:
            anomalies.append(
                f"{sensor.name}: peak {stats.max:.0f} {sensor.unit} exceeds {limit_kw:.0f} kW — possible outlier"
            )

    # Extended zero production during daylight (solar panels)
    if sensor.category == "solar" and sensor.role == "power":
        zero_streak = 0
        max_streak = 0
        for v in values:
            if v == 0.0:
                zero_streak += 1
                max_streak = max(max_streak, zero_streak)
            else:
                zero_streak = 0
        if max_streak > len(values) * 0.7 and stats.max > 0:
            anomalies.append(
                f"{sensor.name}: zero output for {max_streak} of {len(values)} intervals — check inverter"
            )

    return anomalies


async def _fetch_stats_as_history_points(
    hass: "HomeAssistant",
    recorder,
    entity_id: str,
    start_time: datetime,
    end_time: datetime,
) -> list[HistoryPoint]:
    """Fetch 5-minute statistics as HistoryPoint objects.

    Used as a fallback when get_significant_states returns very few points —
    which happens for "5-minute aggregated" sensors (e.g. Zendure battery) that
    store data in the statistics table rather than the state history table.
    """
    from homeassistant.components.recorder.statistics import statistics_during_period

    def _fetch():
        return statistics_during_period(
            hass, start_time, end_time,
            {entity_id}, "5minute", None,
            {"mean"},
        )

    try:
        data = await recorder.async_add_executor_job(_fetch)
    except Exception as exc:  # noqa: BLE001
        _LOGGER.debug("Stats fallback failed for %s: %s", entity_id, exc)
        return []

    points: list[HistoryPoint] = []
    for row in data.get(entity_id, []):
        mean = row.get("mean")
        if mean is None:
            continue
        ts = datetime.fromtimestamp(row["start"], tz=timezone.utc)
        points.append(HistoryPoint(ts=ts, value=mean))

    return points


async def fetch_history_bundles(
    hass: "HomeAssistant",
    groups: list[SensorGroup],
    history_hours: int,
    max_points: int = _DEFAULT_MAX_POINTS,
) -> list[GroupHistoryBundle]:
    """
    Fetch recorder history for all sensors in all groups.

    Returns one GroupHistoryBundle per group, each containing one
    SensorHistoryBundle per sensor.
    """
    from homeassistant.components.recorder import get_instance
    from homeassistant.components.recorder.history import get_significant_states

    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(hours=history_hours)

    # Collect all entity IDs in one call
    all_entity_ids: list[str] = [
        s.entity_id for group in groups for s in group.sensors
    ]
    if not all_entity_ids:
        return []

    _LOGGER.debug(
        "Fetching %d hours of history for %d entities",
        history_hours,
        len(all_entity_ids),
    )

    # get_significant_states must run in the recorder thread
    recorder = get_instance(hass)

    def _fetch() -> dict[str, list]:
        return get_significant_states(
            hass,
            start_time,
            end_time,
            entity_ids=all_entity_ids,
            significant_changes_only=False,  # False = all recorded changes, not just "significant" ones
            minimal_response=True,
        )

    try:
        raw_history: dict[str, list] = await recorder.async_add_executor_job(_fetch)
    except Exception as exc:  # noqa: BLE001
        _LOGGER.error("Failed to fetch recorder history: %s", exc)
        raw_history = {}

    result: list[GroupHistoryBundle] = []

    for group in groups:
        bundles: list[SensorHistoryBundle] = []

        for sensor in group.sensors:
            current_state_obj = hass.states.get(sensor.entity_id)
            current_state_str = (current_state_obj.state if current_state_obj else "unavailable")
            current_value: Optional[float] = None
            if current_state_str not in _UNAVAILABLE:
                current_value = _parse_numeric(current_state_str)

            states_list = raw_history.get(sensor.entity_id, [])
            points: list[HistoryPoint] = []
            for state_obj in states_list:
                # MinimalState has .state and .last_changed
                raw_val = getattr(state_obj, "state", None)
                ts = getattr(state_obj, "last_changed", None)
                if raw_val is None or raw_val in _UNAVAILABLE or ts is None:
                    continue
                val = _parse_numeric(raw_val)
                if val is None:
                    continue
                # Ensure tz-aware
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                points.append(HistoryPoint(ts=ts, value=val))

            # Sparse-sensor fallback: statistics-based sensors (e.g. Zendure battery)
            # store data only in the statistics table, not in state history.
            # get_significant_states returns ≤ 1 point for them; fall back to
            # 5-minute statistics rows which give a proper time series.
            if len(points) < _MIN_POINTS_THRESHOLD:
                stats_points = await _fetch_stats_as_history_points(
                    hass, recorder, sensor.entity_id, start_time, end_time
                )
                if len(stats_points) > len(points):
                    _LOGGER.debug(
                        "%s: state history had %d points; using %d points from 5-min statistics",
                        sensor.entity_id, len(points), len(stats_points),
                    )
                    points = stats_points

            resampled = _resample(points, max_points)
            numeric_values = [p.value for p in resampled]

            # For efficiency sensors (COP etc.):
            #  • value == 0  → device idle, not a real reading
            #  • value < 0   → sensor artifact (e.g. defrost-cycle glitch); physically impossible
            # Compute stats on active valid samples only; annotate both cases.
            if sensor.role == "efficiency":
                active_values  = [v for v in numeric_values if v > 0]
                artifact_count = sum(1 for v in numeric_values if v < 0)
                idle_pct = (
                    round(100 * (len(numeric_values) - len(active_values)) / len(numeric_values))
                    if numeric_values else 0
                )
                stats = _compute_stats(active_values)
                anomalies = _detect_anomalies(sensor, active_values, stats) if stats else []
                if numeric_values:
                    note = (
                        f"{sensor.name}: device was idle (value=0) for "
                        f"{idle_pct}% of the window; stats reflect active periods only"
                    )
                    anomalies.insert(0, note)
                if artifact_count:
                    anomalies.insert(0, (
                        f"{sensor.name}: {artifact_count} negative COP reading(s) detected "
                        f"— sensor artifact (likely defrost cycle), excluded from stats"
                    ))
            else:
                stats = _compute_stats(numeric_values)
                anomalies = _detect_anomalies(sensor, numeric_values, stats) if stats else []

            bundles.append(
                SensorHistoryBundle(
                    sensor=sensor,
                    current_state=current_state_str,
                    current_value=current_value,
                    resampled=resampled,
                    stats=stats,
                    anomalies=anomalies,
                )
            )

        result.append(GroupHistoryBundle(group=group, bundles=bundles))

    return result


async def fetch_long_term_context(
    hass: "HomeAssistant",
    groups: list[SensorGroup],
) -> LongTermContext:
    """Fetch daily (last 30 days) and monthly (last 12 months) aggregates from HA statistics.

    Uses the pre-computed statistics tables in the recorder DB — much faster
    than loading raw state changes for long windows. Returns an empty
    LongTermContext if statistics are unavailable or the recorder is off.
    """
    from homeassistant.components.recorder import get_instance
    from homeassistant.components.recorder.statistics import statistics_during_period

    end_time = datetime.now(timezone.utc)
    daily_start = end_time - timedelta(days=30)
    monthly_start = end_time - timedelta(days=365)

    all_sensors: list[DiscoveredSensor] = [s for g in groups for s in g.sensors]
    if not all_sensors:
        return LongTermContext()

    recorder = get_instance(hass)
    entity_ids = [s.entity_id for s in all_sensors]

    _LOGGER.debug("Fetching long-term statistics for %d entities", len(entity_ids))

    def _fetch_stats() -> tuple[dict, dict]:
        daily = statistics_during_period(
            hass, daily_start, end_time,
            set(entity_ids), "day", None,
            {"mean", "min", "max", "sum", "change"},
        )
        monthly = statistics_during_period(
            hass, monthly_start, end_time,
            set(entity_ids), "month", None,
            {"mean", "min", "max", "sum", "change"},
        )
        return daily, monthly

    try:
        daily_data, monthly_data = await recorder.async_add_executor_job(_fetch_stats)
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning("Failed to fetch long-term statistics: %s", exc)
        return LongTermContext()

    def _to_agg(row: dict, fmt: str) -> StatAggregate:
        return StatAggregate(
            date=datetime.fromtimestamp(row["start"], tz=timezone.utc).strftime(fmt),
            mean=row.get("mean"),
            min=row.get("min"),
            max=row.get("max"),
            change=row.get("change"),
        )

    bundles: list[SensorLongTermBundle] = []
    for sensor in all_sensors:
        daily = [_to_agg(r, "%Y-%m-%d") for r in daily_data.get(sensor.entity_id, [])]
        monthly = [_to_agg(r, "%Y-%m") for r in monthly_data.get(sensor.entity_id, [])]
        if daily or monthly:
            bundles.append(SensorLongTermBundle(
                entity_id=sensor.entity_id,
                name=sensor.name,
                unit=sensor.unit,
                role=sensor.role,
                daily=daily,
                monthly=monthly,
            ))

    return LongTermContext(bundles=bundles)
