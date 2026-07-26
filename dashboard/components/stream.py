"""Live data-bus panel — renders the EnergyPlus <-> LLM flow for one timestep.

Deliverable #5 asks the demo to highlight "data transferring live from
EnergyPlus to the LLM and the subsequent control actions updating the model
parameters". This module renders exactly that, as five ordered stages:

    1 SENSE   EnergyPlus -> Bridge      what the simulation reported
    2 PROMPT  Bridge     -> LLM         what the model was shown
    3 TOOL    LLM        -> Bridge      what the model decided
    4 CLAMP   safety layer             what was corrected (INV-1..5)
    5 ACT     Bridge     -> EnergyPlus  what was actually written

It reads the same events as the terminal renderer (agent/stream.py), so the
video, the CLI and the dashboard can never disagree about what happened.
Falls back to reconstructing stages from a decision log for runs recorded
before the stream bus existed.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

STAGES = [
    ("1", "EnergyPlus → Bridge", "sense"),
    ("2", "Bridge → LLM", "prompt"),
    ("3", "LLM → Bridge", "tool"),
    ("4", "Safety clamps", "clamp"),
    ("5", "Bridge → EnergyPlus", "act"),
]


def _fmt(value: Any, digits: int = 1, suffix: str = "") -> str:
    try:
        return f"{float(value):.{digits}f}{suffix}"
    except (TypeError, ValueError):
        return "—"


def build_flow(decision: dict[str, Any]) -> dict[str, Any]:
    """Project one decision-log row onto the five stage payloads."""
    snap = decision.get("sensor_snapshot") or {}
    zones = snap.get("zones") or {}
    tool_calls = decision.get("tool_calls") or []
    held = bool(decision.get("held"))
    fallback = bool(decision.get("fallback") or decision.get("fallback_used"))

    if fallback:
        decided_by = "Adaptive policy — LLM unavailable"
    elif not tool_calls:
        decided_by = "Adaptive policy — no tool calls returned"
    else:
        decided_by = "LLM tool calls"

    occupied = sum(1 for z in zones.values() if int(z.get("occ", 0) or 0) > 0)

    return {
        "timestep": decision.get("timestep"),
        "clock": f"{int(decision.get('sim_hour') or 0):02d}:"
        f"{int(decision.get('sim_minute') or 0):02d}",
        "sense": {
            "outdoor_temp": snap.get("outdoor_temp"),
            "energy_kwh_cum": snap.get("energy_kwh_cum", decision.get("energy_kwh")),
            "demand_kw": decision.get("demand_kw"),
            "grid_label": decision.get("grid_label"),
            "zones": zones,
        },
        "prompt": {
            "zone_count": len(zones),
            "occupied": occupied,
            "empty": len(zones) - occupied,
            "held": held,
        },
        "tool": {
            "tool_calls": tool_calls,
            "source": decided_by,
            "fallback": fallback,
            "reasoning": (decision.get("reasoning") or "").strip(),
        },
        "clamp": {"clamp_events": decision.get("clamp_events") or []},
        "act": {
            "actions": decision.get("actions") or decision.get("actions_applied") or [],
            "fallback": fallback,
            "held": held,
        },
    }


def _render_sense(p: dict[str, Any]) -> None:
    c1, c2, c3 = st.columns(3)
    c1.metric("Outdoor", _fmt(p.get("outdoor_temp"), 1, " °C"))
    c2.metric("Demand", _fmt(p.get("demand_kw"), 1, " kW"))
    c3.metric("Energy so far", _fmt(p.get("energy_kwh_cum"), 2, " kWh"))

    zones = p.get("zones") or {}
    if not zones:
        st.caption("No sensor snapshot recorded for this step.")
        return
    st.dataframe(
        [
            {
                "Zone": z,
                "Temp °C": zd.get("temp"),
                "People": int(zd.get("occ", 0) or 0),
                "Cool SP": zd.get("cool_sp"),
                "Heat SP": zd.get("heat_sp"),
                "State": "occupied" if int(zd.get("occ", 0) or 0) > 0 else "empty",
            }
            for z, zd in zones.items()
        ],
        hide_index=True,
        use_container_width=True,
    )


def _render_prompt(p: dict[str, Any]) -> None:
    if p.get("held"):
        st.caption(
            "No LLM call this step — holding the previous setpoints "
            "(cadence throttle saves tokens between decisions)."
        )
        return
    st.caption(
        f"Sent {p.get('zone_count', 0)} zones to the model — "
        f"{p.get('occupied', 0)} occupied, {p.get('empty', 0)} empty. "
        "Only this compact snapshot crosses the wire; raw EnergyPlus logs stay on disk."
    )


def _render_tool(p: dict[str, Any]) -> None:
    calls = p.get("tool_calls") or []
    if p.get("fallback"):
        st.warning(p.get("source", "Fallback"), icon="⚠️")
    else:
        st.caption(p.get("source", ""))

    if calls:
        st.dataframe(
            [
                {
                    "Tool": c.get("tool"),
                    **{k: v for k, v in (c.get("args") or {}).items()},
                }
                for c in calls
            ],
            hide_index=True,
            use_container_width=True,
        )
    reasoning = p.get("reasoning")
    if reasoning:
        st.markdown(f"> {reasoning.splitlines()[0]}")


def _render_clamp(p: dict[str, Any]) -> None:
    events = p.get("clamp_events") or []
    if not events:
        st.success("No corrections — the model stayed inside every safety limit.", icon="✅")
        return
    st.warning(f"{len(events)} correction(s) applied before writing.", icon="🛡️")
    st.dataframe(
        [
            {
                "Zone": e.get("zone"),
                "Field": e.get("field"),
                "Asked": e.get("req"),
                "Applied": e.get("applied"),
                "Rule": e.get("rule"),
            }
            for e in events
        ],
        hide_index=True,
        use_container_width=True,
    )


def _render_act(p: dict[str, Any]) -> None:
    actions = p.get("actions") or []
    if not actions:
        st.caption("No actuator writes this step.")
        return
    if p.get("held"):
        st.caption("Re-applied the previous setpoints to keep actuator ownership.")
    st.dataframe(
        [
            {
                "Zone": a.get("zone"),
                "Cooling °C": a.get("cooling_setpoint"),
                "Heating °C": a.get("heating_setpoint"),
                "Lights": a.get("lighting_level"),
            }
            for a in actions
        ],
        hide_index=True,
        use_container_width=True,
    )


_RENDERERS = {
    "sense": _render_sense,
    "prompt": _render_prompt,
    "tool": _render_tool,
    "clamp": _render_clamp,
    "act": _render_act,
}


def render_data_stream(logs: list[dict[str, Any]], *, key: str = "stream") -> None:
    """Render the five-stage EnergyPlus <-> LLM flow for a chosen timestep."""
    st.markdown("#### Live data bus — EnergyPlus → LLM → control actions")
    st.caption(
        "Every 15 minutes the loop runs these five stages. "
        "Pick a timestep to inspect exactly what crossed each boundary."
    )

    if not logs:
        st.info("No decisions recorded yet — run the closed loop to populate the bus.")
        return

    steps = [int(d.get("timestep") or 0) for d in logs]
    # Default to the busiest step so the panel opens on something interesting.
    default = max(
        range(len(logs)),
        key=lambda i: len(logs[i].get("tool_calls") or [])
        + len(logs[i].get("clamp_events") or []),
    )
    chosen = st.select_slider(
        "Timestep",
        options=steps,
        value=steps[default],
        key=f"{key}_step",
    )
    decision = next((d for d in logs if int(d.get("timestep") or 0) == chosen), logs[0])
    flow = build_flow(decision)

    st.markdown(f"**Timestep {flow['timestep']} · {flow['clock']}**")
    for glyph, title, stage in STAGES:
        with st.container(border=True):
            st.markdown(f"**{glyph} · {title}**")
            _RENDERERS[stage](flow[stage])
