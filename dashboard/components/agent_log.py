"""Agent activity feed + decision detail — native Streamlit only (no HTML/JSON dumps)."""

from __future__ import annotations

from typing import Any

import streamlit as st


def _normalize_log(raw: dict[str, Any]) -> dict[str, Any]:
    """Map Phase-5 decision rows onto a display-friendly shape."""
    if "llm_reasoning" in raw or ("step" in raw and "time" in raw):
        return raw

    ts = int(raw.get("timestep") or 0)
    hour = int(raw.get("sim_hour") or 0)
    minute = int(raw.get("sim_minute") or 0)
    reasoning = (raw.get("reasoning") or "").strip() or "Holding previous settings."

    actions_out: list[dict[str, Any]] = []
    for t in raw.get("tool_calls") or []:
        name = t.get("tool") or ""
        args = t.get("args") or {}
        if name == "set_hvac_setpoint":
            actions_out.append(
                {
                    "tool": name,
                    "zone": args.get("zone"),
                    "cooling": args.get("cooling_setpoint"),
                    "heating": args.get("heating_setpoint"),
                }
            )
        elif name == "set_lighting_level":
            actions_out.append(
                {
                    "tool": name,
                    "zone": args.get("zone"),
                    "level": args.get("level"),
                }
            )

    if not actions_out:
        for a in raw.get("actions") or []:
            if "lighting_level" in a:
                actions_out.append(
                    {
                        "tool": "set_lighting_level",
                        "zone": a.get("zone"),
                        "level": a["lighting_level"],
                    }
                )
            if "cooling_setpoint" in a or "heating_setpoint" in a:
                actions_out.append(
                    {
                        "tool": "set_hvac_setpoint",
                        "zone": a.get("zone"),
                        "cooling": a.get("cooling_setpoint"),
                        "heating": a.get("heating_setpoint"),
                    }
                )

    clamps = raw.get("clamp_events") or []
    clamp_desc = ""
    if clamps:
        c0 = clamps[0]
        clamp_desc = (
            f"Safety limit · {c0.get('zone', '?')} "
            f"{c0.get('field', 'setpoint')}: asked {c0.get('req', '?')} → kept {c0.get('applied', '?')}"
        )

    grid = str(raw.get("grid_label") or "")
    carbon = 700 if grid.upper() == "HIGH" else 520
    snap = raw.get("sensor_snapshot") or {}

    return {
        "step": ts,
        "time": f"{hour:02d}:{minute:02d}",
        "llm_reasoning": reasoning,
        "actions": actions_out,
        "carbon_intensity": carbon,
        "grid_label": grid or ("HIGH" if carbon >= 650 else "NORMAL"),
        "has_clamp": bool(clamps),
        "clamp_desc": clamp_desc,
        "clamp_count": len(clamps),
        "sensor_snapshot": snap,
        "fallback": bool(raw.get("fallback") or raw.get("fallback_used")),
        "held": bool(raw.get("held")),
    }


def _action_summary(actions: list[dict]) -> str:
    cools: list[float] = []
    lights: list[float] = []
    for act in actions:
        name = act.get("tool", "")
        if name == "set_hvac_setpoint":
            try:
                cools.append(float(act.get("cooling", act.get("cooling_setpoint"))))
            except (TypeError, ValueError):
                pass
        elif name == "set_lighting_level":
            try:
                lights.append(float(act.get("level", 0)))
            except (TypeError, ValueError):
                pass

    parts: list[str] = []
    if cools:
        lo, hi = min(cools), max(cools)
        if lo == hi:
            parts.append(f"Cooling set to {lo:.0f}°C across zones")
        else:
            parts.append(f"Cooling set between {lo:.0f}–{hi:.0f}°C")
    if lights:
        avg = sum(lights) / len(lights)
        if avg <= 0.05:
            parts.append("Lights turned off")
        else:
            parts.append(f"Lights at ~{int(avg * 100)}%")
    return " · ".join(parts) if parts else "No change — holding last settings"


def _plain_reason(text: str, *, truncate: bool = False) -> str:
    t = (text or "").strip()
    if t.startswith("[HOLD]"):
        return "Between decision cycles — keeping the last HVAC and lighting settings."
    if t.startswith("[AUTO]") or t.startswith("[POLICY]"):
        t = t.split("]", 1)[-1].strip() or t
    if not t or t == "No reasoning recorded.":
        return "Agent adjusted setpoints based on occupancy and outdoor conditions."
    if truncate and len(t) > 280:
        return t[:277].rstrip() + "…"
    return t


