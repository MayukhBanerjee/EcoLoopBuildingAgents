"""
app.py — Elite Industrial FinTech Building AI Dashboard.

Color Theme: "The Industrial FinTech Core" (Light Mode - Crisp Slate, Pure White, & Brass Gold).
Palettes:
  - #F8FAFC (Canvas Base Background)
  - #FFFFFF (Solid pure white container cards)
  - #020617 (Primary text & icons - Ink Obsidian)
  - #D4AF37 (Hero Savings Metric - Champagne Gold)
  - #0369A1 (Operational Metrics - Deep Electric Sapphire)
  - #B91C1C (System Invariants / Safety Warnings - Muted Terracotta)

Features:
  - Premium light-mode styling matching modern SaaS metrics (Stripe/Vercel style)
  - Real-time file sync with fallback mock data simulation
  - High-hierarchy sans-serif typography (Inter)
  - Diff Energy Chart (Baseline Sapphire vs Agent Champagne Gold)
  - Safety clamp event feed
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go

# --- PAGE CONFIGURATION ---
st.set_page_config(
    page_title="ecoLoop // Building Management System",
    page_icon="🏢",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# --- DIRECTORY PATHS ---
LOG_PATH = Path("data/logs/agent_decisions.jsonl")
BASELINE_PATH = Path("data/baseline_results/eplusout.csv")
AGENT_PATH = Path("data/agent_results/eplusout.csv")

# --- CUSTOM CSS STYLING (The Industrial FinTech Core) ---
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');

    /* Global Overrides */
    .stApp {
        background-color: #F8FAFC !important;
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif !important;
        color: #020617 !important;
    }
    
    /* Remove Streamlit default white space and headers */
    header, footer {
        visibility: hidden !important;
    }
    
    #MainMenu, .stDeployButton {
        display: none !important;
    }
    
    div.block-container {
        padding-top: 2rem !important;
        padding-bottom: 2rem !important;
    }

    /* Titles & Refined Headers */
    .dashboard-title {
        font-size: 2.1rem;
        font-weight: 800;
        color: #020617;
        letter-spacing: -0.8px;
        margin-bottom: 4px;
        line-height: 1.1;
    }

    .dashboard-subtitle {
        color: #64748B;
        font-size: 0.95rem;
        font-weight: 400;
        letter-spacing: 0.2px;
        margin-top: 0px;
        margin-bottom: 24px;
        border-bottom: 1px solid #E2E8F0;
        padding-bottom: 12px;
    }

    /* Clean Fintech Containers */
    .fintech-card {
        background-color: #FFFFFF !important;
        border: 1px solid #E2E8F0 !important;
        border-radius: 12px !important;
        padding: 24px !important;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05), 0 2px 4px -2px rgba(0, 0, 0, 0.05) !important;
        margin-bottom: 24px !important;
    }

    .fintech-card-header {
        font-size: 1.05rem;
        font-weight: 600;
        color: #020617;
        margin-bottom: 18px;
        letter-spacing: -0.3px;
        display: flex;
        justify-content: space-between;
        align-items: center;
    }

    /* KPI Grid Styling */
    .kpi-container {
        display: flex;
        gap: 16px;
        margin-bottom: 24px;
        width: 100%;
    }

    .kpi-box {
        flex: 1;
        background-color: #FFFFFF;
        border: 1px solid #E2E8F0;
        border-radius: 12px;
        padding: 20px 24px;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05), 0 2px 4px -2px rgba(0, 0, 0, 0.05);
    }

    .kpi-label {
        font-size: 0.75rem;
        font-weight: 600;
        text-transform: uppercase;
        color: #64748B;
        letter-spacing: 0.5px;
        margin-bottom: 6px;
    }

    .kpi-value {
        font-size: 2.1rem;
        font-weight: 800;
        color: #020617;
        line-height: 1.1;
    }

    .kpi-value-gold {
        color: #D4AF37; /* Champagne Gold */
    }

    .kpi-value-sapphire {
        color: #0369A1; /* Deep Electric Sapphire */
    }

    .kpi-value-terracotta {
        color: #B91C1C; /* Terracotta Red */
    }

    .kpi-subtext {
        font-size: 0.8rem;
        color: #64748B;
        margin-top: 4px;
    }

    /* Refined Log Feed */
    .log-feed-window {
        background-color: #FFFFFF;
        border: 1px solid #E2E8F0;
        border-radius: 12px;
        padding: 20px;
        max-height: 520px;
        min-height: 520px;
        overflow-y: auto;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
    }

    .log-feed-header {
        border-bottom: 1px solid #E2E8F0;
        padding-bottom: 10px;
        margin-bottom: 16px;
        display: flex;
        justify-content: space-between;
        align-items: center;
        color: #020617;
        font-size: 0.9rem;
        font-weight: 600;
    }

    .log-feed-row {
        margin-bottom: 14px;
        padding-bottom: 14px;
        border-bottom: 1px solid #F1F5F9;
        font-size: 0.85rem;
        line-height: 1.55;
        color: #334155;
    }

    .log-feed-row:last-child {
        border-bottom: none;
        margin-bottom: 0;
        padding-bottom: 0;
    }

    .log-timestamp {
        font-weight: 600;
        color: #020617;
        margin-right: 8px;
    }

    .log-section-label {
        font-weight: 600;
        color: #475569;
        margin-right: 4px;
    }

    .badge {
        display: inline-block;
        padding: 2px 8px;
        border-radius: 4px;
        font-size: 0.7rem;
        font-weight: 600;
        text-transform: uppercase;
        margin-right: 6px;
    }

    .badge-sapphire {
        background-color: #E0F2FE;
        color: #0369A1;
        border: 1px solid #BAE6FD;
    }

    .badge-gold {
        background-color: #FEF3C7;
        color: #B45309;
        border: 1px solid #FDE68A;
    }

    .badge-terracotta {
        background-color: #FEE2E2;
        color: #B91C1C;
        border: 1px solid #FCA5A5;
    }

    /* Custom Streamlit Expander styling overrides */
    .streamlit-expanderHeader {
        background-color: #FFFFFF !important;
        border: 1px solid #E2E8F0 !important;
        border-radius: 6px !important;
        color: #020617 !important;
        font-weight: 500 !important;
    }
    
    /* Ghost Button Styles */
    .stButton>button {
        background-color: transparent !important;
        color: #020617 !important;
        border: 1px solid #CBD5E1 !important;
        border-radius: 6px !important;
        padding: 6px 16px !important;
        font-size: 0.85rem !important;
        font-weight: 500 !important;
        transition: all 0.2s ease !important;
    }
    
    .stButton>button:hover {
        background-color: #F1F5F9 !important;
        border-color: #94A3B8 !important;
    }
    </style>
    """,
    unsafe_allow_html=True
)

