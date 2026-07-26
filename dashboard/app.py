"""
EcoLoop Control Panel — Streamlit ops console.

Light industrial theme from feature/dashboard:
  teal savings accent, navy telemetry, IBM Plex + Outfit type.

Prefers Phase-5 comparison artifacts under data/comparison/.
Falls back to mock demo data when those files are missing.
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

from dashboard.components.about import show_about_dialog
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

COMPARISON = ROOT / "data" / "comparison"

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

    .feed-shell {
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      box-shadow: var(--shadow);
      overflow: hidden;
    }
    /* Plotly charts sit under self-contained panel headers (no open/close HTML wrappers) */
    div[data-testid="stVerticalBlockBorderWrapper"] {
      background: var(--surface);
      border: 1px solid var(--line) !important;
      border-radius: var(--radius) !important;
      box-shadow: var(--shadow);
      padding: .35rem .55rem .15rem;
      margin-bottom: 1rem;
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
        [10, 10, 9, 9, 9, 9, 12, 15, 20, 28, 35, 42, 45, 48, 46, 44, 40, 35, 32, 28, 22, 16, 12, 10]
    )
    hour_profile_96 = np.repeat(hour_profile, 4)[:steps]
    np.random.seed(42)
    baseline_watts = hour_profile_96 * 1000 + np.random.normal(0, 800, steps)
    baseline_kwh_cum = np.cumsum((baseline_watts / 1000) * 0.25)
    agent_savings = np.repeat(
        np.array(
            [
                0.30, 0.30, 0.30, 0.30, 0.30, 0.30, 0.10, 0.08, 0.12, 0.15, 0.14, 0.15,
                0.18, 0.20, 0.22, 0.25, 0.20, 0.15, 0.15, 0.12, 0.20, 0.25, 0.28, 0.30,
            ]
        ),
        4,
    )[:steps]
    agent_kwh_cum = np.cumsum((baseline_watts * (1.0 - agent_savings) / 1000) * 0.25)
    outdoor_temp = np.repeat(
        np.array([18, 17, 17, 16, 16, 17, 19, 21, 23, 25, 27, 28, 29, 30, 30, 29, 28, 27, 26, 24, 23, 21, 20, 19]),
        4,
    )[:steps] + np.random.normal(0, 0.2, steps)
    occupancy = np.repeat(
        np.array([0, 0, 0, 0, 0, 0, 0, 2, 8, 25, 28, 30, 29, 27, 28, 30, 25, 12, 4, 1, 0, 0, 0, 0]),
        4,
    )[:steps]
    zone_temps, zone_setpoints, pmvs = [], [], []
    for i in range(steps):
        occ = occupancy[i]
        out_t = outdoor_temp[i]
        hour = i // 4
        setpoint = 27.0 if occ == 0 else (24.5 if hour >= 18 or hour <= 8 else 23.0)
        temp = (
            min(25.5 + 0.05 * (out_t - 20) + np.random.normal(0, 0.1), setpoint)
            if occ == 0
            else setpoint + np.random.normal(0, 0.15)
        )
        zone_temps.append(temp)
        zone_setpoints.append(setpoint)
        pmvs.append(0.3 * (temp - 23.5))

    df_timeline = pd.DataFrame(
        {
            "timestamp": time_index,
            "step": np.arange(1, steps + 1),
            "clock": [f"{i // 4:02d}:{(i % 4) * 15:02d}" for i in range(steps)],
            "sim_hour": [i // 4 for i in range(steps)],
            "sim_minute": [(i % 4) * 15 for i in range(steps)],
            "baseline_kwh_cum": baseline_kwh_cum,
            "agent_kwh_cum": agent_kwh_cum,
            "outdoor_temp": outdoor_temp,
            "occupancy": occupancy,
            "zone_temp": zone_temps,
            "zone_setpoint": zone_setpoints,
            "pmv": pmvs,
        }
    )
    mock_logs = []
    for i in range(1, steps + 1):
        hour = (i - 1) // 4
        minute = ((i - 1) % 4) * 15
        occ = occupancy[i - 1]
        temp = zone_temps[i - 1]
        if occ == 0:
            reasoning = "Zone unoccupied — relaxing cooling to 27.0°C and cutting lights."
            actions = [
                {"tool": "set_hvac_setpoint", "zone": "SPACE1-1", "cooling": 27.0, "heating": 16.0},
                {"tool": "set_lighting_level", "zone": "SPACE1-1", "level": 0.0},
            ]
            carbon = 680
        else:
            reasoning = "Occupied zone — holding comfort-edge setpoints."
            actions = [
                {"tool": "set_hvac_setpoint", "zone": "SPACE1-1", "cooling": 24.5, "heating": 20.0},
            ]
            carbon = 520
        mock_logs.append(
            {
                "step": i,
                "time": f"{hour:02d}:{minute:02d}",
                "sensor_snapshot": {
                    "outdoor_temp": round(float(outdoor_temp[i - 1]), 1),
                    "zone_temperatures": {"SPACE1-1": round(float(temp), 1)},
                    "occupancy": {"SPACE1-1": int(occ)},
                },
                "llm_reasoning": reasoning,
                "actions": actions,
                "carbon_intensity": carbon,
                "has_clamp": False,
                "clamp_desc": "",
            }
        )
    kpis = {
        "savings_pct": float(
            (baseline_kwh_cum[-1] - agent_kwh_cum[-1]) / baseline_kwh_cum[-1] * 100
        ),
        "comfort_compliance_pct": float((np.abs(df_timeline["pmv"]) <= 0.5).mean() * 100),
        "agent_kwh": float(agent_kwh_cum[-1]),
        "baseline_kwh": float(baseline_kwh_cum[-1]),
        "total_clamp_events": 0,
        "timesteps_agent": steps,
        "timesteps_baseline": steps,
        "decisions_count": steps,
        "status": "simulated",
        "run_id": "demo",
        "model": "demo",
    }
    return df_timeline, mock_logs, kpis, "simulated", "Demo data — run generate_comparison.py for live results"


@st.cache_data(ttl=5)
def get_dashboard_data():
    kpis_path = COMPARISON / "kpis.json"
    energy_path = COMPARISON / "energy_timeseries.csv"
    zone_path = COMPARISON / "zone_temps.csv"
    decisions_path = COMPARISON / "decisions.jsonl"

    if not kpis_path.is_file() or not energy_path.is_file():
        return generate_mock_data()

    try:
        kpis = json.loads(kpis_path.read_text(encoding="utf-8"))
        energy = pd.read_csv(energy_path)
        energy["agent_kwh_cum"] = pd.to_numeric(energy.get("agent_kwh_cum"), errors="coerce")
        energy["baseline_kwh_cum"] = pd.to_numeric(energy["baseline_kwh_cum"], errors="coerce")

        zone = pd.read_csv(zone_path) if zone_path.is_file() else pd.DataFrame()
        decisions: list[dict] = []
        if decisions_path.is_file():
            for line in decisions_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    decisions.append(json.loads(line))

        # Build timeline frame (SPACE1-1 focus) with clock labels for charts
        keep_cols = ["step", "baseline_kwh_cum", "agent_kwh_cum"]
        for c in ("sim_hour", "sim_minute"):
            if c in energy.columns:
                keep_cols.append(c)
        frame = energy[keep_cols].copy()
        if "sim_hour" in frame.columns and "sim_minute" in frame.columns:
            frame["clock"] = [
                f"{int(h):02d}:{int(m):02d}"
                for h, m in zip(frame["sim_hour"], frame["sim_minute"], strict=False)
            ]
        else:
            frame["clock"] = [
                f"{max(0, int(s) - 1) // 4:02d}:{(max(0, int(s) - 1) % 4) * 15:02d}"
                for s in frame["step"].tolist()
            ]
        if not zone.empty and "zone" in zone.columns:
            z1 = zone[zone["zone"] == "SPACE1-1"].copy()
            if not z1.empty:
                frame = frame.merge(
                    z1[["step", "agent_temp_c", "baseline_temp_c", "agent_occ"]],
                    on="step",
                    how="left",
                )
                frame["zone_temp"] = frame["agent_temp_c"].fillna(frame.get("baseline_temp_c"))
                frame["occupancy"] = pd.to_numeric(frame.get("agent_occ"), errors="coerce").fillna(0)

        by_step = {int(d.get("timestep") or 0): d for d in decisions}
        outdoor, setpoints = [], []
        for step in frame["step"].tolist():
            d = by_step.get(int(step), {})
            snap = d.get("sensor_snapshot") or {}
            outdoor.append(snap.get("outdoor_temp"))
            zones = snap.get("zones") or {}
            z1 = zones.get("SPACE1-1") or {}
            setpoints.append(z1.get("cool_sp"))
        frame["outdoor_temp"] = outdoor
        frame["zone_setpoint"] = setpoints
        if "zone_temp" in frame.columns:
            frame["pmv"] = 0.3 * (pd.to_numeric(frame["zone_temp"], errors="coerce") - 23.5)
        else:
            frame["pmv"] = 0.0

        status = kpis.get("status", "complete")
        mode = "live" if status in ("complete", "partial") else "simulated"
        label = (
            f"Run {kpis.get('run_id')} · {kpis.get('model')}"
            if mode == "live"
            else "Baseline only — agent pending"
        )
        if status == "partial":
            label += " · partial day"
        return frame, decisions, kpis, mode, label
    except Exception as exc:  # noqa: BLE001
        df, logs, kpis, mode, _ = generate_mock_data()
        return df, logs, kpis, "simulated", f"Fallback — {exc}"


df, logs, kpis, mode_kind, mode_label = get_dashboard_data()
steps_completed = int(kpis.get("timesteps_agent") or len(logs) or 0)
total_steps = int(kpis.get("timesteps_baseline") or 96)
status_dot_cls = "status-dot" if mode_kind == "live" else "status-dot sim"
status_text = "LIVE DAY" if mode_kind == "live" else "DEMO DAY"

_has_comparison = (COMPARISON / "kpis.json").is_file() and (COMPARISON / "energy_timeseries.csv").is_file()
if not _has_comparison:
    st.info(
        "No comparison data found — showing demo telemetry. "
        "Run `uv run python scripts/generate_comparison.py` after a closed-loop run to load live KPIs."
    )

saved_kwh = float(kpis.get("baseline_kwh") or 0) - float(kpis.get("agent_kwh") or 0)
savings_pct = float(kpis.get("savings_pct") or 0)
comfort_pct = float(kpis.get("comfort_compliance_pct") or 0)

# --- Header ---
h1, h2 = st.columns([4.0, 1.35], vertical_alignment="bottom")
with h1:
    st.markdown(
        f"""
        <div class="hero" style="border:none;margin:0;padding:0;">
          <div>
            <div class="brand-mark">
              <div class="brand-glyph">E</div>
              <div class="brand-kicker">EcoLoop · Building energy agent</div>
            </div>
            <div class="hero-title">How the building saved energy today</div>
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
    b1, b2 = st.columns(2, gap="small")
    with b1:
        if st.button("About", use_container_width=True, key="about_btn"):
            show_about_dialog()
    with b2:
        if st.button("↻ Refresh", use_container_width=True, key="sync_btn"):
            get_dashboard_data.clear()
            st.rerun()

