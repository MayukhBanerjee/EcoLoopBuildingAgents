# EcoLoop — System Architecture

Autonomous closed-loop building energy management: a physics-accurate
EnergyPlus simulation and an open-source LLM exchanging data every 15
simulated minutes, with a deterministic safety layer between them.

```
  EnergyPlus  ──①──►  Bridge  ──②──►  LLM Agent
  (physics)          (reader)         (tool calls)
       ▲                                   │
       │                                   ③
       │                                   ▼
       └──⑤── Actuators ──④── Safety clamps (INV-1..5)
```

Every arrow is observable. `main.py --stream` renders all five stages live in
the terminal; `scripts/replay_stream.py` replays any finished run from disk;
the dashboard **Live data bus** panel renders the same five stages per
timestep. All three consume the same event records (`stream_events.jsonl` or
a reconstruction from `agent_decisions.jsonl`), so they cannot disagree.

---

## 1. Layers

| Layer | Package | Responsibility |
|---|---|---|
| Simulation | `energyplus/` | `baseline.idf`, `runtime.idf`, Chicago EPW, 15-min timestep |
| Bridge | `bridge/` | Sensor reads, actuator writes, safety clamps |
| Cognition | `agent/` | MCP tools, prompts, tool-call loop, memory, adaptive policy |
| Observability | `agent/stream.py` | Five-stage bus → console + JSONL + dashboard |
| Presentation | `dashboard/` | Streamlit + Plotly; renders `data/comparison/` only |
| Entry | `main.py` | Wires runner + reader + writer + LLM + orchestrator |

### Bridge (`bridge/`)

- **`state_manager.py`** — process-wide `EnergyPlusAPI` singleton (lazy import from
  `ENERGYPLUS_DIR`); one shared EP state so reader/writer cannot diverge.
- **`ep_runner.py`** — callback on
  `begin_zone_timestep_after_init_heat_balance`; skips warmup and
  `api_data_fully_ready() == false`. Exception firewall (INV-7).
- **`ep_reader.py`** — resolves handles once; reads zone temp, occupancy, CO₂,
  setpoints, lighting energy, outdoor air, facility energy. Bad handles fail
  loud and dump `available_api_data.csv`.
- **`ep_writer.py`** — only component that writes actuators; applies
  `bridge/clamps.py` before every write.
- **`clamps.py`** — pure INV-1…5 math (unit-tested, no EnergyPlus).
- **`constants.py`** — zones, sensor variable names, clamp bounds.

### Cognition (`agent/`)

`orchestrator.py` is the heartbeat. Per non-hold timestep:

```
read sensors → build prompt → tool-call rounds → [action nudge] → clamp → apply → JSONL + memory
```

On hold steps (`AGENT_EVERY_N_STEPS`): re-apply last `ControlAction`, log
`held=true`, no LLM call.

`llm_client.py` — OpenAI-compatible client (Groq by default; Ollama via
`OPENAI_BASE_URL`). Dev = 8B, prod = 70B.

`policy.py` — occupancy-aware adaptive fallback when the LLM is unavailable
or returns no control tools (not a static 22/20 hold).

`stream.py` — SENSE → PROMPT → TOOL → CLAMP → ACT event bus.

---

## 2. Tool-calling architecture

Five MCP tools in `agent/mcp_server.py` (Pydantic schemas = validation boundary):

| Tool | Purpose | Class |
|---|---|---|
| `set_hvac_setpoint` | Cooling + heating for one zone | write |
| `set_lighting_level` | Lighting fraction 0.0–1.0 | write |
| `read_sensors` | Current building state | read (discouraged — snapshot is pre-injected) |
| `get_energy_report` | Cumulative kWh, demand, savings vs baseline | read |
| `predict_comfort` | PMV for a proposed setpoint | pure |

**Writes are queued, not immediate.** Tool calls accumulate into one
`ControlAction`, applied once at end-of-timestep so clamps see the full intent.

**Schema conversion is lossy on purpose.** `mcp_to_openai_tool()` strips
`$defs` / title noise — smaller models degrade on verbose JSON Schema.

### Self-correction (in order of cost)

1. **Argument validation** — invalid tool args → rejection tool-message → one
   corrective LLM round (`llm_client.py`).
2. **Salvage parsing** — recover tool calls buried in text content (common on 8B).
3. **Action nudge** — `build_action_nudge_prompt()` if the model observed but
   never called a write tool.
4. **Adaptive policy** — `policy_action(reading)` if still no writes, or on
   `LLMUnavailable` / `--chaos`.

The building is never left on schedule defaults without an explicit action.

---

## 3. Safety: the prompt is advisory, the writer is law

Constraints appear in `SYSTEM_PROMPT` so the model *plans* within them.
Every write is re-enforced in `bridge/clamps.py` via `EPWriter.apply()`:

| ID | Invariant |
|---|---|
| INV-1 | Cooling ∈ [20, 26] °C occupied; ≤ 28 °C unoccupied |
| INV-2 | Heating ∈ [18, 24] °C occupied; ≥ 16 °C unoccupied |
| INV-3 | Heating ≤ cooling − 1 °C (deadband) |
| INV-4 | Max ±2 °C change per timestep (ramp) |
| INV-5 | Lighting ∈ [0, 1]; floor 0.3 when occupied |
| INV-6 | LLM failure → adaptive policy |
| INV-7 | Agent exceptions never abort EnergyPlus |
| INV-9 | Baseline and agent share identical physics + weather |

