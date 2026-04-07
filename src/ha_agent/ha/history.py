"""History fetching, resampling, stats computation, and anomaly detection."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog

from ha_agent.config import Settings
from ha_agent.ha.client import HAClient
from ha_agent.models import (
    GroupHistoryBundle,
    HistoryPoint,
    SensorDefinition,
    SensorGroup,
    SensorHistoryBundle,
    SensorStats,
)

log = structlog.get_logger(__name__)

# Sensors whose anomaly detection checks for excessive relay cycling
_RELAY_SWITCH_ENTITIES = {"sensor.zendure_2400_ac_relais_schakelingen_totaal_vandaag"}
_RELAY_HIGH_THRESHOLD = 40  # switches/day considered excessive

# Solar entity prefixes — used to detect zero-solar anomalies
_SOLAR_POWER_ENTITIES = {
    "sensor.opendtu_07869c_ac_power",
    "sensor.hms_1600_4t_1_power",
    "sensor.hms_1600_4t_2_power",
    "sensor.hms_800_2t_1_power",
}

# Battery SoC entities — rapid changes flagged
_BATTERY_SOC_ENTITIES = {
    "sensor.zendure_2400_ac_laadpercentage",
    "sensor.sf2400ac_788_electric_level",
    "sensor.sf2400ac_967_electric_level",
}
_SOC_RAPID_CHANGE_THRESHOLD = 30.0  # % per hour


def _parse_float(value: str) -> Optional[float]:
    """Convert HA state string to float, returning None for non-numeric states."""
    if value in ("unavailable", "unknown", "none", "", "None"):
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _resample_to_n_points(
    raw: list[dict], n: int, start: datetime, end: datetime
) -> list[HistoryPoint]:
    """
    Bucket the raw history list into n equal-width time buckets.

    Each bucket contains the mean of all numeric readings that fall within it.
    Buckets with no data inherit the last known value (forward-fill).
    Returns an empty list if raw is empty.
    """
    if not raw:
        return []

    total_seconds = (end - start).total_seconds()
    if total_seconds <= 0 or n <= 0:
        return []

    bucket_seconds = total_seconds / n

    # Parse raw points into (ts, value) pairs
    parsed: list[tuple[datetime, float]] = []
    for point in raw:
        raw_ts = point.get("last_changed") or point.get("last_updated")
        if not raw_ts:
            continue
        # HA may return timestamps with or without 'Z' suffix
        if isinstance(raw_ts, str):
            raw_ts = raw_ts.replace("Z", "+00:00")
            try:
                ts = datetime.fromisoformat(raw_ts)
            except ValueError:
                continue
        elif isinstance(raw_ts, datetime):
            ts = raw_ts
        else:
            continue

        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)

        val = _parse_float(point.get("state", ""))
        if val is None:
            continue
        parsed.append((ts, val))

    if not parsed:
        return []

    # Sort chronologically
    parsed.sort(key=lambda x: x[0])

    # Assign each reading to a bucket index
    buckets: list[list[float]] = [[] for _ in range(n)]
    for ts, val in parsed:
        offset = (ts - start).total_seconds()
        idx = int(offset / bucket_seconds)
        idx = max(0, min(idx, n - 1))
        buckets[idx].append(val)

    # Build result with forward-fill for empty buckets
    result: list[HistoryPoint] = []
    last_val: Optional[float] = None
    for i, bucket in enumerate(buckets):
        bucket_ts = start + timedelta(seconds=i * bucket_seconds + bucket_seconds / 2)
        if bucket:
            avg = sum(bucket) / len(bucket)
            last_val = avg
        elif last_val is not None:
            avg = last_val
        else:
            continue  # no data yet, skip leading empty buckets
        result.append(HistoryPoint(ts=bucket_ts, value=avg))

    return result


def compute_stats(points: list[HistoryPoint]) -> Optional[SensorStats]:
    """Compute min/max/mean/total/data_points from resampled history."""
    if not points:
        return None
    values = [p.value for p in points]
    return SensorStats(
        min=min(values),
        max=max(values),
        mean=sum(values) / len(values),
        total=sum(values),
        data_points=len(values),
    )


def detect_anomalies(
    sensor: SensorDefinition,
    points: list[HistoryPoint],
    stats: Optional[SensorStats],
    current_state: str,
) -> list[str]:
    """Return a list of human-readable anomaly strings for this sensor."""
    anomalies: list[str] = []
    if not points or stats is None:
        return anomalies

    entity = sensor.entity_id

    # --- Relay switching (battery oscillation) ---
    if entity in _RELAY_SWITCH_ENTITIES:
        current_val = _parse_float(current_state)
        if current_val is not None and current_val >= _RELAY_HIGH_THRESHOLD:
            anomalies.append(
                f"Excessive relay switches today: {current_val:.0f} "
                f"(threshold {_RELAY_HIGH_THRESHOLD}). "
                "May indicate battery oscillation or misconfigured charge/discharge schedule."
            )

    # --- Zero solar power during expected generation hours ---
    if entity in _SOLAR_POWER_ENTITIES and stats.max < 5.0:
        anomalies.append(
            f"Solar power near-zero all day (max {stats.max:.1f} W). "
            "Check inverter connectivity or shading."
        )

    # --- Rapid battery SoC changes ---
    if entity in _BATTERY_SOC_ENTITIES and len(points) >= 2:
        for i in range(1, len(points)):
            dt_hours = (points[i].ts - points[i - 1].ts).total_seconds() / 3600
            if dt_hours <= 0:
                continue
            d_soc = abs(points[i].value - points[i - 1].value)
            rate = d_soc / dt_hours
            if rate > _SOC_RAPID_CHANGE_THRESHOLD:
                anomalies.append(
                    f"Rapid SoC change detected: {d_soc:.1f}% in "
                    f"{dt_hours * 60:.0f} min ({rate:.1f}%/h). "
                    "Could indicate measurement glitch or very high charge/discharge rate."
                )
                break  # report once per sensor

    # --- General: sensor stuck at zero for the whole period ---
    if stats.max == 0.0 and stats.min == 0.0 and stats.data_points >= 4:
        # Skip sensors that are legitimately often zero (dryer, dishwasher)
        _always_zero_ok = {"sensor.droger_power", "sensor.vaatwasser_current_consumption"}
        if entity not in _always_zero_ok and sensor.role in ("power", "energy", ""):
            anomalies.append(
                f"Sensor reported 0 for all {stats.data_points} history points. "
                "Verify device is operational."
            )

    return anomalies


async def build_sensor_history_bundle(
    client: HAClient,
    sensor: SensorDefinition,
    settings: Settings,
    start: datetime,
    end: datetime,
) -> SensorHistoryBundle:
    """
    Fetch history + current state for one sensor, resample, compute stats, detect anomalies.
    """
    raw_history, state_data = await asyncio.gather(
        client.get_history(sensor.entity_id, start, end),
        client.get_state(sensor.entity_id),
        return_exceptions=True,
    )

    # Handle errors gracefully
    if isinstance(raw_history, Exception):
        log.warning("history_error", entity_id=sensor.entity_id, error=str(raw_history))
        raw_history = []
    if isinstance(state_data, Exception):
        log.warning("state_error", entity_id=sensor.entity_id, error=str(state_data))
        state_data = {"entity_id": sensor.entity_id, "state": "unavailable", "attributes": {}}

    current_state: str = state_data.get("state", "unavailable")
    current_value = _parse_float(current_state)

    resampled = _resample_to_n_points(
        raw_history,
        settings.max_history_points,
        start,
        end,
    )
    stats = compute_stats(resampled)
    anomalies = detect_anomalies(sensor, resampled, stats, current_state)

    return SensorHistoryBundle(
        sensor=sensor,
        current_state=current_state,
        current_value=current_value,
        resampled=resampled,
        stats=stats,
        anomalies=anomalies,
    )


async def build_all_bundles(
    client: HAClient,
    sensor_groups: list[SensorGroup],
    settings: Settings,
) -> list[GroupHistoryBundle]:
    """
    Fetch history for all sensors in all groups concurrently.
    Returns a list of GroupHistoryBundle, one per group.
    """
    now = datetime.now(tz=timezone.utc)
    start = now - timedelta(hours=settings.history_hours)

    # Flatten to (group, sensor) pairs and launch all tasks at once
    pairs: list[tuple[SensorGroup, SensorDefinition]] = [
        (group, sensor) for group in sensor_groups for sensor in group.sensors
    ]

    tasks = [
        build_sensor_history_bundle(client, sensor, settings, start, now)
        for _, sensor in pairs
    ]

    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Regroup results
    group_bundles: dict[str, list[SensorHistoryBundle]] = {}
    for (group, sensor), result in zip(pairs, results):
        key = group.label
        if key not in group_bundles:
            group_bundles[key] = []
        if isinstance(result, Exception):
            log.warning(
                "bundle_error", entity_id=sensor.entity_id, group=key, error=str(result)
            )
            group_bundles[key].append(
                SensorHistoryBundle(
                    sensor=sensor,
                    current_state="unavailable",
                    current_value=None,
                    resampled=[],
                    stats=None,
                    anomalies=[f"Failed to fetch: {result}"],
                )
            )
        else:
            group_bundles[key].append(result)

    return [
        GroupHistoryBundle(group=group, bundles=group_bundles.get(group.label, []))
        for group in sensor_groups
    ]
