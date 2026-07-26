"""
fallback.py — safe defaults when the LLM is unavailable (INV-6).

Protects the 30% System Integration score from one bad API timeout.
"""

from __future__ import annotations

from bridge.constants import CONTROLLED_ZONES
from bridge.ep_writer import ControlAction

SAFE_COOLING_C = 22.0
SAFE_HEATING_C = 20.0


def safe_action() -> ControlAction:
    """Conservative comfort-safe setpoints for all zones; lights untouched."""
    return ControlAction(
        cooling_setpoints={z: SAFE_COOLING_C for z in CONTROLLED_ZONES},
        heating_setpoints={z: SAFE_HEATING_C for z in CONTROLLED_ZONES},
        lighting_levels={},
        ventilation_rates={},
    )
