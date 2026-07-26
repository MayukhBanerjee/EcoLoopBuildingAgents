"""
ep_writer.py — EMS actuator injection with hard safety clamps (INV-1..5).

Actuator names verified against data/runtime_oracle/eplusout.edd:
  - Zone Temperature Control / Cooling|Heating Setpoint / <ZONE>
  - Lights / Electricity Rate / <ZONE> LIGHTS 1   [W]
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from bridge.clamps import (
    ClampEvent,
    clamp_cooling,
    clamp_heating,
    clamp_lighting,
    stamp_zone,
)
from bridge.constants import (
    CONTROLLED_ZONES,
    DESIGN_LIGHTS_W,
    LIGHTS_ACTUATOR_NAME,
)

logger = logging.getLogger("EcoLoop.bridge.writer")


@dataclass
class ControlAction:
    """Desired control setpoints for one timestep (pre-clamp)."""

    cooling_setpoints: dict[str, float] = field(default_factory=dict)
    heating_setpoints: dict[str, float] = field(default_factory=dict)
    lighting_levels: dict[str, float] = field(default_factory=dict)  # 0.0-1.0 fraction
    ventilation_rates: dict[str, float] = field(default_factory=dict)  # reserved

    # Back-compat alias used by early stubs / fallback
    @property
    def zone_setpoints(self) -> dict[str, float]:
        return self.cooling_setpoints


class ActuatorError(RuntimeError):
    """Raised when an actuator handle cannot be resolved."""


class EPWriter:
    """Injects control actions into a running EnergyPlus simulation."""

    def __init__(self, api: Any, state: Any) -> None:
        self.api = api
        self.state = state
        self._actuator_cache: dict[tuple[str, str, str], int] = {}
        self._actuators_ready = False
        # last applied absolute setpoints for ramp limiting
        self.last_cooling: dict[str, float] = {}
        self.last_heating: dict[str, float] = {}
        self.clamp_log: list[dict[str, Any]] = []

    def _get_actuator(self, component_type: str, control_type: str, name: str) -> int:
        key = (component_type, control_type, name)
        if key not in self._actuator_cache:
            handle = int(
                self.api.exchange.get_actuator_handle(
                    self.state, component_type, control_type, name
                )
            )
            self._actuator_cache[key] = handle
        return self._actuator_cache[key]

    def ensure_actuators(self) -> None:
        """Resolve and validate all required actuators (call once after data-ready)."""
        if self._actuators_ready:
            return
        bad: list[str] = []
        for zone in CONTROLLED_ZONES:
            for ctrl in ("Cooling Setpoint", "Heating Setpoint"):
                h = self._get_actuator("Zone Temperature Control", ctrl, zone)
                if h < 0:
                    bad.append(f"Zone Temperature Control / {ctrl} / {zone} -> {h}")
            lights = LIGHTS_ACTUATOR_NAME[zone]
            h = self._get_actuator("Lights", "Electricity Rate", lights)
            if h < 0:
                bad.append(f"Lights / Electricity Rate / {lights} -> {h}")
        if bad:
            raise ActuatorError(
                "Invalid actuator handles (check eplusout.edd):\n  - " + "\n  - ".join(bad)
            )
        self._actuators_ready = True
        logger.info("All actuators valid (%s handles)", len(self._actuator_cache))

    def seed_from_sensors(
        self,
        cooling: dict[str, float],
        heating: dict[str, float],
    ) -> None:
        """Initialize ramp baselines from live thermostat readings.

        Schedule 'off' sentinels (e.g. cooling 40 C) are snapped into the
        legal band so INV-4 does not waste half a day ramping 40 -> 26.
        """
        from bridge.constants import COOL_UNOCC_MAX, HEAT_OCC_MIN

        for zone in CONTROLLED_ZONES:
            if zone in cooling and zone not in self.last_cooling:
                c = float(cooling[zone])
                if c > COOL_UNOCC_MAX:
                    c = COOL_UNOCC_MAX
                self.last_cooling[zone] = c
            if zone in heating and zone not in self.last_heating:
                h = float(heating[zone])
                if h < HEAT_OCC_MIN:
                    h = HEAT_OCC_MIN
                self.last_heating[zone] = h

    def apply(
        self,
        action: ControlAction,
        occupancy: dict[str, int] | None = None,
    ) -> list[ClampEvent]:
        """
        Apply control actions with INV-1..5 clamps.

        Returns the list of clamp events (empty if LLM stayed in bounds).
        """
        self.ensure_actuators()
        occ = occupancy or {}
        events: list[ClampEvent] = []
        ex = self.api.exchange

        zones = set(action.cooling_setpoints) | set(action.heating_setpoints) | set(
            action.lighting_levels
        )
        for zone in zones:
            if zone not in CONTROLLED_ZONES:
                logger.warning("Ignoring unknown zone %s", zone)
                continue
            occupied = int(occ.get(zone, 0)) > 0

            cool_req = action.cooling_setpoints.get(zone)
            heat_req = action.heating_setpoints.get(zone)

            cool_applied = self.last_cooling.get(zone)
            heat_applied = self.last_heating.get(zone)

            if cool_req is not None:
                cool_applied, cool_events, _ = clamp_cooling(
                    float(cool_req),
                    occupied=occupied,
                    last=self.last_cooling.get(zone),
                )
                events.extend(stamp_zone(cool_events, zone))
                handle = self._get_actuator(
                    "Zone Temperature Control", "Cooling Setpoint", zone
                )
                ex.set_actuator_value(self.state, handle, cool_applied)
                self.last_cooling[zone] = cool_applied

            if heat_req is not None:
                # If cooling not updated this step, use last cooling for deadband
                cool_for_deadband = (
                    cool_applied
                    if cool_applied is not None
                    else self.last_cooling.get(zone, 24.0)
                )
                heat_applied, heat_events = clamp_heating(
                    float(heat_req),
                    occupied=occupied,
                    last=self.last_heating.get(zone),
                    cooling_applied=cool_for_deadband,
                )
                events.extend(stamp_zone(heat_events, zone))
                handle = self._get_actuator(
                    "Zone Temperature Control", "Heating Setpoint", zone
                )
                ex.set_actuator_value(self.state, handle, heat_applied)
                self.last_heating[zone] = heat_applied

            if zone in action.lighting_levels:
                level, light_events = clamp_lighting(
                    float(action.lighting_levels[zone]), occupied=occupied
                )
                events.extend(stamp_zone(light_events, zone))
                watts = level * DESIGN_LIGHTS_W[zone]
                handle = self._get_actuator(
                    "Lights", "Electricity Rate", LIGHTS_ACTUATOR_NAME[zone]
                )
                ex.set_actuator_value(self.state, handle, watts)

        for ev in events:
            record = {
                "zone": ev.zone,
                "field": ev.field,
                "requested": ev.requested,
                "applied": ev.applied,
                "rule": ev.rule,
            }
            self.clamp_log.append(record)
            logger.info(
                "CLAMP %s %s: %.2f -> %.2f (%s)",
                ev.zone,
                ev.field,
                ev.requested,
                ev.applied,
                ev.rule,
            )
        return events
