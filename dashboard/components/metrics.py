"""KPI strip for the EcoLoop ops console."""

from __future__ import annotations

import streamlit as st


def render_kpi_row(
    savings_pct: float,
    comfort_pct: float,
    agent_kwh: float,
    baseline_kwh: float,
    clamps_count: int,
    steps_completed: int,
    total_steps: int = 96,
) -> None:
    progress = min(100.0, (steps_completed / total_steps) * 100.0)
    st.markdown(
        f"""
        <div class="kpi-strip">
          <div class="kpi-card kpi-hero">
            <div class="kpi-label">Energy saved</div>
            <div class="kpi-value teal">{savings_pct:.1f}%</div>
            <div class="kpi-hint">vs baseline schedule</div>
          </div>
          <div class="kpi-card">
            <div class="kpi-label">Comfort compliance</div>
            <div class="kpi-value">{comfort_pct:.1f}%</div>
            <div class="kpi-hint">PMV within ±0.5</div>
          </div>
          <div class="kpi-card">
            <div class="kpi-label">Agent demand</div>
            <div class="kpi-value navy">{agent_kwh:.1f}<span class="kpi-unit">kWh</span></div>
            <div class="kpi-hint">baseline {baseline_kwh:.1f} kWh</div>
          </div>
          <div class="kpi-card">
            <div class="kpi-label">Safety clamps</div>
            <div class="kpi-value danger">{clamps_count}</div>
            <div class="kpi-hint">invariants enforced</div>
          </div>
          <div class="kpi-card">
            <div class="kpi-label">Loop progress</div>
            <div class="kpi-value">{steps_completed}<span class="kpi-unit">/{total_steps}</span></div>
            <div class="progress-track"><div class="progress-fill" style="width:{progress:.1f}%"></div></div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
