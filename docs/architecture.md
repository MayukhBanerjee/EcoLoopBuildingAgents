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
the dashboard's **Live data bus** panel renders the same five stages per
timestep. All three read the same event records, so they cannot disagree.

---

## 1. Layers

| Layer | Package | Responsibility |
|---|---|---|
| Simulation | `energyplus/` | 5-zone DX/VAV office, Chicago EPW, 15-min timestep |
| Bridge | `bridge/` | Sensor reads, actuator writes, safety clamps |
| Cognition | `agent/` | MCP tools, prompting, tool-call loop, memory, fallback |
| Observability | `agent/stream.py` | Five-stage event bus (terminal + JSONL + UI) |
| Presentation | `dashboard/` | Streamlit + Plotly; renders only, never recomputes |

### Bridge (`bridge/`)

- **`ep_runner.py`** — registers a callback on
  `begin_zone_timestep_after_init_heat_balance`, skipping warmup steps and
  those where `api_data_fully_ready()` is false. Wraps every callback in an
  exception firewall so agent code can never abort the simulation (INV-7).
- **`ep_reader.py`** — resolves variable handles once, then reads zone
  temperature, occupancy, CO₂, both setpoints, lighting energy and outdoor
  temperature per step. Invalid handles fail loud and dump
  `available_api_data.csv` rather than silently returning zeros.
- **`ep_writer.py`** — the only component that writes actuators, and the only
  place safety is enforced.

### Cognition (`agent/`)

`orchestrator.py` is the heartbeat. Per timestep:

```
read sensors → build prompt → tool-call rounds → [nudge] → clamp → apply → log
```

`llm_client.py` wraps an OpenAI-compatible endpoint (Groq) hosting Llama 3.x.

---

## 2. Tool-calling architecture

Five MCP tools are declared in `agent/mcp_server.py`, each with a Pydantic
input schema that doubles as the validation boundary:

| Tool | Purpose | Class |
|---|---|---|
| `set_hvac_setpoint` | Cooling + heating setpoint for one zone | write |
| `set_lighting_level` | Lighting fraction 0.0–1.0 for one zone | write |
| `read_sensors` | Current building state | read |
| `get_energy_report` | Cumulative kWh, demand, savings vs baseline | read |
| `predict_comfort` | PMV estimate for a proposed setpoint | pure |

**Writes are queued, not immediate.** Tool calls accumulate into a single
`ControlAction`, applied once at end-of-timestep. One atomic write per step
means no half-applied state if a later tool call fails, and the clamp layer
sees the complete intent rather than a stream of fragments.

**Schema conversion is lossy on purpose.** `mcp_to_openai_tool()` strips
Pydantic's `$defs`, `title` and per-property `description` noise. Smaller
models degrade measurably when handed verbose JSON Schema.

### Self-correction

Three independent recovery mechanisms, in order of cost:

1. **Argument validation** — the first tool call is validated against its
   Pydantic model. On failure the rejection is fed back as a `tool` message
   naming the violated rule, and one corrective call is made.
2. **Salvage parsing** — small models sometimes emit tool calls as JSON inside
   the text channel. `_salvage_tool_calls()` recovers those instead of losing
   the step.
3. **Action nudge** — if the model observed without acting, one corrective
   round restates the exact required calls (`build_action_nudge_prompt`).

If all three fail, `agent/policy.py` supplies a deterministic
occupancy-aware action. The building is never left uncontrolled.

---

## 3. Safety: the prompt is advisory, the writer is law

Constraints appear in the system prompt so the model *plans* within them, but
every one is re-enforced in `bridge/clamps.py` before any actuator write.
An LLM cannot violate these regardless of what it emits:

| ID | Invariant |
|---|---|
| INV-1 | Cooling setpoint ∈ [20, 26] °C occupied; ≤ 28 °C only when unoccupied |
| INV-2 | Heating setpoint ∈ [18, 24] °C occupied; ≥ 16 °C only when unoccupied |
| INV-3 | Heating ≤ cooling − 1 °C (deadband) |
| INV-4 | Max ±2 °C change per timestep (ramp limit) |
| INV-5 | Lighting ∈ [0, 1]; floor 0.3 in any occupied zone |
| INV-6 | LLM failure → deterministic adaptive policy |
| INV-7 | No agent exception may abort EnergyPlus |
| INV-9 | Baseline and agent runs share identical physics and weather |