# --- MOCK DATA GENERATOR ---
def generate_mock_data():
    steps = 96
    time_index = pd.date_range(start="2026-06-01 00:00", periods=steps, freq="15min")
    
    # Energy base profile: peak midday, low at night
    hour_profile = np.array([
        10, 10, 9, 9, 9, 9,           # 00:00 - 05:00
        12, 15, 20, 28, 35, 42,       # 06:00 - 11:00
        45, 48, 46, 44, 40, 35,       # 12:00 - 17:00
        32, 28, 22, 16, 12, 10        # 18:00 - 23:00
    ])
    hour_profile_96 = np.repeat(hour_profile, 4)[:steps]
    
    # Add random noise to baseline
    np.random.seed(42)
    baseline_watts = hour_profile_96 * 1000 + np.random.normal(0, 800, steps)
    baseline_kwh_timestep = (baseline_watts / 1000) * 0.25
    baseline_kwh_cum = np.cumsum(baseline_kwh_timestep)
    
    # Agent saves energy (average ~19.1% savings)
    agent_savings_factor = np.array([
        0.30, 0.30, 0.30, 0.30, 0.30, 0.30,
        0.10, 0.08, 0.12, 0.15, 0.14, 0.15,
        0.18, 0.20, 0.22, 0.25, 0.20, 0.15,
        0.15, 0.12, 0.20, 0.25, 0.28, 0.30
    ])
    agent_savings_factor_96 = np.repeat(agent_savings_factor, 4)[:steps]
    agent_watts = baseline_watts * (1.0 - agent_savings_factor_96)
    agent_kwh_timestep = (agent_watts / 1000) * 0.25
    agent_kwh_cum = np.cumsum(agent_kwh_timestep)
    
    # Outdoor temp profile
    outdoor_profile = np.array([
        18, 17, 17, 16, 16, 17,
        19, 21, 23, 25, 27, 28,
        29, 30, 30, 29, 28, 27,
        26, 24, 23, 21, 20, 19
    ])
    outdoor_temp = np.repeat(outdoor_profile, 4)[:steps] + np.random.normal(0, 0.2, steps)
    
    # Occupancy profile
    occ_profile = np.array([
        0, 0, 0, 0, 0, 0,
        0, 2, 8, 25, 28, 30,
        29, 27, 28, 30, 25, 12,
        4, 1, 0, 0, 0, 0
    ])
    occupancy = np.repeat(occ_profile, 4)[:steps]
    
    # Zone Temps
    zone_temps = []
    zone_setpoints = []
    pmvs = []
    
    for i in range(steps):
        occ = occupancy[i]
        out_t = outdoor_temp[i]
        
        if occ == 0:
            setpoint = 27.0
        else:
            hour = i // 4
            if hour >= 18 or hour <= 8:
                setpoint = 24.5
            else:
                setpoint = 23.0
                
        if occ == 0:
            temp = 25.5 + 0.05 * (out_t - 20) + np.random.normal(0, 0.1)
            temp = min(temp, setpoint)
        else:
            temp = setpoint + np.random.normal(0, 0.15)
            
        zone_temps.append(temp)
        zone_setpoints.append(setpoint)
        
        pmv_val = 0.3 * (temp - 23.5)
        pmvs.append(pmv_val)

    # Compile dataframes
    df_timeline = pd.DataFrame({
        "timestamp": time_index,
        "step": np.arange(1, steps + 1),
        "baseline_watts": baseline_watts,
        "baseline_kwh_cum": baseline_kwh_cum,
        "agent_watts": agent_watts,
        "agent_kwh_cum": agent_kwh_cum,
        "outdoor_temp": outdoor_temp,
        "occupancy": occupancy,
        "zone_temp": zone_temps,
        "zone_setpoint": zone_setpoints,
        "pmv": pmvs
    })
    
    mock_logs = []
    carbon_intensity_profile = [
        680, 675, 670, 665, 660, 665,
        670, 660, 630, 590, 550, 520,
        500, 495, 505, 530, 570, 630,
        700, 730, 740, 725, 705, 690
    ]
    
    for i in range(1, steps + 1):
        hour = (i - 1) // 4
        minute = ((i - 1) % 4) * 15
        time_str = f"{hour:02d}:{minute:02d}"
        occ = occupancy[i-1]
        temp = zone_temps[i-1]
        sp = zone_setpoints[i-1]
        co2 = 400 + occ * 18 + int(np.random.normal(0, 10))
        carbon = carbon_intensity_profile[hour % 24]
        
        reasoning = ""
        actions = []
        
        if occ == 0:
            reasoning = f"Zone is unoccupied. Relaxing cooling setpoint to 27.0°C to shed load and shutting off illumination to optimize inactive state."
            actions = [
                {"tool": "set_hvac_setpoint", "zone": "SPACE1-1", "cooling": 27.0, "heating": 16.0},
                {"tool": "set_lighting_level", "zone": "SPACE1-1", "level": 0.0}
            ]
        else:
            if carbon >= 650:
                reasoning = f"Carbon intensity is high ({carbon} gCO2/kWh). Shifting cooling setpoint to 24.5°C to conserve energy while securing PMV comfort guidelines."
                actions = [
                    {"tool": "set_hvac_setpoint", "zone": "SPACE1-1", "cooling": 24.5, "heating": 18.0},
                    {"tool": "set_lighting_level", "zone": "SPACE1-1", "level": 0.6}
                ]
            else:
                reasoning = f"Occupancy detected. Restoring target cooling setpoint to 23.0°C. Workspace illumination set to optimized 0.8 scale."
                actions = [
                    {"tool": "set_hvac_setpoint", "zone": "SPACE1-1", "cooling": 23.0, "heating": 20.0},
                    {"tool": "set_lighting_level", "zone": "SPACE1-1", "level": 0.8}
                ]
                
        has_clamp = False
        clamp_desc = ""
        if i == 20:
            has_clamp = True
            clamp_desc = "[INV-4 Enforced] Actuator setpoint change from 22.0°C to 26.5°C violates ramp limits. Clamped target to 24.0°C."
        elif i == 45:
            has_clamp = True
            clamp_desc = "[INV-5 Enforced] Lights deactivated in occupied zone. Minimum safe level (0.3) applied."
            
        mock_logs.append({
            "step": i,
            "time": time_str,
            "sensor_snapshot": {
                "outdoor_temp": round(outdoor_temp[i-1], 1),
                "zone_temperatures": {"SPACE1-1": round(temp, 1)},
                "occupancy": {"SPACE1-1": int(occ)},
                "co2": {"SPACE1-1": co2}
            },
            "llm_reasoning": reasoning,
            "actions": actions,
            "carbon_intensity": carbon,
            "has_clamp": has_clamp,
            "clamp_desc": clamp_desc
        })
        
    return df_timeline, mock_logs

