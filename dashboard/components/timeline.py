"""Plotly charts with plain-language axes and impact context."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

CHART_LAYOUT = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    margin=dict(l=8, r=8, t=28, b=8),
    legend=dict(
        orientation="h",
        yanchor="bottom",
        y=1.12,
        xanchor="right",
        x=1,
        font=dict(color="#334155", size=11, family="IBM Plex Sans"),
    ),
    bgcolor="rgba(0,0,0,0)",
    font=dict(family="IBM Plex Sans", color="#64748B", size=11),
    hovermode="x unified",
)

AXIS = dict(
    gridcolor="#EEF2F6",
    zeroline=False,
    showline=False,
    tickfont=dict(color="#64748B", size=11),
    title=dict(font=dict(color="#64748B", size=12)),
)


def _clock_labels(df: pd.DataFrame) -> list[str]:
    """Build HH:MM labels for a simulated day (15-min steps)."""
    if "clock" in df.columns:
        return [str(x) for x in df["clock"].tolist()]
    if "sim_hour" in df.columns and "sim_minute" in df.columns:
        return [
            f"{int(h):02d}:{int(m):02d}"
            for h, m in zip(df["sim_hour"], df["sim_minute"], strict=False)
        ]
    labels = []
    for step in df["step"].tolist():
        i = max(0, int(step) - 1)
        labels.append(f"{i // 4:02d}:{(i % 4) * 15:02d}")
    return labels


def _tick_vals(labels: list[str]) -> tuple[list[str], list[str]]:
    """Show a readable subset of clock ticks (every ~2 hours)."""
    if not labels:
        return [], []
    step = max(1, len(labels) // 12)
    idxs = list(range(0, len(labels), step))
    if idxs[-1] != len(labels) - 1:
        idxs.append(len(labels) - 1)
    return [labels[i] for i in idxs], [labels[i] for i in idxs]


def _base_fig(height: int = 280) -> go.Figure:
    fig = go.Figure()
    layout = {k: v for k, v in CHART_LAYOUT.items() if k != "bgcolor"}
    fig.update_layout(**layout, height=height)
    fig.update_xaxes(**AXIS)
    fig.update_yaxes(**AXIS)
    return fig


def _apply_clock_axis(fig: go.Figure, labels: list[str], title: str = "Time of day") -> None:
    ticktext, _ = _tick_vals(labels)
    # Use categorical x = clock labels directly
    fig.update_xaxes(
        title_text=title,
        tickmode="array",
        tickvals=ticktext,
        ticktext=ticktext,
        title_standoff=12,
    )


def render_energy_chart(df: pd.DataFrame) -> None:
    labels = _clock_labels(df)
    fig = _base_fig(300)

    fig.add_trace(
        go.Scatter(
            x=labels,
            y=df["baseline_kwh_cum"],
            name="Without EcoLoop (normal schedule)",
            mode="lines",
            line=dict(color="#94A3B8", width=2.2, dash="dot"),
            hovertemplate="%{x}<br>Normal schedule: %{y:.1f} kWh<extra></extra>",
        )
    )
    if "agent_kwh_cum" in df.columns and df["agent_kwh_cum"].notna().any():
        fig.add_trace(
            go.Scatter(
                x=labels,
                y=df["agent_kwh_cum"],
                name="With EcoLoop (AI control)",
                mode="lines",
                line=dict(color="#0F766E", width=2.8),
                fill="tonexty",
                fillcolor="rgba(15, 118, 110, 0.12)",
                hovertemplate="%{x}<br>EcoLoop: %{y:.1f} kWh<extra></extra>",
            )
        )
        # End-of-day annotation
        try:
            b = float(df["baseline_kwh_cum"].iloc[-1])
            a = float(df["agent_kwh_cum"].iloc[-1])
            saved = b - a
            if saved > 0 and labels:
                fig.add_annotation(
                    x=labels[-1],
                    y=(a + b) / 2,
                    text=f"Saved {saved:.0f} kWh",
                    showarrow=False,
                    font=dict(color="#0F766E", size=12, family="IBM Plex Sans"),
                    bgcolor="rgba(240,253,250,0.9)",
                    bordercolor="#99F6E4",
                    borderwidth=1,
                    borderpad=4,
                    xanchor="right",
                )
        except (TypeError, ValueError, IndexError):
            pass

    _apply_clock_axis(fig, labels)
    fig.update_yaxes(
        title_text="Electricity used so far (kWh)",
        title_standoff=14,
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


def render_thermal_chart(df: pd.DataFrame) -> None:
    labels = _clock_labels(df)
    fig = _base_fig(300)
    fig.add_hrect(
        y0=20.0,
        y1=26.0,
        fillcolor="rgba(30, 58, 95, 0.06)",
        line_width=0,
        annotation_text="Comfortable for people (20–26°C)",
        annotation_position="top left",
        annotation_font=dict(color="#1E3A5F", size=11, family="IBM Plex Sans"),
    )
    if "zone_temp" in df.columns:
        fig.add_trace(
            go.Scatter(
                x=labels,
                y=df["zone_temp"],
                name="Room temperature",
                mode="lines",
                line=dict(color="#1E3A5F", width=2.6),
                hovertemplate="%{x}<br>Room: %{y:.1f}°C<extra></extra>",
            )
        )
    if "zone_setpoint" in df.columns and df["zone_setpoint"].notna().any():
        fig.add_trace(
            go.Scatter(
                x=labels,
                y=df["zone_setpoint"],
                name="Cooling target set by AI",
                mode="lines",
                line=dict(color="#0F766E", width=1.8, dash="dash"),
                hovertemplate="%{x}<br>Cooling target: %{y:.1f}°C<extra></extra>",
            )
        )
    if "outdoor_temp" in df.columns and df["outdoor_temp"].notna().any():
        fig.add_trace(
            go.Scatter(
                x=labels,
                y=df["outdoor_temp"],
                name="Outdoor weather",
                mode="lines",
                line=dict(color="#94A3B8", width=1.4, dash="dot"),
                hovertemplate="%{x}<br>Outdoor: %{y:.1f}°C<extra></extra>",
            )
        )
    _apply_clock_axis(fig, labels)
    fig.update_yaxes(
        title_text="Temperature (°C)",
        range=[12, 34],
        title_standoff=14,
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


def render_occupancy_chart(df: pd.DataFrame) -> None:
    if "occupancy" not in df.columns or df["occupancy"].fillna(0).sum() <= 0:
        return
    labels = _clock_labels(df)
    fig = _base_fig(150)
    fig.add_trace(
        go.Bar(
            x=labels,
            y=df["occupancy"],
            name="People in the zone",
            marker=dict(color="rgba(15, 118, 110, 0.55)"),
            hovertemplate="%{x}<br>%{y} people in room<extra></extra>",
        )
    )
    fig.update_layout(showlegend=False, margin=dict(l=8, r=8, t=8, b=8))
    _apply_clock_axis(fig, labels, title="Time of day")
    fig.update_yaxes(title_text="People in the room", title_standoff=10)
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


def render_timeline(
    energy_df: pd.DataFrame | None = None,
    zone_df: pd.DataFrame | None = None,
    decisions: list | None = None,
    kpis: dict | None = None,
    *,
    df: pd.DataFrame | None = None,
) -> None:
    """Back-compat wrapper."""
    if df is not None:
        render_energy_chart(df)
        render_thermal_chart(df)
        render_occupancy_chart(df)
        return
    if energy_df is not None and not energy_df.empty:
        render_energy_chart(energy_df)
    if zone_df is not None and not zone_df.empty:
        z = zone_df[zone_df["zone"] == "SPACE1-1"].copy() if "zone" in zone_df.columns else zone_df
        frame = pd.DataFrame({"step": z["step"]})
        if "agent_temp_c" in z.columns:
            frame["zone_temp"] = z["agent_temp_c"]
        elif "baseline_temp_c" in z.columns:
            frame["zone_temp"] = z["baseline_temp_c"]
        if "agent_occ" in z.columns:
            frame["occupancy"] = z["agent_occ"]
        outdoor, setpoints = [], []
        by_step = {int(d.get("timestep") or 0): d for d in (decisions or [])}
        for step in frame["step"].tolist():
            d = by_step.get(int(step), {})
            snap = d.get("sensor_snapshot") or {}
            outdoor.append(snap.get("outdoor_temp"))
            zones = snap.get("zones") or {}
            z1 = zones.get("SPACE1-1") or {}
            setpoints.append(z1.get("cool_sp"))
        frame["outdoor_temp"] = outdoor
        frame["zone_setpoint"] = setpoints
        render_thermal_chart(frame)
        render_occupancy_chart(frame)
