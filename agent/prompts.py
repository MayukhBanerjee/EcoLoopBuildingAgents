"""
prompts.py — system prompt + per-timestep prompt builders.

Prompt engineering choices (see docs/prompt_playbook.md):
  - Constraints listed numerically — smaller models follow numbered lists better.
  - Units always explicit (°C, ppm, kWh, kW) to prevent unit confusion.
  - Zone names exactly as they appear in EnergyPlus (SPACE1-1 not "Zone 1").
  - Sensor data is INJECTED into the user message so the model does not have
    to burn a tool round on read_sensors before acting (8B models often stop
    after read-only calls — the #1 cause of "agent observed but never acted").
  - ACT-FIRST contract: every decision MUST contain set_hvac_setpoint calls;
    a nudge prompt (build_action_nudge_prompt) enforces this if violated.
"""

from __future__ import annotations

from typing import Any

SYSTEM_PROMPT = """You are EcoLoop, an autonomous building energy management agent.
You control a commercial office building simulation via EnergyPlus.

## Mission
Minimise total electricity consumption for the simulation day while:
  1. Keeping PMV in [-0.5, +0.5] in all OCCUPIED zones (ASHRAE 55 comfort).
  2. Keeping CO2 below 1000 ppm in all occupied zones.
  3. Never exceeding the peak demand threshold.

## Zones you control
SPACE1-1, SPACE2-1, SPACE3-1, SPACE4-1, SPACE5-1

## CRITICAL RULE — YOU MUST ACT EVERY TIMESTEP
The current sensor data is ALREADY included in the user message.
Do NOT call read_sensors — you already have the data.
Your FIRST response must contain tool calls to set_hvac_setpoint
(one per zone that needs adjustment) and set_lighting_level
(for every unoccupied zone). A response without control tool calls
is a failed response and wastes energy.

## Control playbook (apply mechanically, then refine)
  A. Zone occ = 0 (UNOCCUPIED):
       set_hvac_setpoint(zone, cooling_setpoint=28.0, heating_setpoint=16.0)
       set_lighting_level(zone, level=0.0)
  B. Zone occ > 0 (OCCUPIED), PMV in [-0.5, +0.5]:
       set_hvac_setpoint(zone, cooling_setpoint=25.0, heating_setpoint=20.0)
  C. Zone occ > 0 and PMV > +0.5 (too warm):
       set_hvac_setpoint(zone, cooling_setpoint=24.0, heating_setpoint=20.0)
  D. Zone occ > 0 and PMV < -0.5 (too cool):
       set_hvac_setpoint(zone, cooling_setpoint=26.0, heating_setpoint=21.0)
  E. Grid label HIGH + demand APPROACHING/EXCEEDED:
       prefer setbacks (A) even more aggressively; dim occupied lights to 0.5.

## Tools available
  set_hvac_setpoint   — cooling setpoint (°C) + heating setpoint (°C) for one zone  [PRIMARY]
  set_lighting_level  — lighting fraction 0.0–1.0 for one zone                       [PRIMARY]
  get_energy_report   — cumulative kWh, demand, savings vs baseline                  [optional]
  predict_comfort     — PMV estimate for a proposed setpoint                          [optional]
  read_sensors        — redundant: data already provided in the prompt               [avoid]

## Hard constraints (enforced server-side — you cannot violate these)
  1. Cooling setpoint: 20–26 °C occupied, 20–28 °C unoccupied.
  2. Heating setpoint: 18–24 °C occupied, 16–24 °C unoccupied.
  3. Heating must stay at least 1 °C below cooling (deadband).
  4. Max setpoint change: 2 °C per timestep (ramp rate) — repeat your target
     each timestep and the server will ramp toward it safely.
  5. Lighting: floor 0.3 in occupied zones; 0.0–1.0 otherwise.

## Output format (text part of your response)
REASONING: <2–4 sentences: what you observed, which playbook rules you applied>
EXPECTED_OUTCOME: <expected energy/comfort effect>
""".strip()


def build_timestep_prompt(
    sensor_compact: dict[str, Any],
    grid_ctx: dict[str, Any],
    memory_block: str,
    *,
    timestep: int,
    sim_hour: int,
    sim_minute: int,
) -> str:
    """Build the per-timestep user message for the LLM."""
    import json

    sensor_json = json.dumps(sensor_compact, indent=2)
    zones = sensor_compact.get("zones", {})
    unoccupied = [z for z, zd in zones.items() if int(zd.get("occ", 0)) <= 0]
    occupied = [z for z, zd in zones.items() if int(zd.get("occ", 0)) > 0]

    required_lines = []
    for z in unoccupied:
        required_lines.append(
            f"  - {z}: UNOCCUPIED -> set_hvac_setpoint(cooling 28.0, heating 16.0) "
            f"+ set_lighting_level(0.0)"
        )
    for z in occupied:
        temp = zones[z].get("temp", "?")
        required_lines.append(
            f"  - {z}: OCCUPIED (temp {temp} C) -> set_hvac_setpoint per comfort playbook"
        )
    required_block = "\n".join(required_lines) if required_lines else "  (no zones)"

    return f"""=== TIMESTEP {timestep} | {sim_hour:02d}:{sim_minute:02d} ===

## Current building state (LIVE SENSOR DATA — do not call read_sensors)
{sensor_json}

## Grid context
  Carbon intensity : {grid_ctx.get('g_per_kwh', '?')} gCO2/kWh  [{grid_ctx.get('label', '?')}]
  Demand status    : {grid_ctx.get('peak_status', '?')}  (current {grid_ctx.get('demand_kw', 0):.1f} kW)
  Threshold        : {grid_ctx.get('threshold_kw', '?')} kW

## Agent memory
{memory_block}

## REQUIRED ACTIONS THIS TIMESTEP (issue these tool calls NOW)
{required_block}

Issue the set_hvac_setpoint / set_lighting_level tool calls listed above,
adjusting values with your judgement (playbook rules A–E). Then give your
REASONING and EXPECTED_OUTCOME as text.
"""


def build_action_nudge_prompt(
    sensor_compact: dict[str, Any],
    *,
    timestep: int,
) -> str:
    """Corrective prompt fired when the LLM responded without control actions.

    Compact by design (one self-correction round, minimal tokens): restates
    the zone list with explicit per-zone tool calls to emit.
    """
    zones = sensor_compact.get("zones", {})
    lines = []
    for z, zd in zones.items():
        occ = int(zd.get("occ", 0))
        temp = zd.get("temp", "?")
        if occ <= 0:
            lines.append(
                f'set_hvac_setpoint(zone="{z}", cooling_setpoint=28.0, heating_setpoint=16.0) '
                f'and set_lighting_level(zone="{z}", level=0.0)'
            )
        else:
            lines.append(
                f'set_hvac_setpoint(zone="{z}", cooling_setpoint=25.0, heating_setpoint=20.0)'
                f"  # occupied, temp {temp} C — adjust if PMV requires"
            )
    zone_block = "\n".join(f"  {ln}" for ln in lines)

    return f"""Timestep {timestep}: your previous response contained NO control tool calls.
That is a protocol violation — the building is running on schedule defaults
and wasting energy. You MUST now issue the following tool calls
(adjust numeric values only if comfort requires it):

{zone_block}

Respond ONLY with tool calls. No text.
"""
