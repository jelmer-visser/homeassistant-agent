"""Tests for ha/history.py — resampling, stats, anomaly detection."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from ha_agent.ha.history import (
    _parse_float,
    _resample_to_n_points,
    compute_stats,
    detect_anomalies,
)
from ha_agent.models import HistoryPoint, SensorDefinition


# ---------------------------------------------------------------------------
# _parse_float
# ---------------------------------------------------------------------------

class TestParseFloat:
    def test_valid(self):
        assert _parse_float("42.5") == 42.5

    def test_integer_string(self):
        assert _parse_float("100") == 100.0

    def test_unavailable(self):
        assert _parse_float("unavailable") is None

    def test_unknown(self):
        assert _parse_float("unknown") is None

    def test_empty(self):
        assert _parse_float("") is None

    def test_non_numeric(self):
        assert _parse_float("on") is None

    def test_negative(self):
        assert _parse_float("-2731") == -2731.0


# ---------------------------------------------------------------------------
# _resample_to_n_points
# ---------------------------------------------------------------------------

class TestResample:
    def _make_points(self, start, n, step_minutes=30, base=100.0, step=10.0):
        return [
            {
                "state": str(base + i * step),
                "last_changed": (start + timedelta(minutes=step_minutes * i)).isoformat(),
            }
            for i in range(n)
        ]

    def test_basic_resample(self, start, now):
        raw = self._make_points(start, 96, step_minutes=15)  # 15-min data → 48 buckets
        result = _resample_to_n_points(raw, 48, start, now)
        assert len(result) == 48

    def test_exact_bucket_count(self, start, now):
        raw = self._make_points(start, 48, step_minutes=30)
        result = _resample_to_n_points(raw, 48, start, now)
        assert len(result) == 48

    def test_empty_input(self, start, now):
        assert _resample_to_n_points([], 48, start, now) == []

    def test_single_point(self, start, now):
        raw = [{"state": "500", "last_changed": start.isoformat()}]
        result = _resample_to_n_points(raw, 48, start, now)
        assert len(result) >= 1
        assert result[0].value == 500.0

    def test_filters_unavailable(self, start, now):
        raw = [
            {"state": "100", "last_changed": start.isoformat()},
            {"state": "unavailable", "last_changed": (start + timedelta(hours=1)).isoformat()},
            {"state": "200", "last_changed": (start + timedelta(hours=2)).isoformat()},
        ]
        result = _resample_to_n_points(raw, 48, start, now)
        values = [p.value for p in result]
        assert all(v in (100.0, 200.0) for v in values)

    def test_forward_fill(self, start, now):
        """Leading value should be forward-filled into empty buckets."""
        raw = [{"state": "999", "last_changed": start.isoformat()}]
        result = _resample_to_n_points(raw, 4, start, now)
        # All buckets from the first one onwards should equal 999
        assert all(p.value == 999.0 for p in result)

    def test_returns_history_points(self, start, now):
        raw = [{"state": "42", "last_changed": start.isoformat()}]
        result = _resample_to_n_points(raw, 48, start, now)
        assert isinstance(result[0], HistoryPoint)

    def test_timestamps_in_order(self, start, now):
        raw = self._make_points(start, 48)
        result = _resample_to_n_points(raw, 48, start, now)
        for i in range(1, len(result)):
            assert result[i].ts > result[i - 1].ts


# ---------------------------------------------------------------------------
# compute_stats
# ---------------------------------------------------------------------------

class TestComputeStats:
    def test_basic(self, start):
        points = [
            HistoryPoint(ts=start + timedelta(minutes=30 * i), value=float(v))
            for i, v in enumerate([10, 20, 30, 40])
        ]
        stats = compute_stats(points)
        assert stats is not None
        assert stats.min == 10.0
        assert stats.max == 40.0
        assert stats.mean == 25.0
        assert stats.total == 100.0
        assert stats.data_points == 4

    def test_empty(self):
        assert compute_stats([]) is None

    def test_single(self, start):
        points = [HistoryPoint(ts=start, value=55.0)]
        stats = compute_stats(points)
        assert stats.min == stats.max == stats.mean == stats.total == 55.0


# ---------------------------------------------------------------------------
# detect_anomalies
# ---------------------------------------------------------------------------

class TestDetectAnomalies:
    def _make_history(self, start, values):
        return [
            HistoryPoint(ts=start + timedelta(minutes=30 * i), value=v)
            for i, v in enumerate(values)
        ]

    def test_relay_switches_high(self, relay_sensor, start):
        points = self._make_history(start, [66.0] * 10)
        stats = compute_stats(points)
        anomalies = detect_anomalies(relay_sensor, points, stats, "66")
        assert any("relay switch" in a.lower() for a in anomalies)

    def test_relay_switches_normal(self, relay_sensor, start):
        points = self._make_history(start, [5.0] * 10)
        stats = compute_stats(points)
        anomalies = detect_anomalies(relay_sensor, points, stats, "5")
        assert not any("relay" in a.lower() for a in anomalies)

    def test_solar_zero(self, solar_sensor, start):
        points = self._make_history(start, [0.0] * 20)
        stats = compute_stats(points)
        anomalies = detect_anomalies(solar_sensor, points, stats, "0")
        assert any("solar" in a.lower() or "zero" in a.lower() for a in anomalies)

    def test_rapid_soc_change(self, battery_soc_sensor, start):
        # 80% drop in 30 minutes = 160%/h >> threshold
        points = self._make_history(start, [100.0, 20.0] + [20.0] * 10)
        stats = compute_stats(points)
        anomalies = detect_anomalies(battery_soc_sensor, points, stats, "20")
        assert any("rapid" in a.lower() or "soc" in a.lower() for a in anomalies)

    def test_no_anomaly_normal_operation(self, solar_sensor, start):
        points = self._make_history(start, [1000.0 + i * 10 for i in range(20)])
        stats = compute_stats(points)
        anomalies = detect_anomalies(solar_sensor, points, stats, "1200")
        assert anomalies == []
