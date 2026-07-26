# EcoLoop

**Autonomous closed-loop building energy management** — a physics-accurate EnergyPlus simulation controlled in real time by an open-source LLM, with a hard safety layer between the model and the building.

Built for the Honeywell Campus Hackathon (Physical AI).

```
EnergyPlus (physics)  ──►  Python Bridge  ──►  LLM Agent (tool calls)
        ▲                                            │
        └──── actuators ◄──── safety clamps ◄────────┘
```

Every 15 simulated minutes the agent reads zone sensors, reasons about occupancy / grid carbon / comfort, and writes HVAC setpoints + lighting — or holds the last safe action. The building is never left uncontrolled.

---

## Results (demo run)

| Metric | Value |
|--------|------:|
| Electricity vs uncontrolled baseline | **−33.8%** (58 kWh saved on a 24 h day) |
| Agent energy | 114.1 kWh |
| Baseline energy | 172.5 kWh |
| Comfort band (occupied time) | 33.2% *(+10.1 pts vs baseline 23.1%)* |
| Safety clamp interventions | logged per step (INV-1…5) |

Dashboard and KPIs are generated from the same run artifacts — numbers are not hand-typed.

---

## What makes it real

| Claim | How EcoLoop proves it |
|-------|------------------------|
| Closed loop | EnergyPlus timestep callback → agent → actuators → next physics step |
| Open-source LLM | Groq-hosted Llama (`llama-3.1-8b-instant` / `llama-3.3-70b-versatile`) via OpenAI-compatible API |
| Safety is not prompt hope | Deterministic clamps in `bridge/clamps.py` re-enforce every invariant before any write |
| Observable | Terminal stream, JSONL event bus, Streamlit dashboard — same stages |
| Fail-safe | LLM timeout / error → occupancy-aware adaptive policy (`agent/policy.py`) |

---

## Stack

- **Simulation** — EnergyPlus V26.1 · 5-zone DX/VAV office · Chicago EPW · 15-min steps (96 / day)
- **Bridge** — `pyenergyplus` API · sensor read · actuator write · clamps
- **Agent** — MCP-style tools · tool-calling loop · rolling memory · stream bus
- **UI** — Streamlit + Plotly
- **Runtime** — Python 3.10+ · [`uv`](https://github.com/astral-sh/uv) (or pip)

---

## Prerequisites

1. **EnergyPlus 26.1** installed locally  
   Default path: `C:\EnergyPlusV26-1-0` (override with `ENERGYPLUS_DIR` in `.env`)
2. **Python 3.10+**
3. **Groq API key** (or any OpenAI-compatible endpoint / local Ollama)

---

## Quick start

```bash
# 1. Install
uv sync
# or: pip install -r requirements.txt

# 2. Configure
cp .env.example .env          # Windows: copy .env.example .env
# set GROQ_API_KEY=...
# set ENERGYPLUS_DIR=...

# 3. Instrument models (once)
uv run python scripts/prepare_models.py

# 4. Uncontrolled baseline (once — comparison reference)
uv run python scripts/run_baseline.py

# 5. Closed-loop agent (dev = 8B model)
uv run python main.py --dev

# 6. Build dashboard artifacts from the latest run
uv run python scripts/generate_comparison.py

# 7. Dashboard
uv run streamlit run dashboard/app.py
```

Already have `data/comparison/` populated? Skip to step 7 — the dashboard needs no live simulation.

### Useful flags

```bash
uv run python main.py --dev --dry-run          # short smoke
uv run python main.py --dev --chaos            # force fallback policy (no LLM)
uv run python main.py --dev --stream           # live SENSE→PROMPT→TOOL→CLAMP→ACT bus
uv run python main.py                          # scored 70B run
uv run python scripts/replay_stream.py         # replay a finished run in the terminal
```

---

## How a timestep works

```
① SENSE     Bridge reads temps, occupancy, CO₂, setpoints, outdoor air, energy
② PROMPT    Orchestrator builds context (sensors + grid + 3-step memory)
③ TOOL      LLM calls MCP tools (set HVAC / lights, or read-only helpers)
④ CLAMP     Hard limits rewrite unsafe values; every catch is logged
⑤ ACT       One atomic write into EnergyPlus; hold last action between LLM cadences
```

**Tools** (`agent/mcp_server.py`):

| Tool | Role |
|------|------|
| `set_hvac_setpoint` | Cooling + heating for one zone |
| `set_lighting_level` | Lighting fraction 0–1 |
| `read_sensors` | Current building state |
| `get_energy_report` | kWh / demand / savings vs baseline |
| `predict_comfort` | PMV estimate for a proposed setpoint |

Writes are **queued**, then applied once per step so clamps see the full intent.

---

## Safety invariants

The system prompt is advisory. The writer is law.

| ID | Rule |
|----|------|
| INV-1 | Cooling ∈ [20, 26] °C occupied; ≤ 28 °C only when empty |
| INV-2 | Heating ∈ [18, 24] °C occupied; ≥ 16 °C only when empty |
| INV-3 | Heating ≤ cooling − 1 °C (deadband) |
| INV-4 | Max ±2 °C change per step (ramp) |
| INV-5 | Lighting ∈ [0, 1]; floor 0.3 when occupied |
| INV-6 | LLM failure → deterministic adaptive policy |
| INV-7 | Agent exceptions never abort EnergyPlus |
| INV-9 | Baseline and agent share identical model + weather |

---

## Repository layout

```
eco-loop/
├── main.py                 # Closed-loop entry
├── agent/                  # LLM brain — orchestrator, tools, policy, stream
├── bridge/                 # EnergyPlus I/O + clamps
├── dashboard/              # Streamlit UI (renders comparison artifacts only)
├── energyplus/
│   ├── models/             # baseline.idf, runtime.idf (local)
│   └── weather/            # Chicago EPW (local)
├── data/
│   ├── baseline_results/   # Uncontrolled EP run
│   ├── comparison/         # KPIs + CSVs + decisions for the dashboard
│   └── agent_results/      # Per-run outputs (gitignored)
├── scripts/
│   ├── prepare_models.py
│   ├── run_baseline.py
│   ├── generate_comparison.py
│   ├── replay_stream.py
│   └── audit_comfort.py
├── tests/                  # Clamps, policy, comfort
└── docs/architecture.md    # Deep dive
```

---

## Environment

See [`.env.example`](.env.example). Important knobs:

| Variable | Purpose |
|----------|---------|
| `GROQ_API_KEY` | LLM auth |
| `MODEL_NAME` | Scored model (default 70B) |
| `DEV_MODEL_NAME` | Fast/cheap model for `--dev` |
| `ENERGYPLUS_DIR` | EnergyPlus install path |
| `AGENT_EVERY_N_STEPS` | LLM every Nth step; hold setpoints between |
| `PEAK_DEMAND_THRESHOLD_KW` | Peak-demand label in prompts |

Offline: point `OPENAI_BASE_URL` at Ollama (`http://localhost:11434/v1`).

---

## Tests

```bash
uv run pytest tests/ -q
```

---

## Docs

- [`docs/architecture.md`](docs/architecture.md) — layers, tools, clamps, stream bus, savings
- [`docs/prompt_playbook.md`](docs/prompt_playbook.md) — ACT-FIRST prompts, playbook A–E, latency

---

## License / hackathon note

PoC for Honeywell Campus Hackathon. Simulation-only — no live building control.
