"""
Shared constants for the EnergyPlus bridge.

Ground truth from Phase 1:
  - Zones: SPACE1-1 .. SPACE5-1 (PLENUM-1 is read-only / uncontrolled)
  - Lights actuators (eplusout.edd): component=Lights, control=Electricity Rate [W]
  - HVAC actuators: Zone Temperature Control / Cooling|Heating Setpoint / <ZONE>
  - Design lighting level from IDF: 1584 W per SPACE lights object
"""

from __future__ import annotations

CONTROLLED_ZONES: tuple[str, ...] = (
    "SPACE1-1",
    "SPACE2-1",
    "SPACE3-1",
    "SPACE4-1",
    "SPACE5-1",
)

# From runtime_oracle/eplusout.edd — names are uppercased by EnergyPlus
LIGHTS_ACTUATOR_NAME: dict[str, str] = {
    z: f"{z} LIGHTS 1" for z in CONTROLLED_ZONES
}

# Design lighting power from baseline IDF (Lighting Level {W})
DESIGN_LIGHTS_W: dict[str, float] = {z: 1584.0 for z in CONTROLLED_ZONES}

# Output:Variable names requested via Python API before run_energyplus
SENSOR_VARIABLES: tuple[tuple[str, str], ...] = tuple(
    [
        *(("Zone Mean Air Temperature", z) for z in CONTROLLED_ZONES),
        *(("Zone People Occupant Count", z) for z in CONTROLLED_ZONES),
        *(("Zone Air CO2 Concentration", z) for z in CONTROLLED_ZONES),
        *(("Zone Thermostat Cooling Setpoint Temperature", z) for z in CONTROLLED_ZONES),
        *(("Zone Thermostat Heating Setpoint Temperature", z) for z in CONTROLLED_ZONES),
        *(("Lights Electricity Energy", f"{z} LIGHTS 1") for z in CONTROLLED_ZONES),
        ("Site Outdoor Air Drybulb Temperature", "Environment"),
        # Prefer this over Electricity:Facility meter — meter handles are -1 on some
        # callback timings even when OutputMeter is listed in available API data.
        ("Facility Net Purchased Electricity Energy", "WHOLE BUILDING"),
    ]
)

FACILITY_ENERGY_VAR = ("Facility Net Purchased Electricity Energy", "WHOLE BUILDING")
# NOTE: get_meter_handle("Electricity:Facility") returns -1 on EP 26.1 Python API.
# ElectricityPurchased:Facility resolves and matches baseline Facility totals (~172 kWh).
FACILITY_METER = "ElectricityPurchased:Facility"

# Safety invariants (enforced in ep_writer — never trusted to the LLM)
COOL_OCC_MIN = 20.0
COOL_OCC_MAX = 26.0
COOL_UNOCC_MAX = 28.0
HEAT_OCC_MIN = 18.0
HEAT_OCC_MAX = 24.0
HEAT_UNOCC_MIN = 16.0
DEADBAND_C = 1.0
RAMP_MAX_C = 2.0
LIGHT_OCC_MIN = 0.3
LIGHT_MIN = 0.0
LIGHT_MAX = 1.0

JOULES_TO_KWH = 1.0 / 3_600_000.0
EXPECTED_TIMESTEPS = 96
