"""
tools.py — tool implementations executed by the orchestrator.

Maps MCP tool names → EPReader / EPWriter / comfort helpers.
The LLM proposes tool calls; ToolExecutor executes them against the live
simulation and accumulates a ControlAction applied at end-of-timestep.

Design
------
- read_sensors     : reads EPReader, caches result for the timestep
- set_hvac_setpoint: adds to pending_action (applied in bulk at end of step)
- set_lighting_level: adds to pending_action
- get_energy_report: uses cached sensor reading + baseline kWh from summary.json
- predict_comfort  : pure computation, no sim access
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from agent.comfort import pmv, pmv_label
from agent.grid import carbon_intensity, intensity_label, peak_status
from agent.mcp_server import MCP_TOOLS
from bridge.constants import CONTROLLED_ZONES
from bridge.ep_writer import ControlAction

logger = logging.getLogger("EcoLoop.agent.tools")

# Baseline kWh from Phase 1 (frozen — never updated during agent tuning)
_DEFAULT_BASELINE_KWH = 172.48


def _load_baseline_kwh() -> float:
    """Read baseline kWh from data/baseline_results/summary.json if present."""
    paths = [
        Path("data/baseline_results/summary.json"),
        Path(__file__).parent.parent / "data" / "baseline_results" / "summary.json",
    ]
    for p in paths:
        if p.is_file():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                kwh = float(data.get("electricity_facility_kwh", _DEFAULT_BASELINE_KWH))
                logger.debug("Loaded baseline: %.3f kWh from %s", kwh, p)
                return kwh
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not parse baseline summary: %s", exc)
    return _DEFAULT_BASELINE_KWH


class ToolExecutor:
    """Dispatches LLM tool calls to bridge + report helpers.

    Lifecycle:
        executor = ToolExecutor(reader, writer, sim_hour)
        # orchestrator processes LLM tool_calls:
        for tc in tool_calls:
            result = executor.execute(tc["name"], tc["args"])
        # at end of timestep:
        executor.pending_action  →  ControlAction to apply via EPWriter
    """

    def __init__(
        self,
        reader: Any,
        writer: Any,
        *,
        sim_hour: int = 0,
        baseline_kwh: float | None = None,
    ) -> None:
        self.reader = reader
        self.writer = writer
        self.sim_hour = sim_hour
        self.baseline_kwh: float = baseline_kwh if baseline_kwh is not None else _load_baseline_kwh()
        self._latest_reading: Any = None  # SensorReading
        self.pending_action = ControlAction()
        self._tool_results: list[dict[str, Any]] = []

    def get_tool_definitions(self) -> list[dict]:
        return MCP_TOOLS

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    def execute(self, name: str, payload: dict) -> dict[str, Any]:
        """Run one tool call; returns a serialisable result dict."""
        logger.debug("Tool call: %s(%s)", name, payload)
        handlers = {
            "read_sensors": self._read_sensors,
            "set_hvac_setpoint": self._set_hvac_setpoint,
            "set_lighting_level": self._set_lighting_level,
            "get_energy_report": self._get_energy_report,
            "predict_comfort": self._predict_comfort,
        }
        handler = handlers.get(name)
        if handler is None:
            result: dict[str, Any] = {"error": f"Unknown tool: {name}"}
        else:
            try:
                result = handler(**payload)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Tool %s raised: %s", name, exc)
                result = {"error": str(exc)}

        self._tool_results.append({"tool": name, "args": payload, "result": result})
        return result

    # ------------------------------------------------------------------
    # Tool implementations
    # ------------------------------------------------------------------

    def _read_sensors(self, zones: list[str] | None = None) -> dict[str, Any]:
        """Read current building state from the live EnergyPlus simulation."""
        reading = self.reader._latest_reading  # set by orchestrator before tools run
        if reading is None:
            return {"error": "Sensor reading not yet available at this timestep."}
        self._latest_reading = reading
        data = reading.to_compact()

        if zones:
            # Filter to requested zones
            data["zones"] = {z: v for z, v in data["zones"].items() if z in zones}

        # Annotate with comfort and occupancy flags
        annotations: dict[str, dict[str, Any]] = {}
        for zone, zd in data["zones"].items():
            temp = zd.get("temp", 22.0)
            cool_sp = zd.get("cool_sp", 24.0)
            pmv_val = pmv(temp)
            annotations[zone] = {
                "pmv": pmv_val,
                "comfort": pmv_label(pmv_val),
                "co2_status": "HIGH" if zd.get("co2", 0) > 900 else "OK",
            }
        data["comfort_annotations"] = annotations
        data["carbon_intensity"] = {
            "hour": self.sim_hour,
            "g_per_kwh": carbon_intensity(self.sim_hour),
            "label": intensity_label(self.sim_hour),
        }
        return data

    def _set_hvac_setpoint(
        self,
        zone: str,
        cooling_setpoint: float,
        heating_setpoint: float,
    ) -> dict[str, Any]:
        """Queue HVAC setpoint change for zone (applied at end of timestep)."""
        if zone not in CONTROLLED_ZONES:
            return {"error": f"Unknown zone '{zone}'. Valid: {list(CONTROLLED_ZONES)}"}
        self.pending_action.cooling_setpoints[zone] = cooling_setpoint
        self.pending_action.heating_setpoints[zone] = heating_setpoint
        pmv_val = pmv(cooling_setpoint)
        return {
            "queued": True,
            "zone": zone,
            "cooling_setpoint": cooling_setpoint,
            "heating_setpoint": heating_setpoint,
            "predicted_pmv_at_cool_sp": pmv_val,
            "comfort": pmv_label(pmv_val),
            "note": "Safety clamps applied server-side before actuator write.",
        }

    def _set_lighting_level(self, zone: str, level: float) -> dict[str, Any]:
        """Queue lighting level change for zone (applied at end of timestep)."""
        if zone not in CONTROLLED_ZONES:
            return {"error": f"Unknown zone '{zone}'. Valid: {list(CONTROLLED_ZONES)}"}
        self.pending_action.lighting_levels[zone] = max(0.0, min(1.0, level))
        from bridge.constants import DESIGN_LIGHTS_W
        watts = self.pending_action.lighting_levels[zone] * DESIGN_LIGHTS_W.get(zone, 1584.0)
        return {
            "queued": True,
            "zone": zone,
            "level": self.pending_action.lighting_levels[zone],
            "estimated_watts": round(watts, 1),
            "note": "Occupied zones floored at 0.3 server-side.",
        }

    def _get_energy_report(self, compare_to_baseline: bool = True) -> dict[str, Any]:
        """Return energy status including savings vs baseline."""
        reading = self._latest_reading or getattr(self.reader, "_latest_reading", None)
        if reading is None:
            return {"error": "No sensor reading cached; call read_sensors first."}

        current_kwh = reading.energy_consumption_kwh
        step_j = reading.energy_step_j
        step_kw = (step_j / 3_600_000.0) * 4.0  # 15-min step → kW average

        report: dict[str, Any] = {
            "cumulative_kwh": round(current_kwh, 3),
            "current_demand_kw": round(step_kw, 2),
            "peak_status": peak_status(step_kw),
            "carbon_intensity_g_per_kwh": carbon_intensity(self.sim_hour),
            "grid_label": intensity_label(self.sim_hour),
        }
        if compare_to_baseline:
            savings = self.baseline_kwh - current_kwh
            pct = (savings / self.baseline_kwh * 100.0) if self.baseline_kwh > 0 else 0.0
            report["baseline_kwh"] = round(self.baseline_kwh, 3)
            report["savings_kwh"] = round(savings, 3)
            report["savings_pct"] = round(pct, 1)
        return report

    def _predict_comfort(
        self, zone: str, proposed_setpoint: float
    ) -> dict[str, Any]:
        """Estimate PMV at proposed cooling setpoint."""
        pmv_val = pmv(proposed_setpoint)
        reading = self._latest_reading or getattr(self.reader, "_latest_reading", None)
        current_temp: float | None = None
        if reading:
            current_temp = reading.zone_temperatures.get(zone)
        return {
            "zone": zone,
            "proposed_setpoint_c": proposed_setpoint,
            "predicted_pmv": pmv_val,
            "comfort_label": pmv_label(pmv_val),
            "in_comfort_band": abs(pmv_val) <= 0.5,
            "current_zone_temp_c": round(current_temp, 1) if current_temp is not None else None,
            "recommendation": (
                "Acceptable" if abs(pmv_val) <= 0.5
                else ("Too warm — lower setpoint" if pmv_val > 0.5 else "Too cool — raise setpoint")
            ),
        }
