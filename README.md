# EcoLoop Building Agents

Physical AI PoC — autonomous closed-loop building energy management.

```
EnergyPlus (Simulation) ──► Python Bridge ──► LLM Agent ──► Control Actions ──► EnergyPlus
         ▲                                                                          │
         └──────────────── Continuous Feedback Loop ◄───────────────────────────────┘
```

## Stack

- EnergyPlus V26.1
- Python 3.10+
- OpenAI API (or Ollama)
- FastAPI · MCP tools · Streamlit

## Quick start

```bash
# 1. Install deps
pip install -r requirements.txt

# 2. Configure
copy .env.example .env
# edit OPENAI_API_KEY

# 3. Run baseline (no AI)
python scripts/run_baseline.py

# 4. Run closed-loop agent
python main.py

# 5. Dashboard
streamlit run dashboard/app.py
```

## Project layout

See folder map in the repo — each package has a short module docstring describing its job.

## Status

Scaffold only — modules to be implemented in build order (bridge → agent → dashboard).