# --- LOADING ENGINE ---
@st.cache_data(ttl=3)
def get_dashboard_data():
    real_data_exists = (
        BASELINE_PATH.exists() and 
        AGENT_PATH.exists() and 
        LOG_PATH.exists()
    )
    
    if not real_data_exists:
        df, logs = generate_mock_data()
        mode = "simulated runtime mode"
        return df, logs, mode
    
    try:
        # Load Baseline
        df_base = pd.read_csv(BASELINE_PATH)
        # Load Agent
        df_agent = pd.read_csv(AGENT_PATH)
        
        # Load JSONL logs
        logs = []
        with open(LOG_PATH, "r") as f:
            for line in f:
                if line.strip():
                    logs.append(json.loads(line))
        
        base_col = [c for c in df_base.columns if "Electricity:Facility" in c or "Electricity:Facility [J](TimeStep)" in c]
        agent_col = [c for c in df_agent.columns if "Electricity:Facility" in c or "Electricity:Facility [J](TimeStep)" in c]
        
        if not base_col or not agent_col:
            df, logs, _ = generate_mock_data()
            return df, logs, "simulated fallback mode"
            
        base_energy_j = df_base[base_col[0]].values
        agent_energy_j = df_agent[agent_col[0]].values
        
        base_kwh_timestep = base_energy_j * 2.77778e-7
        agent_kwh_timestep = agent_energy_j * 2.77778e-7
        
        steps = len(df_base)
        time_index = pd.date_range(start="2026-06-01 00:00", periods=steps, freq="15min")
        
        out_temp_col = [c for c in df_base.columns if "Outdoor" in c or "Drybulb" in c]
        out_temp = df_base[out_temp_col[0]].values if out_temp_col else np.zeros(steps)
        
        df_timeline = pd.DataFrame({
            "timestamp": time_index[:steps],
            "step": np.arange(1, steps + 1),
            "baseline_kwh_cum": np.cumsum(base_kwh_timestep),
            "agent_kwh_cum": np.cumsum(agent_kwh_timestep),
            "outdoor_temp": out_temp,
            "zone_temp": df_agent[[c for c in df_agent.columns if "Mean Air" in c][0]].values if [c for c in df_agent.columns if "Mean Air" in c] else np.zeros(steps),
            "zone_setpoint": df_agent[[c for c in df_agent.columns if "Cooling Setpoint" in c][0]].values if [c for c in df_agent.columns if "Cooling Setpoint" in c] else np.zeros(steps),
        })
        
        df_timeline["pmv"] = 0.3 * (df_timeline["zone_temp"] - 23.5)
        df_timeline["occupancy"] = 0
        
        return df_timeline, logs, "physical AI runtime active"
    except Exception as e:
        df, logs, _ = generate_mock_data()
        return df, logs, f"simulated fallback mode"

