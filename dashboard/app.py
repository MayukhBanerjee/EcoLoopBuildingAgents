"""
EcoLoop Control Panel — Streamlit ops console.

Light industrial theme: teal savings accent, navy telemetry, IBM Plex type.
Reads real EnergyPlus / agent logs when present; otherwise mock demo data.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dashboard.components.agent_log import render_agent_log, render_audit_trail
from dashboard.components.metrics import render_kpi_row
from dashboard.components.timeline import (
    render_energy_chart,
    render_occupancy_chart,
    render_thermal_chart,
)

st.set_page_config(
    page_title="EcoLoop · Control Panel",
    page_icon="◈",
    layout="wide",
    initial_sidebar_state="collapsed",
)

LOG_PATH = Path("data/logs/agent_decisions.jsonl")
BASELINE_PATH = Path("data/baseline_results/eplusout.csv")
AGENT_PATH = Path("data/agent_results/eplusout.csv")

st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@400;500;600;700&family=Outfit:wght@500;600;700&display=swap');

    :root {
      --canvas: #F0F3F6;
      --surface: #FFFFFF;
      --ink: #0B1220;
      --ink-soft: #334155;
      --muted: #64748B;
      --line: #E2E8F0;
      --teal: #0F766E;
      --navy: #1E3A5F;
      --danger: #B91C1C;
      --amber: #B45309;
      --radius: 14px;
      --shadow: 0 1px 2px rgba(15,23,42,.04), 0 10px 28px rgba(15,23,42,.05);
    }

    .stApp {
      background:
        radial-gradient(1200px 500px at 8% -10%, rgba(15,118,110,.07), transparent 55%),
        radial-gradient(900px 420px at 100% 0%, rgba(30,58,95,.06), transparent 50%),
        var(--canvas) !important;
      color: var(--ink) !important;
      font-family: "IBM Plex Sans", "Segoe UI", sans-serif !important;
    }

    header, footer, #MainMenu, .stDeployButton { visibility: hidden !important; display: none !important; }

    div.block-container {
      padding: 1.4rem 2.2rem 2rem !important;
      max-width: 1440px !important;
    }

    div[data-testid="stHorizontalBlock"] { gap: 1.1rem !important; }

    /* Header */
    .hero {
      display: flex;
      justify-content: space-between;
      align-items: flex-end;
      gap: 1.25rem;
      margin-bottom: 1.35rem;
      padding-bottom: 1rem;
      border-bottom: 1px solid var(--line);
    }
    .brand-mark {
      display: inline-flex;
      align-items: center;
      gap: .55rem;
      margin-bottom: .35rem;
    }
    .brand-glyph {
      width: 28px; height: 28px;
      border-radius: 8px;
      background: linear-gradient(145deg, #0F766E, #1E3A5F);
      color: #fff;
      font-family: "Outfit", sans-serif;
      font-weight: 700;
      font-size: 14px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      letter-spacing: -0.02em;
    }
    .brand-kicker {
      font-size: .72rem;
      font-weight: 600;
      letter-spacing: .14em;
      text-transform: uppercase;
      color: var(--muted);
    }
    .hero-title {
      font-family: "Outfit", "IBM Plex Sans", sans-serif !important;
      font-size: 2rem !important;
      font-weight: 700 !important;
      letter-spacing: -0.035em !important;
      color: var(--ink) !important;
      line-height: 1.1 !important;
      margin: 0 !important;
    }
    .hero-sub {
      margin-top: .4rem;
      color: var(--muted);
      font-size: .92rem;
      font-weight: 400;
    }
    .status-pill {
      display: inline-flex;
      align-items: center;
      gap: .45rem;
      padding: .45rem .8rem;
      border-radius: 999px;
      background: #fff;
      border: 1px solid var(--line);
      box-shadow: var(--shadow);
      font-size: .78rem;
      font-weight: 600;
      color: var(--ink-soft);
      white-space: nowrap;
    }
    .status-dot {
      width: 8px; height: 8px;
      border-radius: 50%;
      background: var(--teal);
      box-shadow: 0 0 0 3px rgba(15,118,110,.18);
      animation: pulse 2s ease-in-out infinite;
    }
    .status-dot.sim {
      background: var(--amber);
      box-shadow: 0 0 0 3px rgba(180,83,9,.16);
    }
    @keyframes pulse {
      0%, 100% { opacity: 1; }
      50% { opacity: .55; }
    }

    /* KPI strip */
    .kpi-strip {
      display: grid;
      grid-template-columns: repeat(5, minmax(0, 1fr));
      gap: 12px;
      margin-bottom: 1.15rem;
    }
    .kpi-card {
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      padding: 1rem 1.1rem 1.05rem;
      box-shadow: var(--shadow);
      position: relative;
      overflow: hidden;
    }
    .kpi-card::before {
      content: "";
      position: absolute;
      left: 0; top: 0; bottom: 0;
      width: 3px;
      background: #CBD5E1;
    }
    .kpi-hero::before { background: var(--teal); }
    .kpi-label {
      font-size: .68rem;
      font-weight: 600;
      letter-spacing: .08em;
      text-transform: uppercase;
      color: var(--muted);
      margin-bottom: .35rem;
    }
    .kpi-value {
      font-family: "Outfit", "IBM Plex Sans", sans-serif;
      font-size: 1.85rem;
      font-weight: 700;
      letter-spacing: -0.03em;
      color: var(--ink);
      line-height: 1.05;
    }
    .kpi-value.teal { color: var(--teal); }
    .kpi-value.navy { color: var(--navy); }
    .kpi-value.danger { color: var(--danger); }
    .kpi-unit {
      font-size: .95rem;
      font-weight: 500;
      color: var(--muted);
      margin-left: .25rem;
    }
    .kpi-hint {
      margin-top: .55rem;
      font-size: .78rem;
      color: var(--muted);
      font-weight: 500;
    }
    .progress-track {
      margin-top: .7rem;
      height: 5px;
      border-radius: 999px;
      background: #E2E8F0;
      overflow: hidden;
    }
    .progress-fill {
      height: 100%;
      background: linear-gradient(90deg, #0F766E, #1E3A5F);
      border-radius: 999px;
    }

    /* Panels */
    .panel {
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      box-shadow: var(--shadow);
      padding: 1.05rem 1.15rem 1rem;
      margin-bottom: 1rem;
    }
    .panel-head {
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      margin-bottom: .65rem;
    }
    .panel-title {
      font-family: "Outfit", sans-serif;
      font-size: 1rem;
      font-weight: 600;
      letter-spacing: -0.02em;
      color: var(--ink);
    }
    .panel-sub {
      font-size: .78rem;
      color: var(--muted);
      font-weight: 500;
    }

    /* Feed */
    .feed-shell {
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      box-shadow: var(--shadow);
      overflow: hidden;
      min-height: 560px;
    }
    .feed-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 1rem 1.1rem;
      border-bottom: 1px solid var(--line);
      background: linear-gradient(180deg, #FBFCFD, #F7F9FB);
    }
    .feed-title {
      font-family: "Outfit", sans-serif;
      font-size: 1rem;
      font-weight: 600;
      color: var(--ink);
      letter-spacing: -0.02em;
    }
    .feed-sub { font-size: .75rem; color: var(--muted); margin-top: .15rem; }
    .feed-step {
      font-family: "IBM Plex Mono", monospace;
      font-size: 1.05rem;
      font-weight: 600;
      color: var(--navy);
    }
    .feed-step span { color: var(--muted); font-weight: 500; }
    .feed-scroll {
      max-height: 500px;
      overflow-y: auto;
      padding: .35rem .85rem 1rem;
    }
    .feed-row {
      padding: .85rem .2rem;
      border-bottom: 1px solid #F1F5F9;
    }
    .feed-row:last-child { border-bottom: none; }
    .feed-meta {
      display: flex;
      flex-wrap: wrap;
      gap: .45rem;
      align-items: center;
      margin-bottom: .4rem;
    }
    .feed-time {
      font-family: "IBM Plex Mono", monospace;
      font-size: .78rem;
      font-weight: 600;
      color: var(--ink);
    }
    .feed-body {
      font-size: .86rem;
      line-height: 1.5;
      color: var(--ink-soft);
    }
    .feed-cmd {
      margin-top: .4rem;
      font-family: "IBM Plex Mono", monospace;
      font-size: .76rem;
      font-weight: 500;
      color: var(--teal);
      background: #F0FDFA;
      border: 1px solid #CCFBF1;
      border-radius: 6px;
      padding: .28rem .5rem;
      display: inline-block;
    }
    .clamp-line {
      margin-top: .45rem;
      font-size: .78rem;
      font-weight: 600;
      color: var(--danger);
      background: #FEF2F2;
      border-left: 3px solid var(--danger);
      padding: .35rem .55rem;
      border-radius: 0 6px 6px 0;
    }
    .feed-empty {
      padding: 2.5rem 1.2rem;
      text-align: center;
      color: var(--muted);
      font-size: .9rem;
    }
    .badge {
      display: inline-block;
      padding: .15rem .5rem;
      border-radius: 999px;
      font-size: .65rem;
      font-weight: 700;
      letter-spacing: .04em;
    }
    .badge-ok {
      background: #ECFDF5;
      color: #0F766E;
      border: 1px solid #A7F3D0;
    }
    .badge-warn {
      background: #FFF7ED;
      color: #C2410C;
      border: 1px solid #FED7AA;
    }

    .section-head { margin: .4rem 0 1rem; }
    .section-title {
      font-family: "Outfit", sans-serif;
      font-size: 1.05rem;
      font-weight: 600;
      color: var(--ink);
      letter-spacing: -0.02em;
    }
    .section-sub { font-size: .8rem; color: var(--muted); margin-top: .2rem; }

    .audit-shell {
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      box-shadow: var(--shadow);
      padding: 1.1rem 1.2rem 1.2rem;
      margin-top: .25rem;
    }

    .footer-bar {
      display: flex;
      justify-content: space-between;
      gap: 1rem;
      margin-top: 1.25rem;
      padding-top: .9rem;
      border-top: 1px solid var(--line);
      font-size: .75rem;
      color: var(--muted);
      font-weight: 500;
    }

    /* Controls */
    .stButton > button {
      background: #fff !important;
      color: var(--ink) !important;
      border: 1px solid var(--line) !important;
      border-radius: 10px !important;
      padding: .55rem 1rem !important;
      font-family: "IBM Plex Sans", sans-serif !important;
      font-size: .84rem !important;
      font-weight: 600 !important;
      box-shadow: var(--shadow) !important;
      transition: border-color .15s ease, background .15s ease !important;
    }
    .stButton > button:hover {
      border-color: #0F766E !important;
      background: #F0FDFA !important;
      color: #0F766E !important;
    }

    div[data-testid="stExpander"] {
      background: #F8FAFC;
      border: 1px solid var(--line);
      border-radius: 10px;
      margin-bottom: .55rem;
    }

    @media (max-width: 1100px) {
      .kpi-strip { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .hero { flex-direction: column; align-items: flex-start; }
    }
    @media (max-width: 700px) {
      .kpi-strip { grid-template-columns: 1fr; }
      div.block-container { padding: 1rem !important; }
      .hero-title { font-size: 1.55rem !important; }
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def generate_mock_data():
    steps = 96
    time_index = pd.date_range(start="2026-06-01 00:00", periods=steps, freq="15min")

    hour_profile = np.array(
        [
            10, 10, 9, 9, 9, 9,
            12, 15, 20, 28, 35, 42,
            45, 48, 46, 44, 40, 35,
            32, 28, 22, 16, 12, 10,
        ]
    )
    hour_profile_96 = np.repeat(hour_profile, 4)[:steps]

    np.random.seed(42)
    baseline_watts = hour_profile_96 * 1000 + np.random.normal(0, 800, steps)
    baseline_kwh_timestep = (baseline_watts / 1000) * 0.25
    baseline_kwh_cum = np.cumsum(baseline_kwh_timestep)

    agent_savings_factor = np.array(
        [
            0.30, 0.30, 0.30, 0.30, 0.30, 0.30,
            0.10, 0.08, 0.12, 0.15, 0.14, 0.15,
            0.18, 0.20, 0.22, 0.25, 0.20, 0.15,
            0.15, 0.12, 0.20, 0.25, 0.28, 0.30,
        ]
    )
    agent_savings_factor_96 = np.repeat(agent_savings_factor, 4)[:steps]
    agent_watts = baseline_watts * (1.0 - agent_savings_factor_96)
    agent_kwh_timestep = (agent_watts / 1000) * 0.25
    agent_kwh_cum = np.cumsum(agent_kwh_timestep)

    outdoor_profile = np.array(
        [
            18, 17, 17, 16, 16, 17,
            19, 21, 23, 25, 27, 28,
            29, 30, 30, 29, 28, 27,
            26, 24, 23, 21, 20, 19,
        ]
    )
    outdoor_temp = np.repeat(outdoor_profile, 4)[:steps] + np.random.normal(0, 0.2, steps)

    occ_profile = np.array(
        [
            0, 0, 0, 0, 0, 0,
            0, 2, 8, 25, 28, 30,
            29, 27, 28, 30, 25, 12,
            4, 1, 0, 0, 0, 0,
        ]
    )
    occupancy = np.repeat(occ_profile, 4)[:steps]

    zone_temps, zone_setpoints, pmvs = [], [], []
    for i in range(steps):
        occ = occupancy[i]
        out_t = outdoor_temp[i]
        hour = i // 4
        setpoint = 27.0 if occ == 0 else (24.5 if hour >= 18 or hour <= 8 else 23.0)
        if occ == 0:
            temp = min(25.5 + 0.05 * (out_t - 20) + np.random.normal(0, 0.1), setpoint)
        else:
            temp = setpoint + np.random.normal(0, 0.15)
        zone_temps.append(temp)
        zone_setpoints.append(setpoint)
        pmvs.append(0.3 * (temp - 23.5))

    df_timeline = pd.DataFrame(
        {
            "timestamp": time_index,
            "step": np.arange(1, steps + 1),
            "baseline_kwh_cum": baseline_kwh_cum,
            "agent_kwh_cum": agent_kwh_cum,
            "outdoor_temp": outdoor_temp,
            "occupancy": occupancy,
            "zone_temp": zone_temps,
            "zone_setpoint": zone_setpoints,
            "pmv": pmvs,
        }
    )

    carbon_intensity_profile = [
        680, 675, 670, 665, 660, 665,
        670, 660, 630, 590, 550, 520,
        500, 495, 505, 530, 570, 630,
        700, 730, 740, 725, 705, 690,
    ]

    mock_logs = []
    for i in range(1, steps + 1):
        hour = (i - 1) // 4
        minute = ((i - 1) % 4) * 15
        time_str = f"{hour:02d}:{minute:02d}"
        occ = occupancy[i - 1]
        temp = zone_temps[i - 1]
        carbon = carbon_intensity_profile[hour % 24]

        if occ == 0:
            reasoning = (
                "Zone unoccupied — relaxing cooling to 27.0°C and cutting lights "
                "to shed idle load."
            )
            actions = [
                {"tool": "set_hvac_setpoint", "zone": "SPACE1-1", "cooling": 27.0, "heating": 16.0},
                {"tool": "set_lighting_level", "zone": "SPACE1-1", "level": 0.0},
            ]
        elif carbon >= 650:
            reasoning = (
                f"Grid carbon high ({carbon} gCO₂/kWh). Holding 24.5°C cooling "
                "to cut demand while staying inside PMV band."
            )
            actions = [
                {"tool": "set_hvac_setpoint", "zone": "SPACE1-1", "cooling": 24.5, "heating": 18.0},
                {"tool": "set_lighting_level", "zone": "SPACE1-1", "level": 0.6},
            ]
        else:
            reasoning = (
                "Occupied zone on a clean grid hour — restoring 23.0°C cooling "
                "and optimized lighting at 0.8."
            )
            actions = [
                {"tool": "set_hvac_setpoint", "zone": "SPACE1-1", "cooling": 23.0, "heating": 20.0},
                {"tool": "set_lighting_level", "zone": "SPACE1-1", "level": 0.8},
            ]

        has_clamp = i in (20, 45)
        clamp_desc = ""
        if i == 20:
            clamp_desc = "INV-4 · Ramp limit: 22.0→26.5°C rejected; clamped to 24.0°C."
        elif i == 45:
            clamp_desc = "INV-5 · Lights off while occupied; minimum 0.3 enforced."

        mock_logs.append(
            {
                "step": i,
                "time": time_str,
                "sensor_snapshot": {
                    "outdoor_temp": round(float(outdoor_temp[i - 1]), 1),
                    "zone_temperatures": {"SPACE1-1": round(float(temp), 1)},
                    "occupancy": {"SPACE1-1": int(occ)},
                    "co2": {"SPACE1-1": int(400 + occ * 18 + np.random.normal(0, 10))},
                },
                "llm_reasoning": reasoning,
                "actions": actions,
                "carbon_intensity": carbon,
                "has_clamp": has_clamp,
                "clamp_desc": clamp_desc,
            }
        )

    return df_timeline, mock_logs


@st.cache_data(ttl=3)
def get_dashboard_data():
    real_data_exists = BASELINE_PATH.exists() and AGENT_PATH.exists() and LOG_PATH.exists()
    if not real_data_exists:
        df, logs = generate_mock_data()
        return df, logs, "simulated", "Demo data — run the closed loop for live telemetry"

    try:
        df_base = pd.read_csv(BASELINE_PATH)
        df_agent = pd.read_csv(AGENT_PATH)
        logs = []
        with open(LOG_PATH, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    logs.append(json.loads(line))

        base_col = [c for c in df_base.columns if "Electricity:Facility" in c]
        agent_col = [c for c in df_agent.columns if "Electricity:Facility" in c]
        if not base_col or not agent_col:
            df, logs = generate_mock_data()
            return df, logs, "simulated", "Fallback — energy columns missing in CSV"

        base_kwh = df_base[base_col[0]].values * 2.77778e-7
        agent_kwh = df_agent[agent_col[0]].values * 2.77778e-7
        steps = len(df_base)
        time_index = pd.date_range(start="2026-06-01 00:00", periods=steps, freq="15min")

        out_temp_col = [c for c in df_base.columns if "Outdoor" in c or "Drybulb" in c]
        mean_air = [c for c in df_agent.columns if "Mean Air" in c]
        cool_sp = [c for c in df_agent.columns if "Cooling Setpoint" in c]

        df_timeline = pd.DataFrame(
            {
                "timestamp": time_index[:steps],
                "step": np.arange(1, steps + 1),
                "baseline_kwh_cum": np.cumsum(base_kwh),
                "agent_kwh_cum": np.cumsum(agent_kwh),
                "outdoor_temp": df_base[out_temp_col[0]].values if out_temp_col else np.zeros(steps),
                "zone_temp": df_agent[mean_air[0]].values if mean_air else np.zeros(steps),
                "zone_setpoint": df_agent[cool_sp[0]].values if cool_sp else np.zeros(steps),
                "occupancy": np.zeros(steps),
            }
        )
        df_timeline["pmv"] = 0.3 * (df_timeline["zone_temp"] - 23.5)
        return df_timeline, logs, "live", "Physical AI runtime · EnergyPlus linked"
    except Exception as exc:  # noqa: BLE001
        df, logs = generate_mock_data()
        return df, logs, "simulated", f"Fallback — {exc}"


df, logs, mode_kind, mode_label = get_dashboard_data()
steps_completed = len(logs)

baseline_total = float(df["baseline_kwh_cum"].iloc[-1])
agent_total = float(df["agent_kwh_cum"].iloc[-1])
savings_pct = ((baseline_total - agent_total) / baseline_total) * 100 if baseline_total else 0.0
comfort_pct = (np.abs(df["pmv"]) <= 0.5).mean() * 100
clamps_count = sum(1 for log in logs if log.get("has_clamp", False))
status_dot_cls = "status-dot" if mode_kind == "live" else "status-dot sim"
status_text = "LIVE LOOP" if mode_kind == "live" else "SIM DEMO"

# --- Header ---
h1, h2 = st.columns([4.2, 1.1], vertical_alignment="bottom")
with h1:
    st.markdown(
        f"""
        <div class="hero" style="border:none;margin:0;padding:0;">
          <div>
            <div class="brand-mark">
              <div class="brand-glyph">E</div>
              <div class="brand-kicker">EcoLoop · Building Agent</div>
            </div>
            <div class="hero-title">Control Panel</div>
            <div class="hero-sub">{mode_label}</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
