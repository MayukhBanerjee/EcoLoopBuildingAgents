"""
tests/test_agent_grid.py — Carbon intensity + peak demand logic.
"""

from __future__ import annotations

import os

import pytest
from agent.grid import (
    CARBON_INTENSITY_G_PER_KWH,
    HIGH_INTENSITY_THRESHOLD,
    carbon_intensity,
    intensity_label,
    peak_status,
)


class TestCarbonIntensity:
    def test_returns_float(self) -> None:
        assert isinstance(carbon_intensity(0), float)

    def test_wraps_modulo_24(self) -> None:
        assert carbon_intensity(0) == carbon_intensity(24)
        assert carbon_intensity(23) == carbon_intensity(47)

    def test_all_24_hours_defined(self) -> None:
        assert len(CARBON_INTENSITY_G_PER_KWH) == 24

    def test_midday_lower_than_midnight(self) -> None:
        """Solar ramp: intensity at noon should be lower than at midnight."""
        assert carbon_intensity(12) < carbon_intensity(0)

    def test_evening_peak_higher_than_noon(self) -> None:
        """Evening demand peak: hour 20 should be higher than hour 12."""
        assert carbon_intensity(20) > carbon_intensity(12)

    def test_all_values_positive(self) -> None:
        assert all(carbon_intensity(h) > 0 for h in range(24))


class TestIntensityLabel:
    def test_high_label_when_above_threshold(self) -> None:
        # Hour 0: 680 > 650 threshold
        assert intensity_label(0) == "HIGH"

    def test_low_label_when_below_threshold(self) -> None:
        # Hour 12: 500 < 650 threshold
        assert intensity_label(12) == "LOW"


class TestPeakStatus:
    def setup_method(self) -> None:
        os.environ["PEAK_DEMAND_THRESHOLD_KW"] = "50.0"

    def teardown_method(self) -> None:
        os.environ.pop("PEAK_DEMAND_THRESHOLD_KW", None)

    def test_ok_below_80pct(self) -> None:
        assert peak_status(30.0) == "OK"

    def test_approaching_at_80pct(self) -> None:
        assert peak_status(40.0) == "APPROACHING"

    def test_exceeded_at_threshold(self) -> None:
        assert peak_status(50.0) == "EXCEEDED"

    def test_exceeded_above_threshold(self) -> None:
        assert peak_status(60.0) == "EXCEEDED"

    def test_zero_demand_ok(self) -> None:
        assert peak_status(0.0) == "OK"

    def test_env_threshold_respected(self) -> None:
        os.environ["PEAK_DEMAND_THRESHOLD_KW"] = "100.0"
        # 50 kW against 100 kW threshold = 50% → OK
        assert peak_status(50.0) == "OK"
