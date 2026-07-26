#!/usr/bin/env python
"""
replay_stream.py — re-render a finished run's EnergyPlus <-> LLM flow.

Reads stream_events.jsonl (written by agent.stream.JsonlSink during a live
run) and replays it through the same ConsoleSink used at runtime. Because the
events are already on disk, a replay costs no LLM tokens, hits no rate limit,
and is byte-identical every time — which is what you want when recording the
demo video or showing the loop without a 5-minute EnergyPlus run.

If a run predates the stream bus (no stream_events.jsonl), the script
reconstructs the five stages from agent_decisions.jsonl instead, so every
historical run in data/agent_results is still replayable.

Usage
-----
    uv run python scripts/replay_stream.py                    # latest run
    uv run python scripts/replay_stream.py --speed 4          # 4x faster
    uv run python scripts/replay_stream.py --steps 12         # first 12 steps
    uv run python scripts/replay_stream.py --run data/agent_results/<id>
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))

from agent.stream import (  # noqa: E402
    ACT,
    CLAMP,
    PROMPT,
    SENSE,
    TOOL,
    ConsoleSink,
    StreamEvent,
    read_events,
)

AGENT_ROOT = ROOT / "data" / "agent_results"


def _latest_run() -> Path | None:
    """Newest run directory that has any replayable log."""
    if not AGENT_ROOT.is_dir():
        return None
    candidates = [
        p
        for p in AGENT_ROOT.iterdir()
        if p.is_dir()
        and (
            (p / "stream_events.jsonl").is_file()
            or (p / "agent_decisions.jsonl").is_file()
            or (p / "decisions.jsonl").is_file()
        )
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _decisions_path(run_dir: Path) -> Path | None:
    for name in ("agent_decisions.jsonl", "decisions.jsonl"):
        p = run_dir / name
        if p.is_file():
            return p
    return None


def _events_from_decisions(path: Path) -> list[StreamEvent]:
    """Rebuild the five-stage flow from a decision log (pre-stream runs)."""
    events: list[StreamEvent] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            d: dict[str, Any] = json.loads(line)
        except json.JSONDecodeError:
            continue

        ts = int(d.get("timestep", 0))
        hour = int(d.get("sim_hour", 0))
        minute = int(d.get("sim_minute", 0))
        snap = d.get("sensor_snapshot") or {}
        held = bool(d.get("held"))
        fallback = bool(d.get("fallback") or d.get("fallback_used"))
        tool_calls = d.get("tool_calls") or []

        def _ev(stage: str, **payload: Any) -> StreamEvent:
            return StreamEvent(
                timestep=ts,
                stage=stage,
                sim_hour=hour,
                sim_minute=minute,
                payload=payload,
            )

        events.append(
            _ev(
                SENSE,
                outdoor_temp=snap.get("outdoor_temp"),
                energy_kwh_cum=snap.get("energy_kwh_cum", d.get("energy_kwh")),
                demand_kw=d.get("demand_kw"),
                grid_label=d.get("grid_label"),
                peak_status=d.get("peak_status"),
                zones=snap.get("zones") or {},
            )
        )

        if not held:
            zones = snap.get("zones") or {}
            occupied = sum(
                1 for zd in zones.values() if int(zd.get("occ", 0) or 0) > 0
            )
            events.append(
                _ev(
                    PROMPT,
                    model="replay",
                    cadence="reconstructed from decision log",
                    preview=(
                        f"sensor snapshot: {len(zones)} zones, "
                        f"{occupied} occupied, {len(zones) - occupied} empty"
                    ),
                )
            )
            events.append(
                _ev(
                    TOOL,
                    tool_calls=[
                        {"tool": t.get("tool"), "args": t.get("args")}
                        for t in tool_calls
                    ],
                    source=(
                        "adaptive policy"
                        if fallback or not tool_calls
                        else "LLM tool calls"
                    ),
                    fallback=fallback,
                    reasoning=d.get("reasoning", ""),
                )
            )

        events.append(_ev(CLAMP, clamp_events=d.get("clamp_events") or []))
        events.append(
            _ev(
                ACT,
                actions=d.get("actions") or d.get("actions_applied") or [],
                fallback=fallback,
                held=held,
            )
        )
    return events


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Replay the EnergyPlus -> LLM -> actuator stream."
    )
    parser.add_argument("--run", type=Path, default=None, help="Run directory.")
    parser.add_argument(
        "--speed",
        type=float,
        default=1.0,
        help="Playback multiplier (higher is faster). Use 0 for no delay.",
    )
    parser.add_argument(
        "--steps", type=int, default=None, help="Replay only the first N timesteps."
    )
    parser.add_argument(
        "--no-color", action="store_true", help="Disable ANSI colour."
    )
    args = parser.parse_args()

    run_dir = args.run.resolve() if args.run else _latest_run()
    if run_dir is None or not run_dir.is_dir():
        print("No run found under data/agent_results. Run main.py first.")
        sys.exit(1)

    stream_file = run_dir / "stream_events.jsonl"
    if stream_file.is_file():
        events = read_events(stream_file)
        source = stream_file.name
    else:
        decisions = _decisions_path(run_dir)
        if decisions is None:
            print(f"No replayable log in {run_dir}.")
            sys.exit(1)
        events = _events_from_decisions(decisions)
        source = f"{decisions.name} (reconstructed)"

    if not events:
        print(f"No events found in {run_dir}.")
        sys.exit(1)

    if args.steps is not None:
        events = [e for e in events if e.timestep <= args.steps]

    timesteps = sorted({e.timestep for e in events})
    print(f"\nEcoLoop stream replay — {run_dir.name}")
    print(f"source: {source} | {len(events)} events | {len(timesteps)} timesteps\n")

    # Per-timestep delay; 0.35s reads naturally on video at speed=1.
    delay = 0.0 if args.speed <= 0 else 0.35 / args.speed

    sink = ConsoleSink(color=not args.no_color)
    try:
        current = events[0].timestep
        for event in events:
            if event.timestep != current and delay:
                time.sleep(delay)
                current = event.timestep
            sink.handle(event)
    except KeyboardInterrupt:
        print("\nReplay interrupted.")
    finally:
        sink.close()

    print(f"\nReplay complete — {len(timesteps)} timesteps.\n")


if __name__ == "__main__":
    main()
