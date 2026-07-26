"""
ep_reader.py — live sensor extraction from a running EnergyPlus state.

Fail-loud on invalid handles: dumps available API data CSV and raises.
Accumulates facility electricity meter (J) into cumulative kWh.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from bridge.constants import (
    CONTROLLED_ZONES,
    FACILITY_ENERGY_VAR,
    FACILITY_METER,
    JOULES_TO_KWH,
    LIGHTS_ACTUATOR_NAME,
)

logger = logging.getLogger("EcoLoop.bridge.reader")


@dataclass
class SensorReading:
    timestep: int
    zone_temperatures: dict[str, float] = field(default_factory=dict)
    indoor_air_quality: dict[str, float] = field(default_factory=dict)  # CO2 ppm
    occupancy: dict[str, int] = field(default_factory=dict)
    cooling_setpoints: dict[str, float] = field(default_factory=dict)
    heating_setpoints: dict[str, float] = field(default_factory=dict)
    outdoor_temp: float = 0.0
    energy_step_j: float = 0.0
    energy_consumption_kwh: float = 0.0  # cumulative

    def to_compact(self) -> dict[str, Any]:
        """Rounded snapshot for LLM prompts / JSONL logs."""
        return {
            "timestep": self.timestep,
            "outdoor_temp": round(self.outdoor_temp, 1),
            "energy_kwh_cum": round(self.energy_consumption_kwh, 3),
            "zones": {
                z: {
                    "temp": round(self.zone_temperatures.get(z, 0.0), 1),
                    "co2": round(self.indoor_air_quality.get(z, 0.0), 0),
                    "occ": int(self.occupancy.get(z, 0)),
                    "cool_sp": round(self.cooling_setpoints.get(z, 0.0), 1),
                    "heat_sp": round(self.heating_setpoints.get(z, 0.0), 1),
                }
                for z in CONTROLLED_ZONES
            },
        }

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class HandleError(RuntimeError):
    """Raised when a required variable/meter/actuator handle is invalid (-1)."""


class EPReader:
    """Reads live simulation variables from EnergyPlus."""

    def __init__(self, api: Any, state: Any, *, dump_dir: str | Path = "data/logs") -> None:
        self.api = api
        self.state = state
        self.dump_dir = Path(dump_dir)
        self._var_handles: dict[tuple[str, str], int] = {}
        self._energy_from_meter = False
        self._meter_handle: int | None = None
        self._handles_ready = False
        self._energy_j_cum = 0.0
        self._prev_facility_j: float | None = None
        self.lights_energy_j: dict[str, float] = {z: 0.0 for z in CONTROLLED_ZONES}

    def _dump_available(self) -> Path:
        self.dump_dir.mkdir(parents=True, exist_ok=True)
        out = self.dump_dir / "available_api_data.csv"
        try:
            raw = self.api.exchange.list_available_api_data_csv(self.state)
            if isinstance(raw, (bytes, bytearray)):
                out.write_bytes(bytes(raw))
            else:
                out.write_text(str(raw), encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            out.write_text(f"dump_failed: {exc}\n", encoding="utf-8")
        return out

    def _get_variable_handle(self, name: str, key: str) -> int:
        cache_key = (name, key)
        if cache_key not in self._var_handles:
            handle = int(self.api.exchange.get_variable_handle(self.state, name, key))
            self._var_handles[cache_key] = handle
        return self._var_handles[cache_key]

    def _ensure_handles(self) -> None:
        if self._handles_ready:
            return

        bad: list[str] = []
        for zone in CONTROLLED_ZONES:
            for name in (
                "Zone Mean Air Temperature",
                "Zone People Occupant Count",
                "Zone Air CO2 Concentration",
                "Zone Thermostat Cooling Setpoint Temperature",
                "Zone Thermostat Heating Setpoint Temperature",
            ):
                h = self._get_variable_handle(name, zone)
                if h < 0:
                    bad.append(f"{name} / {zone} -> {h}")
            lights_key = LIGHTS_ACTUATOR_NAME[zone]
            h = self._get_variable_handle("Lights Electricity Energy", lights_key)
            if h < 0:
                bad.append(f"Lights Electricity Energy / {lights_key} -> {h}")

        outdoor_h = self._get_variable_handle(
            "Site Outdoor Air Drybulb Temperature", "Environment"
        )
        if outdoor_h < 0:
            bad.append(f"Site Outdoor Air Drybulb Temperature / Environment -> {outdoor_h}")

        # Energy: prefer Electricity:Building meter (Facility meter handle is -1 on EP26 API)
        self._meter_handle = int(
            self.api.exchange.get_meter_handle(self.state, FACILITY_METER)
        )
        if self._meter_handle >= 0:
            self._energy_from_meter = True
        else:
            energy_name, energy_key = FACILITY_ENERGY_VAR
            energy_h = self._get_variable_handle(energy_name, energy_key)
            if energy_h < 0:
                bad.append(
                    f"meter {FACILITY_METER} -> {self._meter_handle}; "
                    f"{energy_name} / {energy_key} -> {energy_h}"
                )
            else:
                self._energy_from_meter = False

        if bad:
            dump = self._dump_available()
            msg = (
                "Invalid EnergyPlus handles (T2.3 fail-loud):\n  - "
                + "\n  - ".join(bad)
                + f"\nDumped available API data to {dump}"
            )
            logger.error(msg)
            raise HandleError(msg)

        self._handles_ready = True
        logger.info(
            "All sensor handles valid (%s vars, energy_via=%s)",
            len(self._var_handles),
            "meter" if self._energy_from_meter else "variable",
        )

    def _v(self, name: str, key: str) -> float:
        handle = self._get_variable_handle(name, key)
        return float(self.api.exchange.get_variable_value(self.state, handle))

    def read(self, timestep: int) -> SensorReading:
        """Read all sensor values at the current timestep."""
        self._ensure_handles()

        zone_temps: dict[str, float] = {}
        zone_co2: dict[str, float] = {}
        zone_occ: dict[str, int] = {}
        cool: dict[str, float] = {}
        heat: dict[str, float] = {}

        for zone in CONTROLLED_ZONES:
            zone_temps[zone] = self._v("Zone Mean Air Temperature", zone)
            zone_co2[zone] = self._v("Zone Air CO2 Concentration", zone)
            zone_occ[zone] = int(round(self._v("Zone People Occupant Count", zone)))
            cool[zone] = self._v("Zone Thermostat Cooling Setpoint Temperature", zone)
            heat[zone] = self._v("Zone Thermostat Heating Setpoint Temperature", zone)
            lights_key = LIGHTS_ACTUATOR_NAME[zone]
            self.lights_energy_j[zone] = self._v("Lights Electricity Energy", lights_key)

        outdoor = self._v("Site Outdoor Air Drybulb Temperature", "Environment")

        if self._energy_from_meter:
            assert self._meter_handle is not None
            step_j = float(self.api.exchange.get_meter_value(self.state, self._meter_handle))
            if step_j < 0:
                step_j = 0.0
            self._energy_j_cum += step_j
        else:
            # Facility Net Purchased is per-timestep Joules (not cumulative) on this build
            energy_name, energy_key = FACILITY_ENERGY_VAR
            step_j = max(0.0, self._v(energy_name, energy_key))
            self._energy_j_cum += step_j

        return SensorReading(
            timestep=timestep,
            zone_temperatures=zone_temps,
            indoor_air_quality=zone_co2,
            occupancy=zone_occ,
            cooling_setpoints=cool,
            heating_setpoints=heat,
            outdoor_temp=outdoor,
            energy_step_j=step_j,
            energy_consumption_kwh=self._energy_j_cum * JOULES_TO_KWH,
        )
