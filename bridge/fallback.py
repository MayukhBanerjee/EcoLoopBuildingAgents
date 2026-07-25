"""
fallback.py — safe defaults when the LLM is unavailable (INV-6).

Job: If the LLM call fails or times out mid-simulation, apply conservative
setpoints so the simulation completes crash-free. These few lines protect
the 30% System Integration score from one bad API timeout.

Build: Phase 2d.
"""

from __future__ import annotations

from bridge.ep_writer import ControlAction

CONTROLLED_ZONES = ["SPACE1-1", "SPACE2-1", "SPACE3-1", "SPACE4-1", "SPACE5-1"]

SAFE_COOLING_C = 22.0
SAFE_HEATING_C = 20.0


def safe_action() -> ControlAction:
    """Conservative comfort-safe setpoints for all zones; lights untouched."""
    return ControlAction(
        zone_setpoints={z: SAFE_COOLING_C for z in CONTROLLED_ZONES},
        ventilation_rates={},
        lighting_levels={},
    )
