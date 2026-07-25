"""Agent reasoning feed and audit expanders."""

from __future__ import annotations

import streamlit as st


def _action_line(actions: list[dict]) -> str:
    parts: list[str] = []
    for act in actions:
        name = act.get("tool", "")
        if name == "set_hvac_setpoint":
            parts.append(f"HVAC {act.get('cooling')}°C cool")
        elif name == "set_lighting_level":
            level = act.get("level", 0)
            parts.append(f"Lights {int(float(level) * 100)}%")
        else:
            parts.append(name or "action")
    return " · ".join(parts) if parts else "hold — no change"


def render_agent_log(logs: list[dict], total_steps: int = 96, limit: int = 14) -> None:
    steps_completed = len(logs)
    st.markdown(
        f"""
        <div class="feed-shell">
          <div class="feed-header">
            <div>
              <div class="feed-title">Agent activity</div>
              <div class="feed-sub">Live reasoning · tool calls · safety clamps</div>
            </div>
            <div class="feed-step">t{steps_completed:02d}<span>/{total_steps}</span></div>
          </div>
        """,
        unsafe_allow_html=True,
    )

    if not logs:
        st.markdown(
            '<div class="feed-empty">No decisions yet. Start the closed loop to populate this feed.</div>',
            unsafe_allow_html=True,
        )
        st.markdown("</div>", unsafe_allow_html=True)
        return

    rows_html: list[str] = ['<div class="feed-scroll">']
    for log in reversed(logs[-limit:]):
        step_num = int(log.get("step", 0))
        time_str = log.get("time", "00:00")
        reasoning = log.get("llm_reasoning", "No reasoning recorded.")
        actions = log.get("actions", [])
        carbon = int(log.get("carbon_intensity", 550))
        high_carbon = carbon >= 650
        badge_cls = "badge-warn" if high_carbon else "badge-ok"
        badge_label = "HIGH GRID" if high_carbon else "CLEAN GRID"
        clamp_html = ""
        if log.get("has_clamp", False):
            clamp_text = log.get("clamp_desc", "Actuator override intercepted.")
            clamp_html = f'<div class="clamp-line">{clamp_text}</div>'

        rows_html.append(
            f"""
            <div class="feed-row">
              <div class="feed-meta">
                <span class="feed-time">t{step_num:02d} · {time_str}</span>
                <span class="badge {badge_cls}">{carbon} gCO₂ · {badge_label}</span>
              </div>
              <div class="feed-body">{reasoning}</div>
              <div class="feed-cmd">{_action_line(actions)}</div>
              {clamp_html}
            </div>
            """
        )
    rows_html.append("</div></div>")
    st.markdown("".join(rows_html), unsafe_allow_html=True)


def render_audit_trail(logs: list[dict], limit: int = 5) -> None:
    st.markdown(
        """
        <div class="section-head">
          <div class="section-title">Audit trail</div>
          <div class="section-sub">Expand a timestep for full telemetry and actuator payload</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if not logs:
        st.info("Audit trail appears after the first agent decision.")
        return

    for log in reversed(logs[-limit:]):
        step = log.get("step", "?")
        time_str = log.get("time", "--:--")
        with st.expander(f"Step {step}  ·  {time_str}", expanded=False):
            left, right = st.columns(2, gap="large")
            with left:
                st.markdown("**Reasoning**")
                st.write(log.get("llm_reasoning", "—"))
                st.markdown("**Grid context**")
                st.caption(
                    f"Carbon intensity · {log.get('carbon_intensity', '—')} gCO₂/kWh"
                )
                snap = log.get("sensor_snapshot", {})
                st.caption(f"Outdoor · {snap.get('outdoor_temp', '—')} °C")
            with right:
                st.markdown("**Sensor snapshot**")
                st.json(snap if isinstance(snap, dict) else {})
                st.markdown("**Actuator commands**")
                st.json(log.get("actions", []))
