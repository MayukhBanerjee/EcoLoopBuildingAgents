"""
clamps.py — pure safety math for INV-1 .. INV-5 (unit-testable, no EnergyPlus).

The LLM may propose anything. This module is law.
"""

from __future__ import annotations

from dataclasses import dataclass

from bridge.constants import (
    COOL_OCC_MAX,
    COOL_OCC_MIN,
    COOL_UNOCC_MAX,
    DEADBAND_C,
    HEAT_OCC_MAX,
    HEAT_OCC_MIN,
    HEAT_UNOCC_MIN,
    LIGHT_MAX,
    LIGHT_MIN,
    LIGHT_OCC_MIN,
    RAMP_MAX_C,
)


@dataclass(frozen=True)
class ClampEvent:
    zone: str
    field: str
    requested: float
    applied: float
    rule: str


def clamp_cooling(
    requested: float,
    *,
    occupied: bool,
    last: float | None,
) -> tuple[float, list[ClampEvent], str]:
    """Return (applied, events, zone_placeholder_filled_later)."""
    events: list[ClampEvent] = []
    lo = COOL_OCC_MIN
    hi = COOL_OCC_MAX if occupied else COOL_UNOCC_MAX
    value = requested
    if value < lo or value > hi:
        events.append(
            ClampEvent("", "cooling", requested, min(hi, max(lo, value)), "INV-1")
        )
        value = min(hi, max(lo, value))
    if last is not None:
        delta = value - last
        if abs(delta) > RAMP_MAX_C:
            limited = last + (RAMP_MAX_C if delta > 0 else -RAMP_MAX_C)
            events.append(ClampEvent("", "cooling", value, limited, "INV-4"))
            value = limited
    return value, events, "cooling"


def clamp_heating(
    requested: float,
    *,
    occupied: bool,
    last: float | None,
    cooling_applied: float,
) -> tuple[float, list[ClampEvent]]:
    events: list[ClampEvent] = []
    lo = HEAT_UNOCC_MIN if not occupied else HEAT_OCC_MIN
    hi = HEAT_OCC_MAX
    value = requested
    if value < lo or value > hi:
        events.append(
            ClampEvent("", "heating", requested, min(hi, max(lo, value)), "INV-2")
        )
        value = min(hi, max(lo, value))
    if last is not None:
        delta = value - last
        if abs(delta) > RAMP_MAX_C:
            limited = last + (RAMP_MAX_C if delta > 0 else -RAMP_MAX_C)
            events.append(ClampEvent("", "heating", value, limited, "INV-4"))
            value = limited
    # INV-3 deadband: heating < cooling - 1
    max_heat = cooling_applied - DEADBAND_C
    if value > max_heat:
        events.append(ClampEvent("", "heating", value, max_heat, "INV-3"))
        value = max_heat
    return value, events


def clamp_lighting(requested: float, *, occupied: bool) -> tuple[float, list[ClampEvent]]:
    events: list[ClampEvent] = []
    value = min(LIGHT_MAX, max(LIGHT_MIN, requested))
    if value != requested:
        events.append(ClampEvent("", "lighting", requested, value, "INV-5-range"))
    if occupied and value < LIGHT_OCC_MIN:
        events.append(ClampEvent("", "lighting", value, LIGHT_OCC_MIN, "INV-5"))
        value = LIGHT_OCC_MIN
    return value, events


def stamp_zone(events: list[ClampEvent], zone: str) -> list[ClampEvent]:
    return [
        ClampEvent(zone=zone, field=e.field, requested=e.requested, applied=e.applied, rule=e.rule)
        for e in events
    ]
