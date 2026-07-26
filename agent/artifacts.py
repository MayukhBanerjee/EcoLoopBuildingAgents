"""
artifacts.py — Phase 4 deliverable exporters.

Produces:
  - actuator_timeline.csv  (step, zone, cooling, heating, lights)
  - runtime_final_state.idf (runtime.idf + header + final setpoint schedules)
"""

from __future__ import annotations

import csv
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bridge.constants import CONTROLLED_ZONES

logger = logging.getLogger("EcoLoop.agent.artifacts")


def write_actuator_timeline(
    rows: list[dict[str, Any]],
    out_path: Path,
) -> Path:
    """Write every applied override as a CSV row."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "timestep",
        "sim_hour",
        "sim_minute",
        "zone",
        "cooling_c",
        "heating_c",
        "lights_fraction",
        "fallback",
    ]
    with out_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})
    logger.info("Wrote actuator timeline: %s (%d rows)", out_path, len(rows))
    return out_path


def _schedule_compact(
    name: str,
    schedule_type: str,
    *,
    until_time: str,
    value: float,
) -> str:
    """Minimal Schedule:Compact covering the whole day with a constant value."""
    return (
        f"Schedule:Compact,\n"
        f"  {name},                     !- Name\n"
        f"  {schedule_type},            !- Schedule Type Limits Name\n"
        f"  Through: 12/31,             !- Field 1\n"
        f"  For: AllDays,               !- Field 2\n"
        f"  Until: {until_time},        !- Field 3\n"
        f"  {value:.2f};                !- Field 4\n"
    )


def write_runtime_final_state_idf(
    *,
    source_idf: Path,
    out_path: Path,
    final_cooling: dict[str, float],
    final_heating: dict[str, float],
    final_lights: dict[str, float],
    run_id: str,
    summary: dict[str, Any] | None = None,
) -> Path:
    """
    Copy runtime.idf and append a generated comment header plus Schedule:Compact
    objects encoding the agent's final setpoints (brief deliverable).
    """
    if not source_idf.is_file():
        raise FileNotFoundError(f"Source IDF not found: {source_idf}")

    src = source_idf.read_text(encoding="utf-8", errors="replace")
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    savings = (summary or {}).get("savings_pct", "?")
    agent_kwh = (summary or {}).get("agent_final_kwh", "?")

    header = (
        f"! ============================================================\n"
        f"! EcoLoop runtime_final_state.idf\n"
        f"! Generated: {stamp}\n"
        f"! Run ID   : {run_id}\n"
        f"! Agent kWh: {agent_kwh}\n"
        f"! Savings  : {savings}%\n"
        f"! Source   : {source_idf.name}\n"
        f"! Note: Schedule:Compact blocks below encode FINAL agent setpoints\n"
        f"!       applied at the end of the closed-loop run (documentation).\n"
        f"!       Live control during the run used EMS actuators, not these.\n"
        f"! ============================================================\n\n"
    )

    schedules: list[str] = [
        "! ----- EcoLoop final agent setpoints (generated) -----\n"
    ]
    for zone in CONTROLLED_ZONES:
        cool = final_cooling.get(zone)
        heat = final_heating.get(zone)
        light = final_lights.get(zone)
        if cool is not None:
            schedules.append(
                _schedule_compact(
                    f"EcoLoop Final Cool {zone}",
                    "Temperature",
                    until_time="24:00",
                    value=float(cool),
                )
            )
        if heat is not None:
            schedules.append(
                _schedule_compact(
                    f"EcoLoop Final Heat {zone}",
                    "Temperature",
                    until_time="24:00",
                    value=float(heat),
                )
            )
        if light is not None:
            schedules.append(
                _schedule_compact(
                    f"EcoLoop Final Lights {zone}",
                    "Fraction",
                    until_time="24:00",
                    value=float(light),
                )
            )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(header + src + "\n" + "\n".join(schedules), encoding="utf-8")
    logger.info("Wrote runtime final state IDF: %s", out_path)
    return out_path