# Load Data
df, logs, data_mode = get_dashboard_data()
steps_completed = len(logs)

# --- HEADER SECTION ---
col_head_title, col_head_meta = st.columns([3, 1])

with col_head_title:
    st.markdown('<div class="dashboard-title">ecoloop control panel</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="dashboard-subtitle">Smart building closed-loop energy optimization // Source: {data_mode}</div>', unsafe_allow_html=True)

with col_head_meta:
    # Sleek ghost button with thin border & refresh icon
    st.button("⟳ Synchronize state", key="sync_button", width="stretch")

# --- CALCULATIONS ---
baseline_total_kwh = df["baseline_kwh_cum"].iloc[-1]
agent_total_kwh = df["agent_kwh_cum"].iloc[-1]
net_savings_pct = ((baseline_total_kwh - agent_total_kwh) / baseline_total_kwh) * 100

comfort_steps = df[np.abs(df["pmv"]) <= 0.5]
comfort_compliance_pct = (len(comfort_steps) / len(df)) * 100

clamps_count = sum(1 for log in logs if log.get("has_clamp", False))

# --- KPI METRICS ROW ---
st.markdown(
    f"""
    <div class="kpi-container">
        <div class="kpi-box">
            <div class="kpi-label">Realized energy savings</div>
            <div class="kpi-value kpi-value-gold">{net_savings_pct:.1f}%</div>
            <div class="kpi-subtext">Reduction in total kWh vs schedule</div>
        </div>
        <div class="kpi-box">
            <div class="kpi-label">Comfort compliance</div>
            <div class="kpi-value">{comfort_compliance_pct:.1f}%</div>
            <div class="kpi-subtext">PMV index within comfortable limits</div>
        </div>
        <div class="kpi-box">
            <div class="kpi-label">AI operational demand</div>
            <div class="kpi-value kpi-value-sapphire">{agent_total_kwh:.1f} <span style="font-size:1.1rem; font-weight:500; color:#64748B;">kWh</span></div>
            <div class="kpi-subtext">Baseline standard load: {baseline_total_kwh:.1f} kWh</div>
        </div>
        <div class="kpi-box">
            <div class="kpi-label">Safety clamp overrides</div>
            <div class="kpi-value kpi-value-terracotta">{clamps_count}</div>
            <div class="kpi-subtext">Active system invariants enforced</div>
        </div>
    </div>
    """,
    unsafe_allow_html=True
)

