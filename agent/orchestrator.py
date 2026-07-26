"""
orchestrator.py — closed-loop control heartbeat (Phase 4).

Every non-warmup EnergyPlus timestep:
  read → (optional LLM) → tools → clamp/apply → JSONL flush → memory

INV-6/7: any failure inside step() applies fallback.safe_action() and never
propagates into EnergyPlus (EPRunner also swallows exceptions).
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from agent.artifacts import write_actuator_timeline, write_runtime_final_state_idf
from agent.grid import carbon_intensity, intensity_label, peak_status
from agent.llm_client import LLMClient, LLMUnavailable
from agent.memory import AgentMemory
from agent.policy import describe_policy_action, policy_action
from agent.prompts import (
    SYSTEM_PROMPT,
    build_action_nudge_prompt,
    build_timestep_prompt,
)
from agent.stream import ACT, CLAMP, PROMPT, SENSE, TOOL, StreamBus
from agent.tools import ToolExecutor
from bridge.constants import CONTROLLED_ZONES
from bridge.fallback import safe_action
from bridge.ep_writer import ControlAction

logger = logging.getLogger("EcoLoop.agent.orchestrator")

# Maximum tool-call rounds per timestep (prevents runaway loops)
def _max_tool_rounds() -> int:
    return max(1, int(os.getenv("AGENT_MAX_TOOL_ROUNDS", "4")))


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
        output_dir: str | Path | None = None,
        source_idf: str | Path | None = None,
        stream: StreamBus | None = None,
    ) -> None:
        self.reader = reader
        self.writer = writer
        self.llm = llm
        self.baseline_kwh = baseline_kwh
        self.memory = AgentMemory(window=3)
        self.stream = stream or StreamBus()
        self.timestep = 0
        self.decision_log: list[dict[str, Any]] = []
        self.actuator_timeline: list[dict[str, Any]] = []
        self._seeded = False
        self._last_action = ControlAction()
        self.source_idf = Path(source_idf) if source_idf else None

        env_n = int(os.getenv("AGENT_EVERY_N_STEPS", "1"))
        self._every_n = agent_every_n_steps if agent_every_n_steps is not None else env_n
        self._every_n = max(1, self._every_n)

        run_tag = run_id or time.strftime("%Y%m%d_%H%M%S")
        if output_dir is not None:
            self._log_dir = Path(output_dir)
        else:
            self._log_dir = Path("data/agent_results") / run_tag
        self._log_dir.mkdir(parents=True, exist_ok=True)
        # Plan name + alias for compatibility
        self._log_path = self._log_dir / "agent_decisions.jsonl"
        self._log_alias = self._log_dir / "decisions.jsonl"
        self.run_id = run_tag
        logger.info(
            "Orchestrator ready. every_n=%d log=%s", self._every_n, self._log_path
        )

    # ------------------------------------------------------------------
    # Timestep callback
    # ------------------------------------------------------------------

    def step(self, state: Any) -> None:
        """Called by EnergyPlus at every non-warmup zone timestep."""
        self.timestep += 1
        try:
            self._step_inner(state)
        except Exception as exc:  # noqa: BLE001 — INV-6/7 never abort EP
            logger.exception("Orchestrator step failed at T%d: %s", self.timestep, exc)
            try:
                reading = getattr(self.reader, "_latest_reading", None)
                occ = reading.occupancy if reading is not None else {}
                action = policy_action(reading) if reading is not None else safe_action()
                events = self.writer.apply(action, occupancy=occ)
                sim_minute_total = (self.timestep - 1) * 15
                self._publish_apply(
                    sim_hour=(sim_minute_total // 60) % 24,
                    sim_minute=sim_minute_total % 60,
                    action=action,
                    clamp_events=events,
                    fallback=True,
                    held=False,
                )
                self._record_fallback_entry(
                    reasoning=(
                        f"[FALLBACK] Unhandled error: {exc}. "
                        f"Adaptive policy applied."
                    ),
                    clamp_events=events,
                    reading=reading,
                    action=action,
                )
            except Exception:  # noqa: BLE001
                logger.exception("Fallback apply also failed at T%d", self.timestep)

    def _step_inner(self, state: Any) -> None:
        # 1. Read sensors
        reading = self.reader.read(self.timestep)
        self.reader._latest_reading = reading

        # 2. Seed ramp baselines once
        if not self._seeded:
            self.writer.seed_from_sensors(
                reading.cooling_setpoints, reading.heating_setpoints
            )
            self._seeded = True

        sim_minute_total = (self.timestep - 1) * 15
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

        # 3. Cadence throttle — hold last setpoints between LLM decisions
        sensor_compact_early = reading.to_compact()
        self.stream.publish(
            timestep=self.timestep,
            stage=SENSE,
            sim_hour=sim_hour,
            sim_minute=sim_minute,
            outdoor_temp=sensor_compact_early.get("outdoor_temp"),
            energy_kwh_cum=sensor_compact_early.get("energy_kwh_cum"),
            demand_kw=round(step_kw, 2),
            grid_label=grid_ctx["label"],
            peak_status=grid_ctx["peak_status"],
            zones=sensor_compact_early.get("zones", {}),
        )

        if (self.timestep - 1) % self._every_n != 0:
            # Re-apply last action so actuators stay owned between LLM calls
            if self._has_actions(self._last_action):
                events = self.writer.apply(self._last_action, occupancy=reading.occupancy)
                self._append_timeline(
                    self._last_action, sim_hour, sim_minute, fallback=False
                )
            else:
                events = []
            self._record_entry(
                reading=reading,
                sim_hour=sim_hour,
                sim_minute=sim_minute,
                step_kw=step_kw,
                grid_ctx=grid_ctx,
                reasoning="[HOLD] Between LLM cadence steps — holding last setpoints.",
                tool_calls=[],
                action=self._last_action,
                clamp_events=events,
                fallback_used=False,
                held=True,
            )
            self._publish_apply(
                sim_hour=sim_hour,
                sim_minute=sim_minute,
                action=self._last_action,
                clamp_events=events,
                fallback=False,
                held=True,
            )
            return

        # 4. Build prompt
        user_prompt = build_timestep_prompt(
            reading.to_compact(),
            grid_ctx,
            self.memory.render(),
            timestep=self.timestep,
            sim_hour=sim_hour,
            sim_minute=sim_minute,
        )
        # 5. Tool-calling loop (+ one action-nudge if LLM only observes)
        tool_executor = ToolExecutor(
            self.reader,
            self.writer,
            sim_hour=sim_hour,
            baseline_kwh=self.baseline_kwh,
        )
        tool_defs = tool_executor.get_tool_definitions()

        self.stream.publish(
            timestep=self.timestep,
            stage=PROMPT,
            sim_hour=sim_hour,
            sim_minute=sim_minute,
            model=getattr(self.llm, "model", "?"),
            prompt_chars=len(user_prompt) + len(SYSTEM_PROMPT),
            est_tokens=(len(user_prompt) + len(SYSTEM_PROMPT)) // 4,
            cadence=f"LLM every {self._every_n} step(s)",
            tools_offered=len(tool_defs),
            preview=self._prompt_preview(reading.to_compact()),
        )

        messages: list[dict[str, Any]] = [{"role": "user", "content": user_prompt}]
        recorded_tool_calls: list[dict[str, Any]] = []
        reasoning_text = ""
        fallback_used = False
        nudged = False
        sensor_compact = reading.to_compact()

        try:
            rounds = _max_tool_rounds()
            for _round in range(rounds):
                resp = self.llm.run_with_tools(SYSTEM_PROMPT, messages, tool_defs)
                self._ingest_llm_message(
                    resp.choices[0].message,
                    tool_executor,
                    messages,
                    recorded_tool_calls,
                    round_id=_round,
                )
                msg = resp.choices[0].message
                if msg.content:
                    reasoning_text = str(msg.content).strip()
                if not msg.tool_calls:
                    break
                # Stop early once we have real control actions queued
                if self._has_actions(tool_executor.pending_action):
                    break

            # Nudge: LLM observed but never wrote → one corrective round
            if not self._has_actions(tool_executor.pending_action):
                nudged = True
                logger.info(
                    "T%d: no control tools from LLM — firing action nudge.",
                    self.timestep,
                )
                nudge = build_action_nudge_prompt(
                    sensor_compact, timestep=self.timestep
                )
                messages.append({"role": "user", "content": nudge})
                resp = self.llm.run_with_tools(SYSTEM_PROMPT, messages, tool_defs)
                self._ingest_llm_message(
                    resp.choices[0].message,
                    tool_executor,
                    messages,
                    recorded_tool_calls,
                    round_id=rounds,
                )
                if resp.choices[0].message.content:
                    reasoning_text = (
                        (reasoning_text + "\n") if reasoning_text else ""
                    ) + str(resp.choices[0].message.content).strip()

        except LLMUnavailable as exc:
            logger.warning(
                "LLM unavailable at T%d: %s. Applying adaptive policy.",
                self.timestep,
                exc,
            )
            tool_executor.pending_action = policy_action(reading)
            fallback_used = True
            reasoning_text = (
                f"[FALLBACK] LLM unavailable: {exc}. "
                f"Adaptive policy: {describe_policy_action(tool_executor.pending_action, reading.occupancy)}"
            )

        action = tool_executor.pending_action
        # Still no writes after nudge → adaptive occupancy-aware policy (not static 22/20)
        if not self._has_actions(action):
            action = policy_action(reading)
            tag = "[NUDGE-MISS]" if nudged else "[AUTO]"
            if not fallback_used:
                reasoning_text = (
                    (reasoning_text + "\n") if reasoning_text else ""
                ) + (
                    f"{tag} No control tools called — applying adaptive policy: "
                    f"{describe_policy_action(action, reading.occupancy)}"
                )

        if fallback_used:
            decided_by = "adaptive policy (LLM unavailable)"
        elif not recorded_tool_calls:
            decided_by = "adaptive policy (no tool calls)"
        else:
            decided_by = f"LLM {getattr(self.llm, 'model', '')}".strip()

        self.stream.publish(
            timestep=self.timestep,
            stage=TOOL,
            sim_hour=sim_hour,
            sim_minute=sim_minute,
            tool_calls=[
                {"tool": tc.get("tool"), "args": tc.get("args")}
                for tc in recorded_tool_calls
            ],
            tokens=getattr(self.llm, "total_tokens", None),
            source=decided_by,
            nudged=nudged,
            fallback=fallback_used,
            reasoning=reasoning_text,
        )

        # 6. Apply
        clamp_events = self.writer.apply(action, occupancy=reading.occupancy)
        self._last_action = action
        self._append_timeline(action, sim_hour, sim_minute, fallback=fallback_used)
        self._publish_apply(
            sim_hour=sim_hour,
            sim_minute=sim_minute,
            action=action,
            clamp_events=clamp_events,
            fallback=fallback_used,
            held=False,
        )

        # 7–8. Log + memory
        self._record_entry(
            reading=reading,
            sim_hour=sim_hour,
            sim_minute=sim_minute,
            step_kw=step_kw,
            grid_ctx=grid_ctx,
            reasoning=reasoning_text,
            tool_calls=recorded_tool_calls,
            action=action,
            clamp_events=clamp_events,
            fallback_used=fallback_used,
            held=False,
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
            len(action.cooling_setpoints)
            + len(action.heating_setpoints)
            + len(action.lighting_levels),
            len(clamp_events),
            fallback_used,
        )

    # ------------------------------------------------------------------
    # Logging helpers
    # ------------------------------------------------------------------

    def _ingest_llm_message(
        self,
        msg: Any,
        tool_executor: ToolExecutor,
        messages: list[dict[str, Any]],
        recorded_tool_calls: list[dict[str, Any]],
        *,
        round_id: int,
    ) -> None:
        """Execute tool_calls on msg (if any) and append them to the conversation."""
        if not msg.tool_calls:
            return

        tool_results: list[dict[str, Any]] = []
        openai_tool_calls: list[dict[str, Any]] = []
        for i, tc in enumerate(msg.tool_calls):
            name = (
                tc.function.name
                if hasattr(tc, "function")
                else tc.get("function", {}).get("name", "")
            )
            raw_args = (
                tc.function.arguments
                if hasattr(tc, "function")
                else tc.get("function", {}).get("arguments", "{}")
            )
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
            except json.JSONDecodeError:
                args = {}

            result = tool_executor.execute(name, args)
            recorded_tool_calls.append({"tool": name, "args": args, "result": result})
            tc_id = tc.id if hasattr(tc, "id") else f"tc_{round_id}_{i}"
            tool_results.append(
                {
                    "role": "tool",
                    "tool_call_id": tc_id,
                    "content": json.dumps(result, default=str),
                }
            )
            openai_tool_calls.append(
                {
                    "id": tc_id,
                    "type": "function",
                    "function": {
                        "name": name,
                        "arguments": raw_args if isinstance(raw_args, str) else json.dumps(raw_args),
                    },
                }
            )

        messages.append(
            {
                "role": "assistant",
                "content": msg.content,
                "tool_calls": openai_tool_calls,
            }
        )
        messages.extend(tool_results)

    @staticmethod
    def _has_actions(action: ControlAction) -> bool:
        return bool(
            action.cooling_setpoints
            or action.heating_setpoints
            or action.lighting_levels
        )

    @staticmethod
    def _prompt_preview(sensor_compact: dict[str, Any]) -> str:
        """Two-line digest of what the model was shown (terminal/UI display only)."""
        zones = sensor_compact.get("zones") or {}
        empty = [z for z, zd in zones.items() if int(zd.get("occ", 0) or 0) <= 0]
        occupied = [z for z, zd in zones.items() if int(zd.get("occ", 0) or 0) > 0]
        lines = [
            f"sensor snapshot: {len(zones)} zones, "
            f"{len(occupied)} occupied, {len(empty)} empty"
        ]
        if empty:
            lines.append(f"setback candidates: {', '.join(empty)}")
        return "\n".join(lines)

    def _publish_apply(
        self,
        *,
        sim_hour: int,
        sim_minute: int,
        action: ControlAction,
        clamp_events: list[Any],
        fallback: bool,
        held: bool,
    ) -> None:
        """Emit the CLAMP + ACT stages for one timestep."""
        self.stream.publish(
            timestep=self.timestep,
            stage=CLAMP,
            sim_hour=sim_hour,
            sim_minute=sim_minute,
            clamp_events=[
                {
                    "zone": e.zone,
                    "field": e.field,
                    "rule": e.rule,
                    "req": round(e.requested, 2),
                    "applied": round(e.applied, 2),
                }
                for e in clamp_events
            ],
        )
        self.stream.publish(
            timestep=self.timestep,
            stage=ACT,
            sim_hour=sim_hour,
            sim_minute=sim_minute,
            actions=self._actions_summary(action),
            fallback=fallback,
            held=held,
        )

    def _actions_summary(self, action: ControlAction) -> list[dict[str, Any]]:
        zones = sorted(
            set(action.cooling_setpoints)
            | set(action.heating_setpoints)
            | set(action.lighting_levels)
        )
        rows: list[dict[str, Any]] = []
        for zone in zones:
            row: dict[str, Any] = {"zone": zone}
            if zone in action.cooling_setpoints:
                row["cooling_setpoint"] = action.cooling_setpoints[zone]
            if zone in action.heating_setpoints:
                row["heating_setpoint"] = action.heating_setpoints[zone]
            if zone in action.lighting_levels:
                row["lighting_level"] = action.lighting_levels[zone]
            rows.append(row)
        return rows

    def _append_timeline(
        self,
        action: ControlAction,
        sim_hour: int,
        sim_minute: int,
        *,
        fallback: bool,
    ) -> None:
        for zone in CONTROLLED_ZONES:
            cool = action.cooling_setpoints.get(zone, self.writer.last_cooling.get(zone))
            heat = action.heating_setpoints.get(zone, self.writer.last_heating.get(zone))
            light = action.lighting_levels.get(zone)
            if cool is None and heat is None and light is None:
                continue
            self.actuator_timeline.append(
                {
                    "timestep": self.timestep,
                    "sim_hour": sim_hour,
                    "sim_minute": sim_minute,
                    "zone": zone,
                    "cooling_c": "" if cool is None else round(float(cool), 2),
                    "heating_c": "" if heat is None else round(float(heat), 2),
                    "lights_fraction": "" if light is None else round(float(light), 3),
                    "fallback": fallback,
                }
            )

    def _record_entry(
        self,
        *,
        reading: Any,
        sim_hour: int,
        sim_minute: int,
        step_kw: float,
        grid_ctx: dict[str, Any],
        reasoning: str,
        tool_calls: list[dict[str, Any]],
        action: ControlAction,
        clamp_events: list[Any],
        fallback_used: bool,
        held: bool,
    ) -> None:
        actions_summary = self._actions_summary(action)
        clamp_summary = [
            {
                "zone": e.zone,
                "field": e.field,
                "rule": e.rule,
                "req": round(e.requested, 2),
                "applied": round(e.applied, 2),
            }
            for e in clamp_events
        ]
        entry: dict[str, Any] = {
            "timestep": self.timestep,
            "sim_hour": sim_hour,
            "sim_minute": sim_minute,
            "fallback": fallback_used,
            "fallback_used": fallback_used,  # alias
            "held": held,
            "energy_kwh": round(reading.energy_consumption_kwh, 3),
            "demand_kw": round(step_kw, 2),
            "grid_label": grid_ctx["label"],
            "peak_status": grid_ctx["peak_status"],
            "reasoning": reasoning,
            "actions": actions_summary,  # plan name
            "actions_applied": actions_summary,
            "sensor_snapshot": reading.to_compact(),
            "tool_calls": tool_calls,
            "clamp_events": clamp_summary,
            "tokens_used_total": self.llm.total_tokens,
        }
        self.decision_log.append(entry)
        self._write_log_entry(entry)

        if not held:
            self.memory.append(
                timestep=self.timestep,
                summary=(reasoning[:120] if reasoning else "no reasoning"),
                actions=actions_summary,
                energy_kwh=reading.energy_consumption_kwh,
                fallback_used=fallback_used,
            )

    def _record_fallback_entry(
        self,
        *,
        reasoning: str,
        clamp_events: list[Any],
        reading: Any,
        action: ControlAction | None = None,
    ) -> None:
        sim_minute_total = (self.timestep - 1) * 15
        sim_hour = (sim_minute_total // 60) % 24
        sim_minute = sim_minute_total % 60
        action = action or (policy_action(reading) if reading is not None else safe_action())
        self._last_action = action
        self._append_timeline(action, sim_hour, sim_minute, fallback=True)
        energy = reading.energy_consumption_kwh if reading is not None else 0.0
        step_j = reading.energy_step_j if reading is not None else 0.0
        step_kw = (step_j / 3_600_000.0) * 4.0
        grid_ctx = {
            "label": intensity_label(sim_hour),
            "peak_status": peak_status(step_kw),
        }
        # Minimal reading stub if needed
        if reading is None:
            from bridge.ep_reader import SensorReading

            reading = SensorReading(timestep=self.timestep)
        self._record_entry(
            reading=reading,
            sim_hour=sim_hour,
            sim_minute=sim_minute,
            step_kw=step_kw,
            grid_ctx=grid_ctx,
            reasoning=reasoning,
            tool_calls=[],
            action=action,
            clamp_events=clamp_events,
            fallback_used=True,
            held=False,
        )

    def _write_log_entry(self, entry: dict[str, Any]) -> None:
        """Append one JSONL line and flush (T4.4 kill-mid-run safe)."""
        line = json.dumps(entry, default=str) + "\n"
        try:
            with self._log_path.open("a", encoding="utf-8") as fh:
                fh.write(line)
                fh.flush()
                try:
                    os.fsync(fh.fileno())
                except OSError:
                    pass
            with self._log_alias.open("a", encoding="utf-8") as fh:
                fh.write(line)
                fh.flush()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to write decision log: %s", exc)

    # ------------------------------------------------------------------
    # End-of-run artifacts
    # ------------------------------------------------------------------

    def save_summary(self) -> Path:
        """Write summary.json + Phase 4 artifacts."""
        if not self.decision_log:
            logger.warning("No decisions logged; writing empty summary.")
            summary = {
                "run_id": self.run_id,
                "total_timesteps": 0,
                "error": "no decisions logged",
            }
        else:
            total_steps = len(self.decision_log)
            fallback_count = sum(
                1 for d in self.decision_log if d.get("fallback") or d.get("fallback_used")
            )
            total_clamps = sum(len(d.get("clamp_events", [])) for d in self.decision_log)
            final_kwh = float(self.decision_log[-1]["energy_kwh"])
            baseline = float(self.baseline_kwh or 0.0)
            savings_kwh = baseline - final_kwh
            savings_pct = (savings_kwh / baseline * 100.0) if baseline > 0 else 0.0

            summary = {
                "run_id": self.run_id,
                "total_timesteps": total_steps,
                "llm_calls": self.llm.total_calls,
                "total_tokens": self.llm.total_tokens,
                "fallback_count": fallback_count,
                "total_clamp_events": total_clamps,
                "baseline_kwh": round(baseline, 3),
                "agent_final_kwh": round(final_kwh, 3),
                "savings_kwh": round(savings_kwh, 3),
                "savings_pct": round(savings_pct, 1),
                "decision_log": str(self._log_path),
            }

        summary_path = self._log_dir / "summary.json"
        summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        logger.info("Run summary saved to %s", summary_path)

        # Actuator timeline
        write_actuator_timeline(
            self.actuator_timeline, self._log_dir / "actuator_timeline.csv"
        )

        # Final IDF
        if self.source_idf and self.source_idf.is_file():
            write_runtime_final_state_idf(
                source_idf=self.source_idf,
                out_path=self._log_dir / "runtime_final_state.idf",
                final_cooling=dict(self.writer.last_cooling),
                final_heating=dict(self.writer.last_heating),
                final_lights={
                    z: self._last_action.lighting_levels.get(z, 0.0)
                    for z in CONTROLLED_ZONES
                    if z in self._last_action.lighting_levels
                    or z in self.writer.last_cooling
                },
                run_id=self.run_id,
                summary=summary,
            )
        else:
            logger.warning("source_idf missing — skipped runtime_final_state.idf")

        if "agent_final_kwh" in summary:
            logger.info(
                "RESULT: baseline=%.2f kWh | agent=%.2f kWh | savings=%.2f kWh (%.1f%%)",
                summary.get("baseline_kwh", 0),
                summary["agent_final_kwh"],
                summary.get("savings_kwh", 0),
                summary.get("savings_pct", 0),
            )
        return summary_path