Each clamp logs `{zone, field, rule, req, applied}` into the decision JSONL
and stream stage **CLAMP**. Dashboard decision cards can surface per-step
warnings; the KPI strip focuses on energy / comfort / day progress.

---

## 4. Prompt engineering

Full rationale: **[`prompt_playbook.md`](prompt_playbook.md)**.

Headline choices in the current code (`agent/prompts.py`):

- Sensor snapshot **injected** into the user message (ACT-FIRST — do not burn
  a round on `read_sensors`).
- Mechanical **playbook A–E** (unoccupied setback, occupied comfort bands,
  grid peak shedding).
- Per-timestep **REQUIRED ACTIONS** block listing exact zones to touch.
- Text format: `REASONING` + `EXPECTED_OUTCOME` (actions are tool calls).
- Rolling **3-step memory** (`agent/memory.py`).
- `temperature=0.2`, `max_tokens=600`.

---

## 5. Latency and token budget

| Control | Mechanism |
|---|---|
| Timeout | 15 s hard cap, one retry → `LLMUnavailable` → policy |
| Rate limit | ≥ 2 s spacing (`AGENT_CALL_SPACING_S`); honour `Retry-After` on 429 |
| Cadence | `AGENT_EVERY_N_STEPS` — LLM every Nth step; hold + re-apply between |
| Model tier | `--dev` → 8B; default → 70B |
| Tool rounds | Cap via `AGENT_MAX_TOOL_ROUNDS` (nudge is separate) |
| Accounting | Tokens + latency in decision log / `summary.json` |

At `N=4` the LLM decides once per simulated hour. Held steps still call
`writer.apply(last_action)` so EMS ownership never reverts to the schedule.

---

## 6. Observability bus

```
SENSE   EnergyPlus → Bridge     compact sensor snapshot
PROMPT  Bridge → LLM            model, prompt size, preview
TOOL    LLM → Bridge            tool names/args, source (LLM / policy)
CLAMP   Bridge → Bridge         INV corrections
ACT     Bridge → EnergyPlus     applied actuator values
```

Sinks (`agent/stream.py`):

- **`ConsoleSink`** — terminal rendering (`main.py --stream`)
- **`JsonlSink`** — `data/agent_results/<run_id>/stream_events.jsonl`
- Emission is best-effort: sink failures never break the control loop

`scripts/replay_stream.py` re-renders from `stream_events.jsonl` or
reconstructs stages from `agent_decisions.jsonl`.

---

## 7. Handling lengthy simulation logs

A 96-step run produces megabytes of EnergyPlus output. **None of it is sent
to the model.**

```
EnergyPlus raw output  →  SensorReading  →  to_compact()  →  ~15 numbers / zones
```

| Artifact | Contents |
|---|---|
| `agent_decisions.jsonl` | Per-step: snapshot, reasoning, tools, clamps, actions, tokens |
| `decisions.jsonl` | Alias of the above (compat) |
| `stream_events.jsonl` | Five stage events per timestep |
| `actuator_timeline.csv` | Every actuator write |
| `runtime_final_state.idf` | Final setpoints as a valid IDF |
| `summary.json` | kWh, savings, calls, tokens, fallbacks, clamps |

Decision lines are **flushed every timestep** so a kill mid-run still leaves
a complete audit trail up to the last step.

---

## 8. Measuring savings honestly

1. `scripts/prepare_models.py` — builds `baseline.idf` + instrumented `runtime.idf`
2. `scripts/run_baseline.py` — uncontrolled day; sums facility electricity
3. `main.py` — closed-loop agent run
4. `scripts/generate_comparison.py` — writes `data/comparison/` (KPIs, CSVs,
   decisions) for the dashboard — **no recomputation in the UI**

Defensibility rules:

1. **INV-9** — same building physics and weather; only EMS/agent control differs.
2. Same electricity series for both totals.
3. Comfort = share of **occupied** zone-steps in band; if occupied count is 0,
   report *not measured* (never fake 100%).
4. Baseline comfort is scored the same way so the dashboard can show a delta
   (e.g. agent 33.2% vs baseline 23.1%).

---

## 9. How to run (reference)

```bash
uv run python scripts/prepare_models.py
uv run python scripts/run_baseline.py
uv run python main.py --dev --stream          # live bus
uv run python scripts/generate_comparison.py
uv run streamlit run dashboard/app.py
uv run python scripts/replay_stream.py        # offline demo of the bus
```

Useful flags: `--chaos` (force policy, no LLM), `--dry-run` / `--max-steps`,
`--no-stream-file`.

---

## 10. Known limitations

- Reference building, not calibrated to a metered site.
- PMV uses fixed `met=1.1`, `clo=0.7`; MRT ≈ air temperature.
- Grid carbon intensity is a representative diurnal curve, not a live ISO feed.
- Zones are reasoned independently (no explicit cross-zone optimiser).
- Wall-clock LLM latency (~1–2 s/call) is fine vs a 15-minute control interval;
  real BMS deployment would need async / edge design.
- Small models often return **tool calls with empty text**; the UI must not
  treat empty reasoning as a HOLD step.
