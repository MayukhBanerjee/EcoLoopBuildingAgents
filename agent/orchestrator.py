"""
orchestrator.py — closed-loop control heartbeat.

Called every non-warmup EnergyPlus timestep via EPRunner callback:
  1. EPReader  → SensorReading
  2. Seed EPWriter ramp baseline from first-step sensor data
  3. Assemble prompt (memory + grid context + sensors)
  4. LLMClient → response with tool_calls
  5. ToolExecutor → execute each tool call; accumulate ControlAction
  6. EPWriter.apply()  → inject clamped setpoints into EnergyPlus
  7. Log decision to JSONL  (data/agent/<run_id>/decisions.jsonl)
  8. AgentMemory.append()
  9. On LLMUnavailable → fallback.safe_action()

The agent calls the LLM every AGENT_EVERY_N_STEPS timesteps (default 1).
Each LLM round supports up to MAX_TOOL_ROUNDS tool-call iterations so the
agent can: read → report → set per-zone → predict → set again.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from agent.grid import carbon_intensity, intensity_label, peak_status
from agent.llm_client import LLMClient, LLMUnavailable
from agent.memory import AgentMemory
from agent.prompts import SYSTEM_PROMPT, build_timestep_prompt
from agent.tools import ToolExecutor
from bridge.fallback import safe_action

logger = logging.getLogger("EcoLoop.agent.orchestrator")

# Maximum tool-call rounds per timestep (prevents runaway loops)
MAX_TOOL_ROUNDS = 6


class EcoLoopOrchestrator:
    """Main closed-loop control orchestrator."""

    def __init__(
        self,
        reader: Any,
        writer: Any,
        llm: LLMClient,
        *,
        baseline_kwh: float | None = None,
        run_id: str | None = None,
        agent_every_n_steps: int | None = None,
    ) -> None:
        self.reader = reader
        self.writer = writer
        self.llm = llm
        self.baseline_kwh = baseline_kwh
        self.memory = AgentMemory(window=3)
        self.timestep = 0
        self.decision_log: list[dict[str, Any]] = []
        self._seeded = False

        # How often to invoke the LLM (1 = every timestep, 4 = once per hour)
        env_n = int(os.getenv("AGENT_EVERY_N_STEPS", "1"))
        self._every_n = agent_every_n_steps if agent_every_n_steps is not None else env_n
        self._every_n = max(1, self._every_n)

        # JSONL decision log path
        run_tag = run_id or time.strftime("%Y%m%d_%H%M%S")
        self._log_dir = Path("data/agent") / run_tag
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._log_path = self._log_dir / "decisions.jsonl"
        logger.info(
            "Orchestrator ready. every_n=%d log=%s", self._every_n, self._log_path
        )

    # ------------------------------------------------------------------
    # Timestep callback (called by EPRunner)
    # ------------------------------------------------------------------

    def step(self, state: Any) -> None:
        """Called by EnergyPlus at every non-warmup zone timestep."""
        self.timestep += 1

        # --- 1. Read sensors ---
        reading = self.reader.read(self.timestep)
        # Stash on reader so ToolExecutor can access it without a direct ref
        self.reader._latest_reading = reading

        # --- 2. Seed writer ramp baseline on first real timestep ---
        if not self._seeded:
            self.writer.seed_from_sensors(reading.cooling_setpoints, reading.heating_setpoints)
            self._seeded = True

        # --- 3. Skip LLM call if not on schedule ---
        if (self.timestep - 1) % self._every_n != 0:
            return

        # --- 4. Build context for LLM ---
        sim_minute_total = (self.timestep - 1) * 15  # 15-min timesteps
        sim_hour = (sim_minute_total // 60) % 24
        sim_minute = sim_minute_total % 60

        step_kw = (reading.energy_step_j / 3_600_000.0) * 4.0
        threshold_kw = float(os.getenv("PEAK_DEMAND_THRESHOLD_KW", "55.0"))
        grid_ctx = {
            "g_per_kwh": carbon_intensity(sim_hour),
            "label": intensity_label(sim_hour),
            "peak_status": peak_status(step_kw),
            "demand_kw": round(step_kw, 2),
            "threshold_kw": threshold_kw,
        }

        memory_block = self.memory.render()
        sensor_compact = reading.to_compact()
        user_prompt = build_timestep_prompt(
            sensor_compact,
            grid_ctx,
            memory_block,
            timestep=self.timestep,
            sim_hour=sim_hour,
            sim_minute=sim_minute,
        )

        # --- 5. Tool-calling loop ---
        tool_executor = ToolExecutor(
            self.reader,
            self.writer,
            sim_hour=sim_hour,
            baseline_kwh=self.baseline_kwh,
        )
        tool_defs = tool_executor.get_tool_definitions()
        messages: list[dict[str, Any]] = [{"role": "user", "content": user_prompt}]
        recorded_tool_calls: list[dict[str, Any]] = []
        reasoning_text = ""
        fallback_used = False

        try:
            for _round in range(MAX_TOOL_ROUNDS):
                resp = self.llm.run_with_tools(SYSTEM_PROMPT, messages, tool_defs)
                msg = resp.choices[0].message

                # Capture reasoning from text content
                if msg.content:
                    reasoning_text = str(msg.content).strip()

                # No tool calls → agent is done deciding
                if not msg.tool_calls:
                    break

                # Execute all tool calls in this round
                tool_results: list[dict[str, Any]] = []
                for tc in msg.tool_calls:
                    name = tc.function.name if hasattr(tc, "function") else tc.get("function", {}).get("name", "")
                    raw_args = tc.function.arguments if hasattr(tc, "function") else tc.get("function", {}).get("arguments", "{}")
                    try:
                        args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                    except json.JSONDecodeError:
                        args = {}

                    result = tool_executor.execute(name, args)
                    recorded_tool_calls.append({"tool": name, "args": args, "result": result})
                    tool_results.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.id if hasattr(tc, "id") else f"tc_{_round}",
                            "content": json.dumps(result, default=str),
                        }
                    )

                # Feed tool results back into conversation
                messages.append(
                    {
                        "role": "assistant",
                        "content": msg.content,
                        "tool_calls": [
                            {
                                "id": tc.id if hasattr(tc, "id") else f"tc_{_round}",
                                "type": "function",
                                "function": {
                                    "name": (tc.function.name if hasattr(tc, "function") else tc.get("function", {}).get("name", "")),
                                    "arguments": (tc.function.arguments if hasattr(tc, "function") else tc.get("function", {}).get("arguments", "{}")),
                                },
                            }
                            for tc in msg.tool_calls
                        ],
                    }
                )
                messages.extend(tool_results)

        except LLMUnavailable as exc:
            logger.warning("LLM unavailable at T%d: %s. Applying fallback.", self.timestep, exc)
            tool_executor.pending_action = safe_action()
            fallback_used = True
            reasoning_text = f"[FALLBACK] LLM unavailable: {exc}"

        # --- 6. Apply accumulated control action ---
        clamp_events = self.writer.apply(
            tool_executor.pending_action,
            occupancy=reading.occupancy,
        )

        # --- 7. Build decision log entry ---
        actions_summary = [
            {
                "zone": zone,
                "cooling_setpoint": tool_executor.pending_action.cooling_setpoints.get(zone),
                "heating_setpoint": tool_executor.pending_action.heating_setpoints.get(zone),
                "lighting_level": tool_executor.pending_action.lighting_levels.get(zone),
            }
            for zone in sorted(
                set(tool_executor.pending_action.cooling_setpoints)
                | set(tool_executor.pending_action.heating_setpoints)
                | set(tool_executor.pending_action.lighting_levels)
            )
        ]
        actions_summary = [
            {k: v for k, v in a.items() if v is not None}
            for a in actions_summary
        ]

        clamp_summary = [
            {"zone": e.zone, "field": e.field, "rule": e.rule, "req": round(e.requested, 2), "applied": round(e.applied, 2)}
            for e in clamp_events
        ]

        entry: dict[str, Any] = {
            "timestep": self.timestep,
            "sim_hour": sim_hour,
            "sim_minute": sim_minute,
            "fallback_used": fallback_used,
            "energy_kwh": round(reading.energy_consumption_kwh, 3),
            "demand_kw": round(step_kw, 2),
            "grid_label": grid_ctx["label"],
            "peak_status": grid_ctx["peak_status"],
            "reasoning": reasoning_text,
            "tool_calls": recorded_tool_calls,
            "actions_applied": actions_summary,
            "clamp_events": clamp_summary,
            "tokens_used_total": self.llm.total_tokens,
        }
        self.decision_log.append(entry)
        self._write_log_entry(entry)

        # --- 8. Update memory ---
        short_summary = reasoning_text[:120] if reasoning_text else "no reasoning"
        self.memory.append(
            timestep=self.timestep,
            summary=short_summary,
            actions=actions_summary,
            energy_kwh=reading.energy_consumption_kwh,
            fallback_used=fallback_used,
        )

        logger.info(
            "T%d %02d:%02d | energy=%.3f kWh | demand=%.1f kW | grid=%s | "
            "actions=%d | clamps=%d | fallback=%s",
            self.timestep,
            sim_hour,
            sim_minute,
            reading.energy_consumption_kwh,
            step_kw,
            grid_ctx["label"],
            len(actions_summary),
            len(clamp_events),
            fallback_used,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _write_log_entry(self, entry: dict[str, Any]) -> None:
        """Append one JSONL line (flush immediately for crash safety)."""
        try:
            with self._log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, default=str) + "\n")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to write decision log: %s", exc)

    def save_summary(self) -> Path:
        """Write run-level summary JSON next to the decision log."""
        if not self.decision_log:
            logger.warning("No decisions logged; skipping summary.")
            return self._log_path.parent / "summary.json"

        total_steps = len(self.decision_log)
        fallback_count = sum(1 for d in self.decision_log if d["fallback_used"])
        total_clamps = sum(len(d["clamp_events"]) for d in self.decision_log)
        final_kwh = self.decision_log[-1]["energy_kwh"]
        savings_kwh = (self.baseline_kwh or 0) - final_kwh
        savings_pct = (savings_kwh / self.baseline_kwh * 100.0) if self.baseline_kwh else 0.0

        summary = {
            "run_id": self._log_dir.name,
            "total_timesteps": total_steps,
            "llm_calls": self.llm.total_calls,
            "total_tokens": self.llm.total_tokens,
            "fallback_count": fallback_count,
            "total_clamp_events": total_clamps,
            "baseline_kwh": round(self.baseline_kwh or 0, 3),
            "agent_final_kwh": round(final_kwh, 3),
            "savings_kwh": round(savings_kwh, 3),
            "savings_pct": round(savings_pct, 1),
        }

        summary_path = self._log_dir / "summary.json"
        summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        logger.info("Run summary saved to %s", summary_path)
        logger.info(
            "RESULT: baseline=%.2f kWh | agent=%.2f kWh | savings=%.2f kWh (%.1f%%)",
            self.baseline_kwh or 0,
            final_kwh,
            savings_kwh,
            savings_pct,
        )
        return summary_path
