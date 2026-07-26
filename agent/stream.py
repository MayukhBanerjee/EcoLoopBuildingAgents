"""
stream.py — observable EnergyPlus <-> LLM data bus.

Makes the closed loop visible. Every timestep emits five ordered stages:

    SENSE   EnergyPlus  -> Bridge     live sensor snapshot
    PROMPT  Bridge      -> LLM        what the model was actually shown
    TOOL    LLM         -> Bridge     tool calls the model chose
    CLAMP   Bridge      -> Bridge     safety corrections (INV-1..5)
    ACT     Bridge      -> EnergyPlus actuator writes

Sinks are pluggable. ConsoleSink renders the flow live in a terminal;
JsonlSink appends newline-delimited events to disk so the dashboard and
scripts/replay_stream.py can re-render the exact same flow without
re-running the simulation or spending LLM tokens.

Emission is best-effort by contract: publish() swallows every sink
exception. Observability must never be able to break the control loop
(same discipline as INV-7 in the EnergyPlus callback).
"""

from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

logger = logging.getLogger("EcoLoop.agent.stream")

SENSE = "SENSE"
PROMPT = "PROMPT"
TOOL = "TOOL"
CLAMP = "CLAMP"
ACT = "ACT"

STAGE_ORDER = (SENSE, PROMPT, TOOL, CLAMP, ACT)

# Stage -> (glyph, arrow label) for terminal + UI rendering
STAGE_META: dict[str, tuple[str, str]] = {
    SENSE: ("1", "EnergyPlus  --->  Bridge"),
    PROMPT: ("2", "Bridge      --->  LLM"),
    TOOL: ("3", "LLM         --->  Bridge"),
    CLAMP: ("4", "Safety clamps"),
    ACT: ("5", "Bridge      --->  EnergyPlus"),
}


@dataclass
class StreamEvent:
    """One stage of one timestep in the closed loop."""

    timestep: int
    stage: str
    sim_hour: int = 0
    sim_minute: int = 0
    payload: dict[str, Any] = field(default_factory=dict)

    @property
    def clock(self) -> str:
        return f"{self.sim_hour:02d}:{self.sim_minute:02d}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestep": self.timestep,
            "stage": self.stage,
            "sim_hour": self.sim_hour,
            "sim_minute": self.sim_minute,
            "payload": self.payload,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> StreamEvent:
        return cls(
            timestep=int(raw.get("timestep", 0)),
            stage=str(raw.get("stage", "")),
            sim_hour=int(raw.get("sim_hour", 0)),
            sim_minute=int(raw.get("sim_minute", 0)),
            payload=raw.get("payload") or {},
        )


class StreamSink(Protocol):
    """Anything that can consume stream events."""

    def handle(self, event: StreamEvent) -> None: ...

    def close(self) -> None: ...


# ---------------------------------------------------------------------------
# Terminal renderer
# ---------------------------------------------------------------------------

