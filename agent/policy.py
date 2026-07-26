"""
policy.py — adaptive rule-based control policy (deterministic safety net).

Used when the LLM produces no control actions (read-only response, timeout,
rate-limit exhaustion, chaos drill). Unlike the old static 22/20 hold, this
policy adapts to the live sensor snapshot, so even fully offline runs steer
the building sensibly and save energy:

  Unoccupied zone : cooling 28 C, heating 16 C, lights 0.0   (deep setback)
  Occupied zone   : cooling targeted to warm edge of comfort, heating 20 C,
                    lights untouched unless zone is empty

The INV-1..5 clamps in EPWriter still apply on top of whatever this returns,
so the policy can never violate safety invariants (ramp rate included).
"""

from __future__ import annotations

from typing import Any

from agent.comfort import pmv
from bridge.constants import (
    CONTROLLED_ZONES,
    COOL_OCC_MAX,
    COOL_UNOCC_MAX,
    HEAT_OCC_MIN,
    HEAT_UNOCC_MIN,
)
from bridge.ep_writer import ControlAction

# Occupied targets: warm edge of ASHRAE comfort for met=1.1 / clo=0.7
# (PMV neutral is ~24.7 C; 25.0 keeps |PMV| < 0.15 while minimising cooling).
OCC_COOLING_C = 25.0
OCC_HEATING_C = 20.0
# If the zone is already too warm (PMV > +0.5), cool harder but stay legal.
OCC_COOLING_WARM_C = 24.0


def policy_action(reading: Any) -> ControlAction:
    """Compute an adaptive ControlAction from a SensorReading.

    Works with any object exposing zone_temperatures / occupancy dicts
    (falls back to safe occupied targets when data is missing).
    """
    temps: dict[str, float] = getattr(reading, "zone_temperatures", None) or {}
    occupancy: dict[str, int] = getattr(reading, "occupancy", None) or {}

    cooling: dict[str, float] = {}
    heating: dict[str, float] = {}
    lights: dict[str, float] = {}

    for zone in CONTROLLED_ZONES:
        occupied = int(occupancy.get(zone, 0)) > 0
        if not occupied:
            # Deep setback: stop conditioning and lighting an empty room.
            cooling[zone] = COOL_UNOCC_MAX      # 28.0
            heating[zone] = HEAT_UNOCC_MIN      # 16.0
            lights[zone] = 0.0
        else:
            temp = float(temps.get(zone, 23.0))
            too_warm = pmv(temp) > 0.5
            cooling[zone] = OCC_COOLING_WARM_C if too_warm else OCC_COOLING_C
            # Never request cooling above the occupied legal cap
            cooling[zone] = min(cooling[zone], COOL_OCC_MAX)
            heating[zone] = max(OCC_HEATING_C, HEAT_OCC_MIN)
            # Leave lights alone in occupied zones (schedule/LLM owns them);
            # the INV-5 floor (0.3) protects occupants either way.

    return ControlAction(
        cooling_setpoints=cooling,
        heating_setpoints=heating,
        lighting_levels=lights,
    )


def describe_policy_action(action: ControlAction, occupancy: dict[str, int]) -> str:
    """One-line human-readable summary for the decision log."""
    unocc = [z for z in CONTROLLED_ZONES if int(occupancy.get(z, 0)) <= 0]
    occ = [z for z in CONTROLLED_ZONES if int(occupancy.get(z, 0)) > 0]
    parts = []
    if unocc:
        parts.append(
            f"{len(unocc)} unoccupied zones -> setback 28/16 C, lights off"
        )
    if occ:
        parts.append(f"{len(occ)} occupied zones -> comfort-edge 25/20 C")
    return "; ".join(parts) if parts else "no zones to control"
