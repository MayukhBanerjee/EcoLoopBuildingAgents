"""
Streamlit dashboard — quantitative savings + agent reasoning deliverable.

Run: streamlit run dashboard/app.py
"""

from __future__ import annotations

import streamlit as st

st.set_page_config(
    page_title="EcoLoop — AI Building Agent",
    page_icon="🏢",
    layout="wide",
)

st.markdown("## EcoLoop Building Agent Dashboard")
st.markdown(
    "*Autonomous AI-driven energy optimization via closed-loop EnergyPlus control*"
)
st.info(
    "Scaffold ready. Implement KPI cards, energy chart, zone timeline, "
    "and agent log using dashboard/components/."
)
