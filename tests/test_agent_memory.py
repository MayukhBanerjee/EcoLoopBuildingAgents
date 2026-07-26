"""
tests/test_agent_memory.py — AgentMemory window and render correctness.
"""

from __future__ import annotations

from agent.memory import AgentMemory


class TestAgentMemory:
    def test_empty_render(self) -> None:
        m = AgentMemory()
        out = m.render()
        assert "first timestep" in out.lower()

    def test_append_and_render_contains_timestep(self) -> None:
        m = AgentMemory(window=3)
        m.append(
            timestep=5,
            summary="reduced lighting",
            actions=[{"zone": "SPACE1-1", "cooling_setpoint": 24.0}],
            energy_kwh=12.5,
        )
        out = m.render()
        assert "T5" in out
        assert "12.5" in out

    def test_window_evicts_oldest(self) -> None:
        m = AgentMemory(window=2)
        for i in range(5):
            m.append(timestep=i, summary=f"step {i}", actions=[], energy_kwh=float(i))
        assert len(m.decisions) == 2
        timesteps = [d["timestep"] for d in m.decisions]
        assert 3 in timesteps
        assert 4 in timesteps
        assert 0 not in timesteps

    def test_fallback_flag_shown(self) -> None:
        m = AgentMemory()
        m.append(
            timestep=1,
            summary="fallback",
            actions=[],
            energy_kwh=5.0,
            fallback_used=True,
        )
        out = m.render()
        assert "FALLBACK" in out

    def test_last_setpoints_empty_on_no_actions(self) -> None:
        m = AgentMemory()
        m.append(timestep=1, summary="idle", actions=[], energy_kwh=0.0)
        assert m.last_setpoints() == {}

    def test_last_setpoints_populated(self) -> None:
        m = AgentMemory()
        m.append(
            timestep=2,
            summary="tuned",
            actions=[
                {"zone": "SPACE1-1", "cooling_setpoint": 23.0, "heating_setpoint": 20.0}
            ],
        )
        sp = m.last_setpoints()
        assert sp["SPACE1-1"]["cooling_setpoint"] == 23.0

    def test_multiple_appends_render_all(self) -> None:
        m = AgentMemory(window=3)
        for i in range(3):
            m.append(timestep=i + 1, summary=f"step {i + 1}", actions=[], energy_kwh=float(i))
        out = m.render()
        for i in range(1, 4):
            assert f"T{i}" in out