# --- MAIN DASHBOARD LAYOUT ---
col_charts, col_terminal = st.columns([7, 5])

with col_charts:
    # 1. Energy Cumulative Chart
    st.markdown('<div class="fintech-card">', unsafe_allow_html=True)
    st.markdown('<div class="fintech-card-header">Cumulative energy load</div>', unsafe_allow_html=True)
    
    fig_energy = go.Figure()
    
    # Baseline line (Slate - Standard baseline operation)
    fig_energy.add_trace(go.Scatter(
        x=df["step"],
        y=df["baseline_kwh_cum"],
        name="Baseline load profile",
        line=dict(color="#64748B", width=2, dash="dash"),
        mode="lines"
    ))
    # Agent line (Champagne Gold - AI optimized value)
    fig_energy.add_trace(go.Scatter(
        x=df["step"],
        y=df["agent_kwh_cum"],
        name="AI optimized profile",
        line=dict(color="#D4AF37", width=2.5),
        fill='tonexty',
        fillcolor='rgba(212, 175, 55, 0.05)', # Elegant shading for savings gap
        mode="lines"
    ))
    
    fig_energy.update_layout(
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
        margin=dict(l=10, r=10, t=10, b=10),
        height=220,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1, font=dict(color="#020617", size=10)),
        xaxis=dict(gridcolor="#E2E8F0", tickfont=dict(color="#64748B", size=10), title=dict(text="Timestep (15-min)", font=dict(color="#64748B", size=10))),
        yaxis=dict(gridcolor="#E2E8F0", tickfont=dict(color="#64748B", size=10), title=dict(text="Load (kWh)", font=dict(color="#64748B", size=10)))
    )
    st.plotly_chart(fig_energy, width="stretch", config={"displayModeBar": False})
    st.markdown('</div>', unsafe_allow_html=True)

    # 2. Zone Temperature & Setpoint Modulation
    st.markdown('<div class="fintech-card">', unsafe_allow_html=True)
    st.markdown('<div class="fintech-card-header">Actuator modulation and thermal boundaries</div>', unsafe_allow_html=True)
    
    fig_temp = go.Figure()
    
    # Comfort band shading
    fig_temp.add_hrect(
        y0=20.0, y1=26.0, 
        fillcolor="rgba(3, 105, 161, 0.03)", 
        line_width=0, 
        annotation_text="Comfort boundary (20 - 26°C)", 
        annotation_position="top left",
        annotation_font=dict(color="#0369A1", size=10)
    )
    
    # Actual Room Temp (Sapphire - Stable engineering)
    fig_temp.add_trace(go.Scatter(
        x=df["step"],
        y=df["zone_temp"],
        name="Zone temperature",
        line=dict(color="#0369A1", width=2.5)
    ))
    
    # Thermostat Setpoint (Slate - Scheduled boundary)
    fig_temp.add_trace(go.Scatter(
        x=df["step"],
        y=df["zone_setpoint"],
        name="Target setpoint",
        line=dict(color="#64748B", width=1.5, dash="dash")
    ))
    
    # Outdoor Drybulb Temp
    fig_temp.add_trace(go.Scatter(
        x=df["step"],
        y=df["outdoor_temp"],
        name="Outdoor temperature",
        line=dict(color="#94A3B8", width=1.2, dash="dot")
    ))
    
    fig_temp.update_layout(
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
        margin=dict(l=10, r=10, t=10, b=10),
        height=220,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1, font=dict(color="#020617", size=10)),
        xaxis=dict(gridcolor="#E2E8F0", tickfont=dict(color="#64748B", size=10), title=dict(text="Timestep (15-min)", font=dict(color="#64748B", size=10))),
        yaxis=dict(gridcolor="#E2E8F0", tickfont=dict(color="#64748B", size=10), title=dict(text="Temperature (°C)", font=dict(color="#64748B", size=10)), range=[14, 33])
    )
    st.plotly_chart(fig_temp, width="stretch", config={"displayModeBar": False})
    st.markdown('</div>', unsafe_allow_html=True)

