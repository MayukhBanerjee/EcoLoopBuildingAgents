"""T2.5 — pure unit tests for INV-1..5 clamp math (no EnergyPlus)."""

from __future__ import annotations

from bridge.clamps import clamp_cooling, clamp_heating, clamp_lighting


def test_inv1_cooling_hard_cap():
    applied, events, _ = clamp_cooling(35.0, occupied=True, last=24.0)
    # first range clamp to 26, then ramp from 24 -> 26 is exactly 2 OK
    assert applied == 26.0
    assert any(e.rule == "INV-1" for e in events)


def test_inv1_unoccupied_allows_28():
    applied, events, _ = clamp_cooling(28.0, occupied=False, last=26.0)
    assert applied == 28.0


def test_inv4_ramp_limit():
    # last=22, request 28 occupied -> range clamps to 26, then ramp 22->24
    applied, events, _ = clamp_cooling(28.0, occupied=True, last=22.0)
    assert applied == 24.0
    assert any(e.rule == "INV-4" for e in events)


def test_inv3_deadband():
    heat, events = clamp_heating(
        25.0, occupied=True, last=20.0, cooling_applied=24.0
    )
    # heating max = 24 - 1 = 23; also INV-2 may clamp 25->24 first
    assert heat <= 23.0
    assert any(e.rule in ("INV-2", "INV-3") for e in events)


def test_inv5_occupied_lights_floor():
    level, events = clamp_lighting(0.0, occupied=True)
    assert level == 0.3
    assert any(e.rule == "INV-5" for e in events)


def test_inv5_unoccupied_allows_off():
    level, events = clamp_lighting(0.0, occupied=False)
    assert level == 0.0
    assert events == []


def test_heating_25_cooling_24_deadband():
    # classic plan case: heating 25 + cooling 24 -> deadband enforced
    cool, _, _ = clamp_cooling(24.0, occupied=True, last=24.0)
    heat, events = clamp_heating(25.0, occupied=True, last=20.0, cooling_applied=cool)
    assert cool == 24.0
    assert heat <= cool - 1.0
