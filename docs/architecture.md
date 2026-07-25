# EcoLoop System Architecture

## Overview

EcoLoop is a closed-loop Physical AI system that autonomously manages commercial
building energy through continuous interaction between a physics-based simulation
engine (EnergyPlus) and an LLM reasoning agent.

```
EnergyPlus ──► Python Bridge ──► LLM Agent ──► Control Actions ──► EnergyPlus
     ▲                                                              │
     └──────────────── Continuous Feedback Loop ◄───────────────────┘
```

## Component Architecture

### 1. Simulation Layer (`energyplus/`)
- Physics-accurate building energy simulation (EnergyPlus V26.1)
- Model: `5ZoneAutoDXVAV` commercial building (baseline + runtime copies)
- Weather: EPW climate file under `energyplus/weather/`

### 2. Python Bridge Layer (`bridge/`)
- `EPRunner` — simulation lifecycle + timestep callbacks
- `EPReader` — live sensor extraction
- `EPWriter` — EMS actuator injection with hard safety clamps

### 3. Cognitive Layer (`agent/`)
- `LLMClient` — OpenAI / Ollama tool-calling
- `mcp_server` — MCP-compatible tool schemas
- `tools` — tool implementations against the bridge
- `prompts` — mission + constraints + CoT format
- `orchestrator` — closed-loop heartbeat

### 4. Visualization (`dashboard/`)
- Streamlit + Plotly: energy savings, zone temps, agent reasoning trace

### 5. Data & Logs (`data/`)
- `baseline_results/` — uncontrolled run
- `agent_results/` — AI-controlled run
- `logs/agent_decisions.jsonl` — audit trail

## Known Limitations

- LLM latency (~2s/step) → real-time deploy needs async
- Synthetic IDF — not calibrated to a real building
- No multi-agent zone coordination yet

*(Expand during tomorrow's polish pass; add `docs/diagrams/system_flow.png`.)*
