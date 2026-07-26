"""
tests/test_agent_tools.py — ToolExecutor dispatch + ControlAction accumulation.

Uses a mock EPReader (with a pre-canned SensorReading) and a mock EPWriter
so no EnergyPlus process is needed.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from bridge.constants import CONTROLLED_ZONES
from bridge.ep_reader import SensorReading
from bridge.ep_writer import ControlAction
from agent.tools import ToolExecutor, _DEFAULT_BASELINE_KWH


def _make_reading(timestep: int = 1) -> SensorReading:
    zones = list(CONTROLLED_ZONES)
    return SensorReading(
        timestep=timestep,
        zone_temperatures={z: 23.0 for z in zones},
        indoor_air_quality={z: 600.0 for z in zones},
        occupancy={z: 2 for z in zones},
        cooling_setpoints={z: 24.0 for z in zones},
        heating_setpoints={z: 20.0 for z in zones},
        outdoor_temp=28.0,
        energy_step_j=1_800_000.0,   # 0.5 kWh per 15-min step
        energy_consumption_kwh=5.0,
    )


@pytest.fixture()
def executor() -> ToolExecutor:
    reader = MagicMock()
    reader._latest_reading = _make_reading()
    writer = MagicMock()
    return ToolExecutor(reader, writer, sim_hour=10, baseline_kwh=172.48)


class TestReadSensors:
    def test_returns_timestep(self, executor: ToolExecutor) -> None:
        result = executor.execute("read_sensors", {})
        assert result.get("timestep") == 1

    def test_returns_all_zones_by_default(self, executor: ToolExecutor) -> None:
        result = executor.execute("read_sensors", {})
        for zone in CONTROLLED_ZONES:
            assert zone in result["zones"]

    def test_filters_zones(self, executor: ToolExecutor) -> None:
        result = executor.execute("read_sensors", {"zones": ["SPACE1-1"]})
        assert "SPACE1-1" in result["zones"]
        assert "SPACE2-1" not in result["zones"]

    def test_comfort_annotations_present(self, executor: ToolExecutor) -> None:
        result = executor.execute("read_sensors", {})
        assert "comfort_annotations" in result
        assert "SPACE1-1" in result["comfort_annotations"]

    def test_carbon_intensity_present(self, executor: ToolExecutor) -> None:
        result = executor.execute("read_sensors", {})
        assert "carbon_intensity" in result
        assert result["carbon_intensity"]["hour"] == 10


class TestSetHVACSetpoint:
    def test_valid_zone_queued(self, executor: ToolExecutor) -> None:
        result = executor.execute(
            "set_hvac_setpoint",
            {"zone": "SPACE1-1", "cooling_setpoint": 23.0, "heating_setpoint": 20.0},
        )
        assert result["queued"] is True
        assert executor.pending_action.cooling_setpoints["SPACE1-1"] == 23.0
        assert executor.pending_action.heating_setpoints["SPACE1-1"] == 20.0

    def test_unknown_zone_returns_error(self, executor: ToolExecutor) -> None:
        result = executor.execute(
            "set_hvac_setpoint",
            {"zone": "FAKE-ZONE", "cooling_setpoint": 23.0, "heating_setpoint": 20.0},
        )
        assert "error" in result

    def test_multiple_zones_accumulated(self, executor: ToolExecutor) -> None:
        for zone in ["SPACE1-1", "SPACE2-1"]:
            executor.execute(
                "set_hvac_setpoint",
                {"zone": zone, "cooling_setpoint": 24.0, "heating_setpoint": 20.0},
            )
        assert "SPACE1-1" in executor.pending_action.cooling_setpoints
        assert "SPACE2-1" in executor.pending_action.cooling_setpoints


class TestSetLightingLevel:
    def test_valid_level_queued(self, executor: ToolExecutor) -> None:
        result = executor.execute(
            "set_lighting_level", {"zone": "SPACE3-1", "level": 0.5}
        )
        assert result["queued"] is True
        assert executor.pending_action.lighting_levels["SPACE3-1"] == 0.5

    def test_level_clamped_to_zero_one(self, executor: ToolExecutor) -> None:
        executor.execute("set_lighting_level", {"zone": "SPACE1-1", "level": 1.5})
        assert executor.pending_action.lighting_levels["SPACE1-1"] == 1.0

        executor.execute("set_lighting_level", {"zone": "SPACE2-1", "level": -0.5})
        assert executor.pending_action.lighting_levels["SPACE2-1"] == 0.0


class TestGetEnergyReport:
    def test_returns_cumulative_kwh(self, executor: ToolExecutor) -> None:
        executor._latest_reading = _make_reading()
        result = executor.execute("get_energy_report", {"compare_to_baseline": False})
        assert result["cumulative_kwh"] == 5.0

    def test_savings_vs_baseline(self, executor: ToolExecutor) -> None:
        executor._latest_reading = _make_reading()
        result = executor.execute("get_energy_report", {"compare_to_baseline": True})
        assert "savings_kwh" in result
        assert result["baseline_kwh"] == pytest.approx(172.48)
        assert result["savings_kwh"] == pytest.approx(172.48 - 5.0)

    def test_peak_status_present(self, executor: ToolExecutor) -> None:
        executor._latest_reading = _make_reading()
        result = executor.execute("get_energy_report", {})
        assert result["peak_status"] in ("OK", "APPROACHING", "EXCEEDED")


class TestPredictComfort:
    def test_comfortable_setpoint(self, executor: ToolExecutor) -> None:
        """24°C (PMV ≈ -0.21) is in the comfort band for clo=0.7, met=1.1."""
        result = executor.execute(
            "predict_comfort", {"zone": "SPACE1-1", "proposed_setpoint": 24.0}
        )
        assert result["in_comfort_band"] is True

    def test_too_warm_setpoint(self, executor: ToolExecutor) -> None:
        """28°C (PMV ≈ +1.02) is outside the comfort band."""
        result = executor.execute(
            "predict_comfort", {"zone": "SPACE1-1", "proposed_setpoint": 28.0}
        )
        assert result["in_comfort_band"] is False
        assert "warm" in result["recommendation"].lower() or "warm" in result["comfort_label"].lower()

    def test_returns_zone_name(self, executor: ToolExecutor) -> None:
        result = executor.execute(
            "predict_comfort", {"zone": "SPACE2-1", "proposed_setpoint": 24.0}
        )
        assert result["zone"] == "SPACE2-1"


class TestUnknownTool:
    def test_unknown_tool_returns_error(self, executor: ToolExecutor) -> None:
        result = executor.execute("nonexistent_tool", {})
        assert "error" in result