# --- One-paragraph story for first-time viewers ---
with st.container(border=True):
    st.markdown(
        f"""
**What you're looking at.** EcoLoop is an AI that watches a simulated office every **15 minutes**
and gently turns cooling / heating / lights down when rooms are empty — always behind hard safety limits.
Click **About** (top right) for the full problem, solution, and how every number is calculated.

**Today's impact.** It used **{savings_pct:.1f}% less electricity** ({saved_kwh:.0f} kWh saved vs the normal schedule).
People were in the comfort band **{comfort_pct:.1f}%** of occupied time — the charts below show *when* and *why*.
        """
    )

render_kpi_row(kpis=kpis, total_steps=total_steps)

# Left charts (through occupancy) + right agent feed aligned to that same height.
# "Peek inside a decision" is its own module below occupancy / the chart stack.
RIGHT_PANEL_HEIGHT = 1080
has_occ = (
    "occupancy" in df.columns
    and pd.to_numeric(df["occupancy"], errors="coerce").fillna(0).sum() > 0
)
if not has_occ:
    RIGHT_PANEL_HEIGHT = 820

left, right = st.columns([1.35, 1], gap="medium")

with left:
    with st.container(border=True):
        st.markdown("#### Electricity use across the day")
        st.caption(
            "X-axis = time of day · Y-axis = kWh used so far · "
            "Grey dotted line = normal building schedule · Teal line = EcoLoop · "
            "Shaded gap = energy saved"
        )
        render_energy_chart(df)

    with st.container(border=True):
        st.markdown("#### Room temperature vs the AI’s cooling target")
        st.caption(
            "X-axis = time of day · Y-axis = °C · "
            "Shaded band = comfortable for people (20–26°C) · "
            "When the room is empty, EcoLoop raises the cooling target to stop wasting power"
        )
        render_thermal_chart(df)

    if has_occ:
        with st.container(border=True):
            st.markdown("#### When people were in the building")
            st.caption(
                "X-axis = time of day · Y-axis = people in this zone · "
                "Empty periods are when EcoLoop can safely save the most energy"
            )
            render_occupancy_chart(df)

with right:
    with st.container(height=RIGHT_PANEL_HEIGHT, border=True):
        render_agent_log(logs, total_steps=total_steps, limit=24)

# Separate module — sits under the occupancy chart / chart stack
with st.container(height=420, border=True):
    render_audit_trail(logs, limit=8)

st.markdown(
    """
    <div class="footer-bar">
      <div>Simulated office · EnergyPlus · AI decisions every few steps · safety limits always on</div>
      <div>Honeywell Campus Hackathon · EcoLoop</div>
    </div>
    """,
    unsafe_allow_html=True,
)
