"""
mcp_server.py — MCP-compatible tool registry.

Job: Define structured tool schemas the LLM can call
(read_sensors, set_hvac_setpoint, set_lighting_level,
get_energy_report, predict_comfort). This is the agentic surface.

Build: with tools.py; schemas first, then implementations.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class ReadSensorsInput(BaseModel):
    zones: Optional[list[str]] = None


class SetHVACInput(BaseModel):
    zone: str
    cooling_setpoint: float = Field(..., description="°C, clamped 18–26")
    heating_setpoint: float = Field(..., description="°C, clamped 18–24")


class SetLightingInput(BaseModel):
    zone: str
    level: float = Field(..., ge=0.0, le=1.0)


class GetEnergyReportInput(BaseModel):
    compare_to_baseline: bool = True


class PredictComfortInput(BaseModel):
    zone: str
    proposed_setpoint: float


MCP_TOOLS: list[dict] = [
    {
        "name": "read_sensors",
        "description": (
            "Read current zone temperatures, CO2, occupancy, and energy "
            "from the building simulation."
        ),
        "input_schema": ReadSensorsInput.model_json_schema(),
    },
    {
        "name": "set_hvac_setpoint",
        "description": (
            "Set heating and cooling setpoints for a zone (safe range 18–26°C)."
        ),
        "input_schema": SetHVACInput.model_json_schema(),
    },
    {
        "name": "set_lighting_level",
        "description": "Adjust lighting power for a zone (0.0 off → 1.0 full).",
        "input_schema": SetLightingInput.model_json_schema(),
    },
    {
        "name": "get_energy_report",
        "description": "Cumulative energy use; optionally vs baseline.",
        "input_schema": GetEnergyReportInput.model_json_schema(),
    },
    {
        "name": "predict_comfort",
        "description": "Estimate PMV comfort for a proposed zone setpoint.",
        "input_schema": PredictComfortInput.model_json_schema(),
    },
]