Every clamp is logged with requested value, applied value and the rule that
fired — visible in the terminal stream (stage ④) and the dashboard. Clamps are
a feature to show a judge, not an embarrassment to hide: they prove the safety
layer is real rather than prompt-hope.

---

## 4. Prompt engineering

Full rationale in **[`prompt_playbook.md`](prompt_playbook.md)**. Summary:

- **Sensor data is injected into the user message**, not fetched via a tool
  round. Small models frequently stop after a read-only call; pre-loading the
  snapshot removes the single largest cause of "observed but never acted".
- **Constraints precede procedure** in the system prompt — Llama-class models
  weight early tokens more heavily for rule-following.
- **One worked example** (few-shot n=1). A second added tokens without
  improving compliance.
- **`temperature=0.2`, `max_tokens=600`** — a control loop should return the
  same decision for the same state.
- **Rolling 3-decision memory** (`agent/memory.py`) as one-line summaries, not
  raw transcripts. This is the anti-oscillation mechanism.

---

## 5. Latency and token budget

| Control | Mechanism |
|---|---|
| Timeout | 15 s hard cap, one retry, then deterministic fallback |
| Rate limit | ≥ 2 s spacing; `Retry-After` honoured on HTTP 429 |
| Cadence | `AGENT_EVERY_N_STEPS` — LLM every Nth step, hold setpoints between |
| Model tier | 8B for development, 70B for scored runs |
| Accounting | Per-call tokens and latency recorded in the decision log |

The cadence knob is the main lever: at `N=4` the LLM decides every hour of
simulated time and holds setpoints in between, cutting token spend ~4× with
minimal control loss, since a building's thermal mass moves slowly relative to
a 15-minute step. Held steps still re-apply the last action so actuator
ownership never lapses back to the schedule.

---

## 6. Handling lengthy simulation logs

A 96-step run produces megabytes of EnergyPlus output (`.eso`, `.mtr`,
`.err`, CSV). **None of it is ever sent to the model.** The reduction chain:

```
EnergyPlus raw output  →  SensorReading (dataclass)  →  to_compact()  →  ~15 numbers
```

`to_compact()` rounds to one decimal and keeps only what a control decision
needs. Everything else is written to disk for audit:

| Artifact | Contents |
|---|---|
| `agent_decisions.jsonl` | One record per timestep: snapshot, tool calls, clamps, actions, tokens |
| `stream_events.jsonl` | Five stage events per timestep (drives replay + UI) |
| `actuator_timeline.csv` | Every actuator write, tidy format |
| `runtime_final_state.idf` | Final setpoints written back as a valid IDF |
| `summary.json` | Run totals: kWh, savings, calls, tokens, fallbacks, clamps |

The decision log is flushed and `fsync`'d per timestep (INV-10), so a run
killed mid-flight still yields a complete audit trail up to the last step.

---

## 7. Measuring savings honestly

`scripts/run_baseline.py` runs the same building with no agent attached and
sums `Electricity:Facility [J](TimeStep)` from `eplusout.csv`.
`scripts/generate_comparison.py` then emits tidy artifacts to
`data/comparison/` which the dashboard renders without recomputation.

Three deliberate choices keep the number defensible:

1. **INV-9** — baseline and agent runs use the same IDF physics and the same
   weather file. The only difference is EMS visibility.
2. **Same source column** — both totals come from the same EnergyPlus
   electricity series, so the comparison is like-for-like.
3. **Comfort is reported over occupied zone-steps only**, and returns *not
   measured* rather than 100% when no zone was ever occupied — a compliance
   rate over an empty sample is undefined, and reporting 100% there would
   overstate the result.

---

## 8. Known limitations

- The model is a synthetic reference building, not calibrated against metered
  data from a real site.
- PMV uses fixed clothing/metabolic assumptions (`met=1.1`, `clo=0.7`) and
  treats mean radiant temperature as equal to air temperature.
- Grid carbon intensity is a representative diurnal curve, not a live feed.
- Zones are reasoned about independently; there is no cross-zone coordination
  or explicit peak-demand optimiser.
- Wall-clock latency (~1–2 s per LLM call) is acceptable against a 15-minute
  control interval but would need an async design for real-time deployment.
