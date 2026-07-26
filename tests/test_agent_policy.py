"""
tests/test_agent_policy.py — adaptive policy correctness.
"""

from __future__ import annotations

from types import SimpleNamespace

from agent.policy import policy_action
from bridge.constants import CONTROLLED_ZONES, COOL_UNOCC_MAX, HEAT_UNOCC_MIN


def _reading(*, temps: dict[str, float], occ: dict[str, int]) -> SimpleNamespace:
    return SimpleNamespace(zone_temperatures=temps, occupancy=occ)


class TestAdaptivePolicy:
    def test_all_unoccupied_deep_setback(self) -> None:
        reading = _reading(
            temps={z: 22.0 for z in CONTROLLED_ZONES},
            occ={z: 0 for z in CONTROLLED_ZONES},
        )
        action = policy_action(reading)
        for z in CONTROLLED_ZONES:
            assert action.cooling_setpoints[z] == COOL_UNOCC_MAX
            assert action.heating_setpoints[z] == HEAT_UNOCC_MIN
            assert action.lighting_levels[z] == 0.0

    def test_occupied_uses_comfort_edge(self) -> None:
        reading = _reading(
            temps={z: 23.0 for z in CONTROLLED_ZONES},
            occ={z: 2 for z in CONTROLLED_ZONES},
        )
        action = policy_action(reading)
        for z in CONTROLLED_ZONES:
            assert action.cooling_setpoints[z] == 25.0
            assert action.heating_setpoints[z] == 20.0
            assert z not in action.lighting_levels  # leave occupied lights alone

    def test_mixed_occupancy(self) -> None:
        occ = {z: 0 for z in CONTROLLED_ZONES}
        occ["SPACE1-1"] = 3
        reading = _reading(temps={z: 23.0 for z in CONTROLLED_ZONES}, occ=occ)
        action = policy_action(reading)
        assert action.cooling_setpoints["SPACE1-1"] == 25.0
        assert action.lighting_levels["SPACE2-1"] == 0.0
        assert "SPACE1-1" not in action.lighting_levels

    def test_too_warm_occupied_lowers_cooling(self) -> None:
        # 28 C → PMV > 0.5 for clo=0.7
        reading = _reading(
            temps={z: 28.0 for z in CONTROLLED_ZONES},
            occ={z: 1 for z in CONTROLLED_ZONES},
        )
        action = policy_action(reading)
        assert action.cooling_setpoints["SPACE1-1"] == 24.0