with col_terminal:
    # 3. System Core Terminal Log Viewer
    st.markdown('<div class="log-feed-window">', unsafe_allow_html=True)
    
    # Terminal header block
    st.markdown(f"""
    <div class="log-feed-header">
        <span>System activity feed</span>
        <span style="font-weight: 400; color:#64748B;">Step {steps_completed}/96</span>
    </div>
    """, unsafe_allow_html=True)
    
    # Log Feed Rows
    for log in reversed(logs):
        step_num = log.get("step", 0)
        time_str = log.get("time", "00:00")
        reasoning_text = log.get("llm_reasoning", "No log output recorded.")
        actions_list = log.get("actions", [])
        carbon = log.get("carbon_intensity", 550)
        
        carbon_label = "High carbon intensity" if carbon >= 650 else "Optimal carbon profile"
        badge_style = "badge-terracotta" if carbon >= 650 else "badge-sapphire"
        
        # Build action strings
        action_strings = []
        for act in actions_list:
            t_name = act.get("tool", "")
            if t_name == "set_hvac_setpoint":
                action_strings.append(f"hvac: {act.get('cooling')}°C cooling")
            elif t_name == "set_lighting_level":
                action_strings.append(f"lights: {int(act.get('level')*100)}%")
        
        actions_rendered = " | ".join(action_strings) if action_strings else "no actions applied"
        
        # Build HTML content
        clamp_html = ""
        if log.get("has_clamp", False):
            clamp_text = log.get("clamp_desc", "Actuator override intercepted.")
            clamp_html = f'<div style="color:#B91C1C; margin-top:4px; font-weight:500;">⚠️ {clamp_text}</div>'
            
        st.markdown(f"""
        <div class="log-feed-row">
            <div>
                <span class="log-timestamp">t{step_num:02d} [{time_str}]</span> 
                <span class="badge {badge_style}">{carbon} gCO2 // {carbon_label}</span>
            </div>
            <div style="margin-top:6px;">
                <span class="log-section-label">Reasoning:</span>{reasoning_text}
            </div>
            <div style="margin-top:4px;">
                <span class="log-section-label">Commands:</span><code style="color:#0369A1; font-family:inherit; font-weight:600;">{actions_rendered}</code>
            </div>
            {clamp_html}
        </div>
        """, unsafe_allow_html=True)
        
    st.markdown('</div>', unsafe_allow_html=True)

