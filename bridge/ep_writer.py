"""
ep_writer.py — control action injector.

Job: Write LLM-decided setpoints / lighting levels into the live
simulation via EMS actuators. Enforce hard clamps (18–26°C, 0–1 lighting).

Build: after ep_reader works; hardcode one setpoint change to prove actuators.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ControlAction:
    zone_setpoints: dict[str, float] = field(default_factory=dict)  # °C
    ventilation_rates: dict[str, float] = field(default_factory=dict)  # ACH
    lighting_levels: dict[str, float] = field(default_factory=dict)  # 0.0–1.0


class EPWriter:
    """Injects control actions into a running EnergyPlus simulation."""

    def __init__(self, api: Any, state: Any) -> None:
        self.api = api
        self.state = state
        self._actuator_cache: dict[tuple[str, str, str], int] = {}

    def apply(self, action: ControlAction) -> None:
        """Apply control actions (clamped to safe operating ranges)."""
        raise NotImplementedError("Wire get_actuator_handle + set_actuator_value.")
