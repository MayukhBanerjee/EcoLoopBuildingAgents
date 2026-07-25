"""Plotly charts for energy and thermal timelines."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

CHART_LAYOUT = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    margin=dict(l=8, r=8, t=8, b=8),
    legend=dict(
        orientation="h",
        yanchor="bottom",
        y=1.08,
        xanchor="right",
        x=1,
        font=dict(color="#334155", size=11, family="IBM Plex Sans"),
        bgcolor="rgba(0,0,0,0)",
    ),
    font=dict(family="IBM Plex Sans", color="#64748B", size=11),
    hovermode="x unified",
)

AXIS = dict(
    gridcolor="#EEF2F6",
    zeroline=False,
    showline=False,
    tickfont=dict(color="#64748B", size=11),
    title=dict(font=dict(color="#94A3B8", size=11)),
)


def _base_fig(height: int = 260) -> go.Figure:
    fig = go.Figure()
    fig.update_layout(**CHART_LAYOUT, height=height)
    fig.update_xaxes(**AXIS)
    fig.update_yaxes(**AXIS)
    return fig


def render_energy_chart(df: pd.DataFrame) -> None:
    fig = _base_fig(270)
    fig.add_trace(
        go.Scatter(
            x=df["step"],
            y=df["baseline_kwh_cum"],
            name="Baseline",
            mode="lines",
            line=dict(color="#94A3B8", width=2, dash="dot"),
            hovertemplate="Step %{x}<br>Baseline %{y:.1f} kWh<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=df["step"],
            y=df["agent_kwh_cum"],
            name="AI-controlled",
            mode="lines",
            line=dict(color="#0F766E", width=2.8),
            fill="tonexty",
            fillcolor="rgba(15, 118, 110, 0.10)",
            hovertemplate="Step %{x}<br>Agent %{y:.1f} kWh<extra></extra>",
        )
    )
    fig.update_xaxes(title_text="Timestep (15 min)")
    fig.update_yaxes(title_text="Cumulative kWh", title_standoff=14)
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})


def render_thermal_chart(df: pd.DataFrame) -> None:
    fig = _base_fig(270)
    fig.add_hrect(
        y0=20.0,
        y1=26.0,
        fillcolor="rgba(30, 58, 95, 0.05)",
        line_width=0,
        annotation_text="Comfort band 20–26°C",
        annotation_position="top left",
        annotation_font=dict(color="#1E3A5F", size=10, family="IBM Plex Sans"),
    )
    fig.add_trace(
        go.Scatter(
            x=df["step"],
            y=df["zone_temp"],
            name="Zone temp",
            mode="lines",
            line=dict(color="#1E3A5F", width=2.6),
            hovertemplate="Step %{x}<br>Zone %{y:.1f}°C<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=df["step"],
            y=df["zone_setpoint"],
            name="Setpoint",
            mode="lines",
            line=dict(color="#0F766E", width=1.8, dash="dash"),
            hovertemplate="Step %{x}<br>Setpoint %{y:.1f}°C<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=df["step"],
            y=df["outdoor_temp"],
            name="Outdoor",
            mode="lines",
            line=dict(color="#94A3B8", width=1.4, dash="dot"),
            hovertemplate="Step %{x}<br>Outdoor %{y:.1f}°C<extra></extra>",
        )
    )
    fig.update_xaxes(title_text="Timestep (15 min)")
    fig.update_yaxes(title_text="Temperature (°C)", range=[14, 33], title_standoff=14)
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})


def render_occupancy_chart(df: pd.DataFrame) -> None:
    if "occupancy" not in df.columns:
        return
    fig = _base_fig(120)
    fig.add_trace(
        go.Bar(
            x=df["step"],
            y=df["occupancy"],
            name="Occupancy",
            marker=dict(color="rgba(15, 118, 110, 0.55)"),
            hovertemplate="Step %{x}<br>%{y} people<extra></extra>",
        )
    )
    fig.update_layout(showlegend=False, margin=dict(l=8, r=8, t=4, b=8))
    fig.update_xaxes(title_text="", visible=False)
    fig.update_yaxes(title_text="People", title_standoff=10)
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
