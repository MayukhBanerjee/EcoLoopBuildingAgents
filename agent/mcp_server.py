"""
mcp_server.py — MCP-compatible tool registry for EcoLoop.

Defines the five agent tools and their Pydantic-validated input schemas.
Exposes MCP_TOOLS (list of dicts with name/description/input_schema) and a
helper to convert to OpenAI function-calling format.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Input schemas (Pydantic v2)
# ---------------------------------------------------------------------------


class ReadSensorsInput(BaseModel):
    """Read current sensor values.  Pass zones=None to read all zones."""

    zones: Optional[list[str]] = Field(
        default=None,
        description="Zone names to read, or null for all controlled zones.",
    )


class SetHVACInput(BaseModel):
    """Set HVAC setpoints for a single zone."""

    zone: str = Field(..., description="Zone name, e.g. SPACE1-1.")
    cooling_setpoint: float = Field(
        ...,
        ge=18.0,
        le=28.0,
        description="Cooling setpoint in °C (clamped 20–26 occupied, 20–28 unoccupied).",
    )
    heating_setpoint: float = Field(
        ...,
        ge=16.0,
        le=24.0,
        description="Heating setpoint in °C (clamped 18–24 occupied, 16–24 unoccupied).",
    )


class SetLightingInput(BaseModel):
    """Set lighting power fraction for a single zone."""

    zone: str = Field(..., description="Zone name, e.g. SPACE1-1.")
    level: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Lighting power fraction: 0.0 = off, 1.0 = full power.",
    )


class GetEnergyReportInput(BaseModel):
    """Request energy consumption report."""

    compare_to_baseline: bool = Field(
        default=True,
        description="If true, include savings vs baseline (172.5 kWh reference).",
    )


class PredictComfortInput(BaseModel):
    """Estimate PMV comfort for a proposed zone setpoint."""

    zone: str = Field(..., description="Zone name.")
    proposed_setpoint: float = Field(
        ...,
        ge=18.0,
        le=28.0,
        description="Proposed cooling setpoint in °C.",
    )


# ---------------------------------------------------------------------------
# MCP tool registry
# ---------------------------------------------------------------------------

MCP_TOOLS: list[dict] = [
    {
        "name": "read_sensors",
        "description": (
            "Read current zone temperatures (°C), CO2 (ppm), occupancy counts, "
            "HVAC setpoints, outdoor temperature, and cumulative energy (kWh). "
            "Call this first at each timestep to understand the building state."
        ),
        "input_schema": ReadSensorsInput.model_json_schema(),
    },
    {
        "name": "set_hvac_setpoint",
        "description": (
            "Set heating and cooling setpoints for one zone. "
            "Safety limits are enforced server-side: cooling 20–26°C occupied, "
            "heating 18–24°C occupied, max 2°C change per timestep. "
            "Call once per zone that needs adjustment."
        ),
        "input_schema": SetHVACInput.model_json_schema(),
    },
    {
        "name": "set_lighting_level",
        "description": (
            "Adjust lighting power for one zone (0.0 = off, 1.0 = full). "
            "Occupied zones are floored at 0.3 for safety. "
            "Switch off or dim lights in unoccupied zones to save energy."
        ),
        "input_schema": SetLightingInput.model_json_schema(),
    },
    {
        "name": "get_energy_report",
        "description": (
            "Return cumulative electricity consumption this run (kWh), "
            "current demand (kW), carbon intensity for the current hour, "
            "and optional savings vs the 172.5 kWh baseline."
        ),
        "input_schema": GetEnergyReportInput.model_json_schema(),
    },
    {
        "name": "predict_comfort",
        "description": (
            "Estimate PMV (Predicted Mean Vote) for a proposed cooling setpoint. "
            "PMV in [-0.5, +0.5] is ASHRAE comfort; outside this range occupants "
            "will complain. Use before aggressive setpoint changes."
        ),
        "input_schema": PredictComfortInput.model_json_schema(),
    },
]