def _render_full_reasoning(text: str) -> None:
    """Render complete agent reasoning, preserving REASONING / ACTIONS / OUTCOME blocks."""
    raw = (text or "").strip()
    if not raw:
        st.write(_plain_reason(raw))
        return

    if raw.startswith("[HOLD]"):
        st.write(_plain_reason(raw))
        return

    # Structured CoT from the agent prompt
    sections: dict[str, str] = {}
    current = "REASONING"
    buf: list[str] = []
    for line in raw.splitlines():
        upper = line.strip().upper()
        if upper.startswith("REASONING:"):
            if buf:
                sections[current] = "\n".join(buf).strip()
            current = "REASONING"
            rest = line.split(":", 1)[-1].strip()
            buf = [rest] if rest else []
        elif upper.startswith("ACTIONS:"):
            if buf:
                sections[current] = "\n".join(buf).strip()
            current = "ACTIONS"
            rest = line.split(":", 1)[-1].strip()
            buf = [rest] if rest else []
        elif upper.startswith("EXPECTED_OUTCOME:") or upper.startswith("EXPECTED OUTCOME:"):
            if buf:
                sections[current] = "\n".join(buf).strip()
            current = "EXPECTED_OUTCOME"
            rest = line.split(":", 1)[-1].strip()
            buf = [rest] if rest else []
        else:
            buf.append(line)
    if buf:
        sections[current] = "\n".join(buf).strip()

    has_structure = bool(sections.get("ACTIONS") or sections.get("EXPECTED_OUTCOME"))
    reasoning_body = (sections.get("REASONING") or "").removeprefix("REASONING:").strip()

    if has_structure or reasoning_body:
        if reasoning_body:
            st.markdown("**Why the agent acted**")
            st.write(reasoning_body)
        if sections.get("ACTIONS"):
            st.markdown("**Actions planned**")
            st.write(sections["ACTIONS"])
        if sections.get("EXPECTED_OUTCOME"):
            st.markdown("**Expected outcome**")
            st.write(sections["EXPECTED_OUTCOME"])
        return

    st.markdown("**Why the agent acted**")
    st.write(_plain_reason(raw, truncate=False))


def render_agent_log(
    logs: list[dict],
    total_steps: int = 96,
    limit: int = 10,
) -> None:
    normalized = [_normalize_log(x) for x in logs]
    steps_completed = len(normalized)

    st.markdown("#### What the agent did")
    st.caption(
        f"Decision timeline · {steps_completed} of {total_steps} steps · "
        "newest first · scroll for more · HOLD rows hidden"
    )

    if not normalized:
        st.info("No decisions yet. Run the closed loop to populate this feed.")
        return

    active = [x for x in normalized if not x.get("held")]
    pool = active if active else normalized
    selected = list(reversed(pool[-limit:]))

    for log in selected:
        step = int(log.get("step", 0))
        time_str = log.get("time", "--:--")
        grid = str(log.get("grid_label") or "")
        carbon = int(log.get("carbon_intensity", 550))

        if log.get("fallback"):
            tag = "Fallback policy"
        elif log.get("held"):
            tag = "Holding"
        elif carbon >= 650 or grid.upper() == "HIGH":
            tag = "High-carbon grid"
        else:
            tag = "Cleaner grid"

        with st.container(border=True):
            c1, c2 = st.columns([2.2, 1])
            with c1:
                st.markdown(f"**{time_str}** · step {step}")
            with c2:
                st.caption(tag)

            # Full reasoning — never truncate in the live feed
            _render_full_reasoning(str(log.get("llm_reasoning", "")))
            st.caption(_action_summary(log.get("actions") or []))

            if log.get("has_clamp"):
                st.warning(log.get("clamp_desc") or "A safety limit blocked an unsafe setpoint.")


def render_audit_trail(logs: list[dict], limit: int = 8) -> None:
    normalized = [_normalize_log(x) for x in logs]
    st.markdown("#### Peek inside a decision")
    st.caption(
        "Expand any step for the full agent reasoning plus a plain-language sensor snapshot."
    )

    if not normalized:
        st.info("Decision detail appears after the first agent step.")
        return

    active = [x for x in normalized if not x.get("held")]
    pool = active if active else normalized

    for log in reversed(pool[-limit:]):
        step = log.get("step", "?")
        time_str = log.get("time", "--:--")
        with st.expander(f"{time_str}  ·  step {step}", expanded=False):
            _render_full_reasoning(str(log.get("llm_reasoning", "")))
            st.caption(_action_summary(log.get("actions") or []))

            snap = log.get("sensor_snapshot") or {}
            outdoor = snap.get("outdoor_temp", "—")
            grid = log.get("grid_label") or "—"
            carbon = log.get("carbon_intensity", "—")

            m1, m2, m3 = st.columns(3)
            m1.metric("Outdoor air", f"{outdoor}°C" if outdoor != "—" else "—")
            m2.metric("Grid", str(grid))
            m3.metric("Carbon intensity", f"{carbon} gCO₂/kWh")

            zones = snap.get("zones") or {}
            if zones:
                rows = []
                for name, zd in zones.items():
                    if not isinstance(zd, dict):
                        continue
                    occ = int(zd.get("occ", 0) or 0)
                    rows.append(
                        {
                            "Zone": name,
                            "People": occ,
                            "Room °C": zd.get("temp"),
                            "Cooling set to": zd.get("cool_sp"),
                            "Heating set to": zd.get("heat_sp"),
                            "Status": "Occupied" if occ > 0 else "Empty",
                        }
                    )
                if rows:
                    st.dataframe(rows, use_container_width=True, hide_index=True)

            if log.get("has_clamp"):
                st.warning(
                    f"{log.get('clamp_desc')}  ·  "
                    f"{log.get('clamp_count', 1)} safety correction(s) this step"
                )
