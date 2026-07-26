"""
memory.py — rolling window of recent agent decisions.

Injected into every LLM timestep prompt so the agent can:
  - track what setpoints it applied previously (no oscillation)
  - verify whether the building responded as expected
  - observe the ramp constraint (max 2 °C/timestep)

Pure Python — no simulator required.
"""

from __future__ import annotations

from collections import deque
from typing import Any


class AgentMemory:
    """Fixed-size window of past decisions rendered as a prompt block."""

    def __init__(self, window: int = 3) -> None:
        self._window = window
        self.decisions: deque[dict[str, Any]] = deque(maxlen=window)

    def append(
        self,
        *,
        timestep: int,
        summary: str,
        actions: list[dict[str, Any]],
        energy_kwh: float = 0.0,
        fallback_used: bool = False,
    ) -> None:
        """Record one timestep decision."""
        self.decisions.append(
            {
                "timestep": timestep,
                "summary": summary,
                "actions": actions,
                "energy_kwh": round(energy_kwh, 3),
                "fallback_used": fallback_used,
            }
        )

    def render(self) -> str:
        """Formatted memory block injected into the timestep prompt.

        Example output::

            --- Recent decisions (last 3 timesteps) ---
            T4 | Energy: 12.3 kWh | SPACE1-1 cool=24.0 heat=20.0 light=0.8
               | SPACE2-1 cool=25.0 heat=20.0 (unoccupied — relaxed)
               | Summary: reduced lighting in unoccupied zones
            T3 | Energy: 9.1 kWh | SPACE1-1 cool=24.0 heat=20.0 light=0.8
               | Summary: baseline setpoints
        """
        if not self.decisions:
            return "No prior decisions (first timestep)."

        lines = [f"--- Recent decisions (last {self._window} timesteps) ---"]
        for d in reversed(self.decisions):
            ts = d["timestep"]
            energy = d["energy_kwh"]
            fb = " [FALLBACK]" if d["fallback_used"] else ""
            action_parts: list[str] = []
            for act in d["actions"]:
                zone = act.get("zone", "?")
                parts = []
                if "cooling_setpoint" in act:
                    parts.append(f"cool={act['cooling_setpoint']:.1f}")
                if "heating_setpoint" in act:
                    parts.append(f"heat={act['heating_setpoint']:.1f}")
                if "lighting_level" in act:
                    parts.append(f"light={act['lighting_level']:.2f}")
                action_parts.append(f"{zone}: {' '.join(parts)}")
            actions_str = " | ".join(action_parts) if action_parts else "no control actions"
            lines.append(
                f"T{ts}{fb} | energy_cum={energy:.3f} kWh | {actions_str}"
            )
            if d["summary"]:
                lines.append(f"   reasoning: {d['summary']}")
        return "\n".join(lines)

    def last_setpoints(self) -> dict[str, dict[str, float]]:
        """Return {zone: {cooling_setpoint, heating_setpoint}} from most recent decision."""
        if not self.decisions:
            return {}
        last = self.decisions[-1]
        result: dict[str, dict[str, float]] = {}
        for act in last.get("actions", []):
            zone = act.get("zone")
            if zone:
                result[zone] = {
                    k: v
                    for k, v in act.items()
                    if k in ("cooling_setpoint", "heating_setpoint", "lighting_level")
                }
        return result