_ANSI = {
    "reset": "\033[0m",
    "dim": "\033[2m",
    "bold": "\033[1m",
    "teal": "\033[36m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "red": "\033[31m",
    "blue": "\033[34m",
}

_STAGE_COLOR = {
    SENSE: "blue",
    PROMPT: "dim",
    TOOL: "teal",
    CLAMP: "yellow",
    ACT: "green",
}


def _supports_color(stream: Any) -> bool:
    if os.getenv("NO_COLOR"):
        return False
    if os.getenv("ECOLOOP_STREAM_COLOR") == "0":
        return False
    return bool(getattr(stream, "isatty", lambda: False)())


class ConsoleSink:
    """Renders the five-stage flow as a boxed block per timestep."""

    WIDTH = 74

    def __init__(self, stream: Any | None = None, *, color: bool | None = None) -> None:
        self._out = stream if stream is not None else sys.stdout
        self._color = _supports_color(self._out) if color is None else color
        self._open_timestep: int | None = None

    # -- colour helpers -------------------------------------------------

    def _c(self, text: str, key: str) -> str:
        if not self._color or key not in _ANSI:
            return text
        return f"{_ANSI[key]}{text}{_ANSI['reset']}"

    def _write(self, text: str) -> None:
        self._out.write(text + "\n")
        try:
            self._out.flush()
        except Exception:  # noqa: BLE001 - a closed pipe must not kill the run
            pass

    # -- frame management ----------------------------------------------

    def _open_frame(self, event: StreamEvent) -> None:
        title = f" T{event.timestep}  {event.clock} "
        bar = "-" * max(0, self.WIDTH - len(title) - 2)
        self._write(self._c(f"+-{title}{bar}", "bold"))
        self._open_timestep = event.timestep

    def _close_frame(self) -> None:
        if self._open_timestep is not None:
            self._write(self._c("+" + "-" * self.WIDTH, "dim"))
            self._open_timestep = None

    def _line(self, text: str = "") -> None:
        self._write(f"| {text}" if text else "|")

    def _stage_header(self, event: StreamEvent, detail: str) -> None:
        glyph, arrow = STAGE_META.get(event.stage, ("?", event.stage))
        colored = self._c(f"{glyph} {arrow}", _STAGE_COLOR.get(event.stage, "reset"))
        pad = " " * max(1, 30 - len(f"{glyph} {arrow}"))
        self._line(f"{colored}{pad}{self._c(detail, 'dim')}")

    # -- main entry point ----------------------------------------------

    def handle(self, event: StreamEvent) -> None:
        if event.stage == SENSE and self._open_timestep is not None:
            self._close_frame()
        if self._open_timestep is None:
            self._open_frame(event)

        renderer = {
            SENSE: self._render_sense,
            PROMPT: self._render_prompt,
            TOOL: self._render_tool,
            CLAMP: self._render_clamp,
            ACT: self._render_act,
        }.get(event.stage)
        if renderer is not None:
            renderer(event)

        if event.stage == ACT:
            self._close_frame()

    # -- per-stage renderers ------------------------------------------

    def _render_sense(self, event: StreamEvent) -> None:
        p = event.payload
        outdoor = p.get("outdoor_temp")
        cum = p.get("energy_kwh_cum")
        demand = p.get("demand_kw")
        bits = []
        if outdoor is not None:
            bits.append(f"outdoor {float(outdoor):.1f}C")
        if demand is not None:
            bits.append(f"demand {float(demand):.1f} kW")
        if cum is not None:
            bits.append(f"cum {float(cum):.2f} kWh")
        grid = p.get("grid_label")
        if grid:
            bits.append(f"grid {grid}")
        self._stage_header(event, " | ".join(bits))

        zones: dict[str, Any] = p.get("zones") or {}
        for zone, zd in zones.items():
            occ = int(zd.get("occ", 0) or 0)
            flag = self._c("OCCUPIED", "green") if occ > 0 else self._c("empty", "dim")
            self._line(
                f"   {zone:<9} {float(zd.get('temp', 0)):5.1f}C  "
                f"occ {occ:<3} cool {float(zd.get('cool_sp', 0)):5.1f} "
                f"heat {float(zd.get('heat_sp', 0)):5.1f}  {flag}"
            )

    def _render_prompt(self, event: StreamEvent) -> None:
        p = event.payload
        bits = []
        if p.get("model"):
            bits.append(str(p["model"]))

        if p.get("prompt_chars") is not None:
            bits.append(f"{p['prompt_chars']} chars")
        if p.get("est_tokens") is not None:
            bits.append(f"~{p['est_tokens']} tok")
        if p.get("cadence"):
            bits.append(str(p["cadence"]))
        self._stage_header(event, " | ".join(bits))
        for line in (p.get("preview") or "").splitlines():
            if line.strip():
                self._line(self._c(f"   {line[: self.WIDTH - 8]}", "dim"))

    def _render_tool(self, event: StreamEvent) -> None:
        p = event.payload
        bits = []
        if p.get("latency_ms") is not None:
            bits.append(f"{float(p['latency_ms']) / 1000:.2f}s")
        if p.get("tokens") is not None:
            bits.append(f"{p['tokens']} tok")
        if p.get("source"):
            bits.append(str(p["source"]))
        self._stage_header(event, " | ".join(bits))

        calls = p.get("tool_calls") or []
        if not calls:
            self._line(self._c("   (no tool calls returned)", "yellow"))
        for call in calls:
            args = call.get("args") or {}
            # zone first — truncation must never eat the zone name
            ordered = sorted(args.items(), key=lambda kv: kv[0] != "zone")
            arg_str = " ".join(f"{k}={v}" for k, v in ordered)
            name = str(call.get("tool", "?"))
            room = self.WIDTH - 8 - len(name)
            self._line(f"   {self._c(name, 'teal')}  {arg_str[:room]}")
        reasoning = (p.get("reasoning") or "").strip()
        if reasoning:
            first = reasoning.splitlines()[0]
            self._line(self._c(f"   \"{first[: self.WIDTH - 12]}\"", "dim"))

    def _render_clamp(self, event: StreamEvent) -> None:
        events = event.payload.get("clamp_events") or []
        if not events:
            self._stage_header(event, self._c("none - LLM stayed in bounds", "green"))
            return
        self._stage_header(event, self._c(f"{len(events)} correction(s)", "yellow"))
        for ev in events:
            self._line(
                self._c(
                    f"   {str(ev.get('zone', '?')):<9} {str(ev.get('field', '?')):<8} "
                    f"{float(ev.get('req', 0)):.1f} -> {float(ev.get('applied', 0)):.1f}"
                    f"   [{ev.get('rule', '?')}]",
                    "yellow",
                )
            )

    def _render_act(self, event: StreamEvent) -> None:
        p = event.payload
        actions = p.get("actions") or []
        tag = ""
        if p.get("fallback"):
            tag = self._c("  [FALLBACK]", "red")
        elif p.get("held"):
            tag = self._c("  [HOLD]", "dim")
        self._stage_header(event, f"{len(actions)} actuator write(s){tag}")
        for act in actions:
            parts = []
            if "cooling_setpoint" in act:
                parts.append(f"cool={float(act['cooling_setpoint']):.1f}")
            if "heating_setpoint" in act:
                parts.append(f"heat={float(act['heating_setpoint']):.1f}")
            if "lighting_level" in act:
                parts.append(f"lights={float(act['lighting_level']):.2f}")
            self._line(
                f"   {self._c(str(act.get('zone', '?')), 'green'):<9} {'  '.join(parts)}"
            )

    def close(self) -> None:
        self._close_frame()


# ---------------------------------------------------------------------------
# JSONL sink
# ---------------------------------------------------------------------------


class JsonlSink:
    """Appends events to a newline-delimited JSON file."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self.path.open("a", encoding="utf-8")

    def handle(self, event: StreamEvent) -> None:
        self._fh.write(json.dumps(event.to_dict(), default=str) + "\n")
        self._fh.flush()

    def close(self) -> None:
        try:
            self._fh.close()
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# Bus
# ---------------------------------------------------------------------------


class StreamBus:
    """Fan-out event publisher. Sink failures are logged, never raised."""

    def __init__(self, sinks: list[StreamSink] | None = None) -> None:
        self.sinks: list[StreamSink] = list(sinks or [])
        self.event_count = 0

    def add(self, sink: StreamSink) -> None:
        self.sinks.append(sink)

    def publish(
        self,
        *,
        timestep: int,
        stage: str,
        sim_hour: int = 0,
        sim_minute: int = 0,
        **payload: Any,
    ) -> None:
        """Emit one event. Never raises."""
        if not self.sinks:
            return
        event = StreamEvent(
            timestep=timestep,
            stage=stage,
            sim_hour=sim_hour,
            sim_minute=sim_minute,
            payload=payload,
        )
        self.event_count += 1
        for sink in self.sinks:
            try:
                sink.handle(event)
            except Exception:  # noqa: BLE001 - observability never breaks control
                logger.debug("Stream sink %s failed", type(sink).__name__, exc_info=True)

    def close(self) -> None:
        for sink in self.sinks:
            try:
                sink.close()
            except Exception:  # noqa: BLE001
                pass


def read_events(path: str | Path) -> list[StreamEvent]:
    """Load events from a JSONL file written by JsonlSink."""
    p = Path(path)
    if not p.is_file():
        return []
    events: list[StreamEvent] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            events.append(StreamEvent.from_dict(json.loads(line)))
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
    return events


def group_by_timestep(events: list[StreamEvent]) -> dict[int, dict[str, StreamEvent]]:
    """Collapse a flat event list into {timestep: {stage: event}}."""
    grouped: dict[int, dict[str, StreamEvent]] = {}
    for ev in events:
        grouped.setdefault(ev.timestep, {})[ev.stage] = ev
    return grouped
