"""About EcoLoop — first-time viewer briefing (Streamlit dialog)."""

from __future__ import annotations

import streamlit as st


@st.dialog("About EcoLoop", width="large")
def show_about_dialog() -> None:
    st.markdown(
        """
### The problem

Commercial buildings waste a lot of electricity on **HVAC and lighting** —
especially when rooms are empty, or when the system keeps running on a fixed
schedule that ignores weather, occupancy, and how dirty the power grid is at
that hour.

Judges and operators still need proof that any “smart” control:
1. actually **cuts energy** versus a fair baseline, and  
2. does **not freeze or overheat people**, and  
3. never writes **unsafe** setpoints into the building.

### The solution

**EcoLoop** is a closed-loop Physical AI demo:

1. **EnergyPlus** simulates a 5-zone office building every **15 minutes** for a full day.  
2. A **Python bridge** reads live sensors (temps, occupancy, demand) and writes HVAC / lighting actuators.  
3. An **LLM agent** (Groq / Llama) reasons with tools — read sensors, set cooling/heating, dim lights, check comfort — then acts.  
4. **Hard safety clamps** sit in front of every write (temperature bands, lighting floors, etc.). If the AI asks for something unsafe, the bridge corrects it and logs a “safety catch.”

We always compare against a **baseline day** with the same weather and building, but **no AI** — so savings are measured, not guessed.

### What this dashboard shows

| Section | What it means |
|---|---|
| **Electricity cut** | % less kWh than the normal schedule for the same day |
| **People comfortable** | Share of *occupied* zone-steps where comfort (PMV) stayed in band — always compared to the no-AI baseline when available |
| **Power used today** | Absolute kWh with EcoLoop vs without |
| **Safety catches** | How many times hard limits blocked or corrected a request |
| **Electricity chart** | Cumulative kWh over the day — shaded gap = energy saved |
| **Temperature chart** | Room °C vs the AI’s cooling target vs outdoor weather |
| **Occupancy chart** | When people were actually in the zone |
| **What the agent did** | Scrollable decision trail (why + what changed) |
| **Peek inside a decision** | Separate module under the occupancy chart — expand a step for sensors & zones |

### What the numbers are calculated from

- **Baseline kWh** — EnergyPlus run with the default schedule (`data/baseline_results`).  
- **Agent kWh** — same building/weather with EcoLoop in the loop (`data/agent_results/...`).  
- **Savings %** — `(baseline − agent) / baseline × 100`.  
- **Comfort %** — among occupied zone readings, fraction with PMV inside ±0.5.  
- **Charts & decisions** — pre-built comparison files under `data/comparison/` (energy timeseries, zone temps, decision log).

### How to read it in 30 seconds

1. Look at **Electricity cut** — that’s the headline impact.  
2. Check the **energy chart** — teal below grey means EcoLoop used less power as the day went on.  
3. Skim **What the agent did** — empty rooms → raise cooling target / lights off; busy rooms → hold comfort.  
4. Open **Peek inside a decision** if you want the sensor picture behind one choice.
        """
    )
    if st.button("Got it", use_container_width=True, type="primary"):
        st.rerun()
