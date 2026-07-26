"""
memory.py — rolling window of recent agent decisions.

Job: Injected into every LLM prompt so the agent knows what it decided in
the last 3 timesteps. Prevents oscillation and makes the ramp-rate
constraint (max 2°C/step) followable. Without this the agent is stateless.

Build: Phase 3e. Pure Python — unit test with no simulator.
"""

from __future__ import annotations

from collections import deque


class AgentMemory:
    """Fixed-size window of past decisions, rendered as a prompt block."""

    def __init__(self, window: int = 3) -> None:
        self.decisions: deque[dict] = deque(maxlen=window)

    def append(self, timestep: int, summary: str, actions: list[dict]) -> None:
        self.decisions.append(
            {"timestep": timestep, "summary": summary, "actions": actions}
        )

    def render(self) -> str:
        """Formatted memory block for the timestep prompt."""
        if not self.decisions:
            return "No prior decisions (first timestep)."
        lines = []
        for d in self.decisions:
            lines.append(f"T{d['timestep']}: {d['summary']}")
        return "\n".join(lines)
