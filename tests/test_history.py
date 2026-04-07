"""Tests for processing/history.py — resampling, stats, anomaly detection."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from custom_components.ha_energy_agent.models import (
    DiscoveredSensor,
    HistoryPoint,
    SensorStats,
)
from custom_components.ha_energy_agent.processing.history import (
    _compute_stats,
    _detect_anomalies,
    _parse_numeric,
    _resample,
)


# ---------------------------------------------------------------------------
# _parse_numeric
# ---------------------------------------------------------------------------

class TestParseNumeric:
    def test_valid_float(self):
        assert _parse_numeric("42.5") == 42.5

    def test_integer_string(self):
        assert _parse_numeric("100") == 100.0

    def test_unavailable(self):
        assert _parse_numeric("unavailable") is None

    def test_unknown(self):
        assert _parse_numeric("unknown") is None

    def test_empty(self):
        assert _parse_numeric("") is None

    def test_non_numeric(self):
        assert _parse_numeric("on") is None

    def test_negative(self):
        assert _parse_numeric("-2731") == -2731.0


# ---------------------------------------------------------------------------
# _resample
# ---------------------------------------------------------------------------

class TestResample:
    def _make_points(self, start, n, step_minutes=30, base=100.0, step=10.0):
        return [
            HistoryPoint(
                ts=start + timedelta(minutes=step_minutes * i),
                value=base + i * step,
            )
            for i in range(n)
        ]

    def test_downsample(self, start):
        points = self._make_points(start, 96)
        result = _resample(points, 48)
        assert len(result) == 48

    def test_no_change_when_already_short(self, start):
        points = self._make_points(start, 24)
        result = _resample(points, 48)
        assert len(result) == 24

    def test_exact_target(self, start):
        points = self._make_points(start, 48)
        result = _resample(points, 48)
        assert len(result) == 48

    def test_empty_input(self):
        assert _resample([], 48) == []

    def test_returns_history_points(self, start):
        points = self._make_points(start, 10)
        result = _resample(points, 5)
        assert all(isinstance(p, HistoryPoint) for p in result)

    def test_timestamps_in_order(self, start):
        points = self._make_points(start, 96)
        result = _resample(points, 48)
        for i in range(1, len(result)):
            assert result[i].ts >= result[i - 1].ts


# ---------------------------------------------------------------------------
# _compute_stats
# ---------------------------------------------------------------------------

class TestComputeStats:
    def test_basic(self):
        values = [10.0, 20.0, 30.0, 40.0]
        stats = _compute_stats(values)
        assert stats is not None
        assert stats.min == 10.0
        assert stats.max == 40.0
        assert stats.mean == 25.0
        assert stats.total == 100.0
        assert stats.data_points == 4

    def test_empty_returns_none(self):
        assert _compute_stats([]) is None

    def test_single_value(self):
        stats = _compute_stats([55.0])
        assert stats.min == stats.max == stats.mean == stats.total == 55.0


# ---------------------------------------------------------------------------
# _detect_anomalies
# ---------------------------------------------------------------------------

class TestDetectAnomalies:
    def _make_points(self, start, values):
        return [
            HistoryPoint(ts=start + timedelta(minutes=30 * i), value=v)
            for i, v in enumerate(values)
        ]

    def test_flat_line_detected(self, solar_sensor, start):
        values = [500.0] * 20
        stats = _compute_stats(values)
        anomalies = _detect_anomalies(solar_sensor, values, stats)
        assert any("stuck" in a.lower() or "constant" in a.lower() for a in anomalies)

    def test_soc_jump_detected(self, battery_soc_sensor, start):
        values = [30.0] + [90.0] * 19  # jump > 50%
        stats = _compute_stats(values)
        anomalies = _detect_anomalies(battery_soc_sensor, values, stats)
        assert any("soc" in a.lower() or "jump" in a.lower() for a in anomalies)

    def test_solar_extended_zero_detected(self, solar_sensor, start):
        values = [0.0] * 40 + [200.0] * 10  # 80% zeros but max > 0
        stats = _compute_stats(values)
        anomalies = _detect_anomalies(solar_sensor, values, stats)
        assert any("zero" in a.lower() or "inverter" in a.lower() for a in anomalies)

    def test_no_anomaly_normal_operation(self, solar_sensor, start):
        values = [float(1000 + i * 10) for i in range(20)]
        stats = _compute_stats(values)
        anomalies = _detect_anomalies(solar_sensor, values, stats)
        assert anomalies == []

    def test_implausible_power_spike(self, grid_sensor, start):
        values = [500.0] * 19 + [200_000.0]  # > 100 kW
        stats = _compute_stats(values)
        anomalies = _detect_anomalies(grid_sensor, values, stats)
        assert any("100" in a or "outlier" in a.lower() or "exceeds" in a.lower() for a in anomalies)