# --- DETAILED REASONING EXPANDERS ---
st.markdown('<div class="fintech-card">', unsafe_allow_html=True)
st.markdown('<div class="fintech-card-header">Detailed timestep logs and audit trail</div>', unsafe_allow_html=True)

for i in range(min(5, steps_completed)):
    log_idx = steps_completed - 1 - i
    if log_idx < 0:
        break
    log_data = logs[log_idx]
    
    with st.expander(f"Step {log_data['step']} // Timeline event: {log_data['time']}"):
        col_exp1, col_exp2 = st.columns(2)
        
        with col_exp1:
            st.markdown(f"**Cognitive reasoning**")
            st.write(log_data['llm_reasoning'])
            
            st.markdown(f"**Grid and ambient metrics**")
            st.write(f"- Carbon intensity: `{log_data.get('carbon_intensity', 550)} gCO2/kWh`")
            st.write(f"- Outdoor temperature: `{log_data['sensor_snapshot']['outdoor_temp']} °C`")
            
        with col_exp2:
            st.markdown(f"**Simulated state telemetry**")
            st.json(log_data['sensor_snapshot'])
            
            st.markdown(f"**Applied actuator commands**")
            st.json(log_data['actions'])

st.markdown('</div>', unsafe_allow_html=True)

# --- FOOTER METRICS & CONTROLS ---
col_foot_1, col_foot_2 = st.columns(2)
with col_foot_1:
    st.markdown(
        """
        <div style="font-size:0.8rem; color:#64748B;">
            Compliance matrix: EnergyPlus V26.1.0 // Python 3.10+ (64-bit) // Groq Cloud Infrastructure
        </div>
        """,
        unsafe_allow_html=True
    )
with col_foot_2:
    st.markdown(
        """
        <div style="font-size:0.8rem; color:#64748B; text-align:right;">
            Honeywell Campus Hackathon 2026 // VIT // Mayukh Banerjee
        </div>
        """,
        unsafe_allow_html=True
    )