with h2:
    st.markdown(
        f"""
        <div style="display:flex;justify-content:flex-end;margin-bottom:.45rem;">
          <div class="status-pill"><span class="{status_dot_cls}"></span>{status_text}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if st.button("↻ Sync state", width="stretch", key="sync_btn"):
        get_dashboard_data.clear()
        st.rerun()

render_kpi_row(
    savings_pct=savings_pct,
    comfort_pct=comfort_pct,
    agent_kwh=agent_total,
    baseline_kwh=baseline_total,
    clamps_count=clamps_count,
    steps_completed=steps_completed,
)

left, right = st.columns([1.35, 1], gap="medium")

with left:
    st.markdown(
        """
        <div class="panel">
          <div class="panel-head">
            <div class="panel-title">Cumulative energy</div>
            <div class="panel-sub">Baseline vs AI · shaded gap = savings</div>
          </div>
        """,
        unsafe_allow_html=True,
    )
    render_energy_chart(df)
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown(
        """
        <div class="panel">
          <div class="panel-head">
            <div class="panel-title">Thermal control</div>
            <div class="panel-sub">Zone · setpoint · outdoor</div>
          </div>
        """,
        unsafe_allow_html=True,
    )
    render_thermal_chart(df)
    st.markdown("</div>", unsafe_allow_html=True)

    if "occupancy" in df.columns and df["occupancy"].sum() > 0:
        st.markdown(
            """
            <div class="panel">
              <div class="panel-head">
                <div class="panel-title">Occupancy profile</div>
                <div class="panel-sub">People count across the simulated day</div>
              </div>
            """,
            unsafe_allow_html=True,
        )
        render_occupancy_chart(df)
        st.markdown("</div>", unsafe_allow_html=True)

with right:
    render_agent_log(logs, total_steps=96, limit=14)

st.markdown('<div class="audit-shell">', unsafe_allow_html=True)
render_audit_trail(logs, limit=5)
st.markdown("</div>", unsafe_allow_html=True)

st.markdown(
    """
    <div class="footer-bar">
      <div>EnergyPlus V26.1 · Python 3.10+ · Groq (Llama 3.3) · MCP tools</div>
      <div>Honeywell Campus Hackathon · Mayukh Banerjee</div>
    </div>
    """,
    unsafe_allow_html=True,
)
