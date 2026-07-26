"""KPI strip — plain-language impact metrics."""

from __future__ import annotations

from typing import Any

import streamlit as st


def render_kpi_row(
    savings_pct: float | None = None,
    comfort_pct: float | None = None,
    agent_kwh: float | None = None,
    baseline_kwh: float | None = None,
    steps_completed: int = 0,
    total_steps: int = 96,
    *,
    kpis: dict[str, Any] | None = None,
) -> None:
    """Render the KPI strip with first-time-viewer friendly copy."""
    baseline_comfort = None
    comfort_delta = None
    if kpis is not None:
        savings_pct = kpis.get("savings_pct")
        comfort_pct = kpis.get("comfort_compliance_pct")
        agent_kwh = kpis.get("agent_kwh")
        baseline_kwh = kpis.get("baseline_kwh")
        steps_completed = int(kpis.get("timesteps_agent") or kpis.get("decisions_count") or 0)
        total_steps = int(kpis.get("timesteps_baseline") or 96)
        baseline_comfort = kpis.get("baseline_comfort_compliance_pct")
        comfort_delta = kpis.get("comfort_delta_pct")

    savings_pct = 0.0 if savings_pct is None else float(savings_pct)
    agent_kwh = 0.0 if agent_kwh is None else float(agent_kwh)
    baseline_kwh = 0.0 if baseline_kwh is None else float(baseline_kwh)
    saved_kwh = max(0.0, baseline_kwh - agent_kwh)

    progress = min(100.0, (steps_completed / total_steps) * 100.0) if total_steps else 0.0
    hours = total_steps * 0.25  # 15-min steps

    if comfort_pct is None:
        comfort_value = "n/a"
        comfort_hint = "No occupied steps — comfort not measured"
    else:
        comfort_value = f"{float(comfort_pct):.1f}%"
        if baseline_comfort is not None and comfort_delta is not None:
            sign = "+" if float(comfort_delta) >= 0 else ""
            comfort_hint = (
                f"vs baseline {float(baseline_comfort):.1f}% "
                f"({sign}{float(comfort_delta):.1f} pts)"
            )
        else:
            comfort_hint = "Occupied time inside the comfort band"

    st.markdown(
        f"""
        <div class="kpi-strip">
          <div class="kpi-card kpi-hero">
            <div class="kpi-label">Electricity cut</div>
            <div class="kpi-value teal">{savings_pct:.1f}%</div>
            <div class="kpi-hint">{saved_kwh:.0f} kWh less than the normal schedule</div>
          </div>
          <div class="kpi-card">
            <div class="kpi-label">People comfortable</div>
            <div class="kpi-value">{comfort_value}</div>
            <div class="kpi-hint">{comfort_hint}</div>
          </div>
          <div class="kpi-card">
            <div class="kpi-label">Power used today</div>
            <div class="kpi-value navy">{agent_kwh:.1f}<span class="kpi-unit">kWh</span></div>
            <div class="kpi-hint">Normal schedule would use {baseline_kwh:.1f} kWh</div>
          </div>
          <div class="kpi-card">
            <div class="kpi-label">Simulated day</div>
            <div class="kpi-value">{steps_completed}<span class="kpi-unit">/{total_steps}</span></div>
            <div class="kpi-hint">{hours:.0f}-hour day · every 15 minutes</div>
            <div class="progress-track"><div class="progress-fill" style="width:{progress:.1f}%"></div></div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
