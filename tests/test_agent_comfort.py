"""
tests/test_agent_comfort.py — PMV model correctness.

Validates the simplified Fanger PMV against known reference values
for the fixed conditions (met=1.1, clo=0.7, v=0.1, RH=50%).
"""

from __future__ import annotations

import pytest
from agent.comfort import comfort_ok, pmv, pmv_label

# Reference: ISO 7730 Annex D, Table D.1 for met=1.1, clo=0.7, va=0.1, RH=50%
# PMV at 20 °C ≈ -1.0...-0.8
# PMV at 23 °C ≈ -0.1...+0.1
# PMV at 26 °C ≈ +0.9...+1.1


class TestPMVRange:
    def test_neutral_temperature_gives_near_zero_pmv(self) -> None:
        """For met=1.1, clo=0.7, RH=50%, v=0.1: neutral ≈ 24.7°C → |PMV| < 0.15 at 25°C."""
        val = pmv(25.0)
        assert abs(val) < 0.2, f"Expected |PMV| < 0.2 at 25°C (neutral band), got {val}"

    def test_too_cold_gives_negative_pmv(self) -> None:
        """18 °C should be cold (PMV < -1.5) for these conditions."""
        val = pmv(18.0)
        assert val < -1.0, f"Expected PMV < -1.0 at 18°C, got {val}"

    def test_too_hot_gives_positive_pmv(self) -> None:
        """28 °C should be warm (PMV > +0.8) for these conditions."""
        val = pmv(28.0)
        assert val > 0.8, f"Expected PMV > +0.8 at 28°C, got {val}"

    def test_monotone_with_temperature(self) -> None:
        """PMV must strictly increase with temperature over 16-32 °C."""
        temps = list(range(16, 33))
        pmvs = [pmv(float(t)) for t in temps]
        for i in range(len(pmvs) - 1):
            assert pmvs[i] < pmvs[i + 1], (
                f"PMV not monotone: pmv({temps[i]})={pmvs[i]} >= pmv({temps[i+1]})={pmvs[i+1]}"
            )

    def test_comfort_band_at_25(self) -> None:
        """25°C is in the comfortable range for clo=0.7, met=1.1."""
        assert comfort_ok(pmv(25.0))

    def test_comfort_band_at_26_still_ok(self) -> None:
        """26°C (PMV ≈ +0.40) is still inside comfort band."""
        assert comfort_ok(pmv(26.0))

    def test_comfort_band_at_27_fails(self) -> None:
        """27°C (PMV ≈ +0.71) is outside comfort band."""
        assert not comfort_ok(pmv(27.0))

    def test_comfort_band_at_21_fails(self) -> None:
        """21°C (PMV ≈ -1.1) is outside comfort band for clo=0.7."""
        assert not comfort_ok(pmv(21.0))

    def test_return_type_is_float(self) -> None:
        assert isinstance(pmv(22.0), float)

    def test_rounded_to_three_places(self) -> None:
        val = pmv(22.0)
        assert val == round(val, 3)


class TestPMVLabels:
    def test_comfortable_label(self) -> None:
        """PMV ≈ 0.09 at 25°C → COMFORTABLE."""
        assert pmv_label(pmv(25.0)) == "COMFORTABLE"

    def test_warm_label(self) -> None:
        """PMV ≈ 0.71 at 27°C → SLIGHTLY_WARM."""
        val = pmv(27.0)
        assert pmv_label(val) in ("SLIGHTLY_WARM", "WARM", "VERY_HOT")

    def test_cold_label(self) -> None:
        """PMV ≈ -1.7 at 19°C → COLD."""
        val = pmv(19.0)
        assert pmv_label(val) in ("COLD", "SLIGHTLY_COOL", "VERY_COLD")


class TestComfortOk:
    @pytest.mark.parametrize("v", [-0.5, 0.0, 0.5])
    def test_boundary_inclusive(self, v: float) -> None:
        assert comfort_ok(v)

    @pytest.mark.parametrize("v", [-0.51, 0.51, 1.0, -1.0])
    def test_outside_band(self, v: float) -> None:
        assert not comfort_ok(v)
