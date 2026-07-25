"""
ep_reader.py — live sensor reader.

Job: Extract zone temps, CO2, occupancy, outdoor temp, and energy
from the running EnergyPlus state at each timestep.

Build: after ep_runner callbacks fire; print values to console first.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SensorReading:
    timestep: int
    zone_temperatures: dict[str, float] = field(default_factory=dict)  # °C
    indoor_air_quality: dict[str, float] = field(default_factory=dict)  # CO2 ppm
    energy_consumption_kwh: float = 0.0
    outdoor_temp: float = 0.0
    occupancy: dict[str, int] = field(default_factory=dict)
    hvac_setpoints: dict[str, float] = field(default_factory=dict)


class EPReader:
    """Reads live simulation variables from EnergyPlus."""

    def __init__(self, api: Any, state: Any) -> None:
        self.api = api
        self.state = state
        self._handle_cache: dict[tuple[str, str], int] = {}

    def read(self, timestep: int) -> SensorReading:
        """Read all sensor values at the current timestep."""
        raise NotImplementedError("Map IDF zone names + get_variable_handle/value.")
