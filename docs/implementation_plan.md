# EcoLoop — S-Grade Phase-Wise Implementation Plan

Honeywell Campus Hackathon · Question 1 · Mayukh Banerjee

This is the execution contract. Every phase has an objective, tasks, hard
constraints, test cases, edge cases, and an **exit gate**. Do not start a phase
until the previous gate passes. Gates are cheap to check and exist so a failure
at 2 AM is caught in the phase that caused it, not three phases later.

---

## 0. Verified Ground Truth (facts, not assumptions)

Checked against the actual installed files on this machine. **The original plan
had wrong values for several of these — using them would fail silently.**

| Fact | Value | Consequence |
|---|---|---|
| EnergyPlus version | 26.1.0 at `C:\EnergyPlusV26-1-0` | `pyenergyplus` importable by adding this dir to `sys.path` |
| Zone names in IDF | `SPACE1-1` … `SPACE5-1` + `PLENUM-1` | **Not** `ZONE_1/2/3`. Plenum is uncontrolled — exclude it from control |
| Lights object names | `SPACE1-1 Lights 1` … `SPACE5-1 Lights 1` | Lights actuator key is the **Lights object name**, not the zone name |
| People object names | `SPACE1-1 People 1` … | Occupancy variable key is the zone name; count comes from `Zone People Occupant Count` |
| IDF timestep | `Timestep,4` → 15-minute steps | Matches the 15-min agent cadence natively — no remapping needed |
| Run periods | Feb 1–5 **and** Jun 1–5 (10 days) | 960 steps = 960 LLM calls. Must trim to 1 day (96 steps) for demo |
| CO2 simulation | **Absent** (`ZoneAirContaminantBalance` not in IDF) | CO2 variable handles will be −1. Must patch IDF or use occupancy proxy |
| Thermostats | `ZoneControl:Thermostat` + dual setpoint, per zone | EMS actuator `Zone Temperature Control` / `Cooling Setpoint` / `<zone>` is available |
| Weather file | `usa_il_chicago.epw` (copied) | Use for both baseline and agent run — identical inputs is non-negotiable |
| **LLM requirement** | Problem statement mandates an **open-source LLM** (Llama 3, Mistral, Qwen…) | GPT-4o-mini is **non-compliant**. Use Groq-hosted open models (OpenAI-compatible API at `https://api.groq.com/openai/v1`) |
| Groq free-tier budget | `llama-3.3-70b-versatile`: 30 req/min, **100K tokens/day**. `llama-3.1-8b-instant`: 500K tokens/day. `openai/gpt-oss-120b`: 200K tokens/day | One 96-step run ≈ 96K tokens on lean prompts → **~1 full 70B run/day**. Develop on 8B, score on 70B |

## 0.1 Problem-Statement Compliance Matrix

Every graded deliverable from the brief, mapped to a repo artifact. Check this
before submitting — missing any row is free points lost.

| Brief requires | Repo artifact | Built in |
|---|---|---|
| Fully functional source code (EnergyPlus wrapper + LLM orchestration + communication bus) | `bridge/` + `agent/` + `main.py` | Phases 2–4 |
| Building models: baseline `.idf` **and modified versions generated during runtime** | `energyplus/models/baseline.idf` + instrumented `runtime.idf` + `data/agent_results/runtime_final_state.idf` snapshot + actuator override timeline CSV | Phases 1, 4 |
| Quantitative savings dashboard with **explicit % kWh reduction** while maintaining comfort | Streamlit dashboard + `data/comparison/kpis.json` export | Phase 5 |
| System Architecture Document covering tool-calling architecture, **prompt engineering strategies, prompt latency management, handling lengthy simulation logs** | `docs/architecture.md` + `docs/prompt_playbook.md` | Phases 3, 6 |
| PoC video ≤ 3 min showing live data flow EnergyPlus → LLM → control actions | `docs/demo_video.mp4` | Phase 6 |
| Open-source LLM, MCP/agentic tools, **self-correction loops** (Criterion 4, 15%) | Groq + Llama, `agent/mcp_server.py`, validation-retry loop in `agent/llm_client.py` | Phase 3 |
| Feedback metrics: zone temps, IAQ, energy, **PMV** | `ep_reader` + `comfort.py` | Phases 2–3 |
| Reasoning inputs: occupancy comfort, **peak demand thresholds, local carbon grid intensity** | `agent/grid.py` + prompt injection | Phase 3f |
| Presentation on provided template; all files PDF/ZIP | Slides + final ZIP | Phase 6 |

## 1. System Invariants (enforced in code, never trusted to the LLM)

These live in `bridge/ep_writer.py` and `bridge/fallback.py`. The prompt also
states them, but the prompt is advisory; the writer is law.

| ID | Invariant | Enforcement point |
|---|---|---|
| INV-1 | Cooling setpoint ∈ [20, 28] °C (28 only when zone unoccupied) | `EPWriter.apply` clamp |
| INV-2 | Heating setpoint ∈ [16, 24] °C (16 only when zone unoccupied) | `EPWriter.apply` clamp |
| INV-3 | Heating setpoint < cooling setpoint − 1 °C (deadband) | `EPWriter.apply` — swap/clamp, log warning |
| INV-4 | Max setpoint change ±2 °C per timestep (ramp rate) | `EPWriter` tracks last applied value per zone |
| INV-5 | Lighting level ∈ [0.0, 1.0]; never 0 in an occupied zone (min 0.3) | `EPWriter.apply` clamp using last occupancy reading |
| INV-6 | LLM failure/timeout → safe defaults (22 °C cool / 20 °C heat, lights untouched) | `fallback.py` via orchestrator try/except |
| INV-7 | Simulation must never crash from an agent error | Orchestrator catches **all** exceptions in callback |
| INV-8 | Only `SPACE1-1..SPACE5-1` are controllable; `PLENUM-1` read-only | Zone whitelist constant in `bridge/__init__.py` |
| INV-9 | Baseline and agent runs use identical IDF physics + weather | Agent IDF differs only by Output/EMS-visibility objects |
| INV-10 | Every decision is logged to JSONL **before** the next timestep starts | Orchestrator flushes file per step |

INV-7 is worth 30% of the score by itself (System Integration = "runs without
crashing"). INV-9 is what makes the savings number defensible when a judge asks
"how do you know the AI caused the difference?"

---

## Phase 0 — Environment Gate (30 min)

**Objective:** prove every external dependency works before writing logic.

### Tasks
1. `pip install -r requirements.txt` in a venv (Python 3.10+, 64-bit — must
   match EnergyPlus bitness or the DLL load fails).
2. Remove `energyplus-api` from requirements if present — the real Python API
   ships **inside** the install dir as `pyenergyplus`; the PyPI package of that
   name is not it. Import via `sys.path.insert(0, ENERGYPLUS_DIR)`.
3. Run `scripts/verify_energyplus_api.py` — imports `pyenergyplus.api`.
4. Create a Groq account, get `GROQ_API_KEY` (no credit card needed), verify a
   1-token test call against **both** `llama-3.1-8b-instant` and
   `llama-3.3-70b-versatile`. Record observed latency (expect <1 s).
5. `git init`, first commit of the scaffold, create GitHub repo, push.

### Test cases
| ID | Test | Pass condition |
|---|---|---|
| T0.1 | `python scripts/verify_energyplus_api.py` | Prints OK, exit 0 |
| T0.2 | `python -c "from pyenergyplus.api import EnergyPlusAPI; print(EnergyPlusAPI.api_version())"` | Prints a version, no DLL error |
| T0.3 | Minimal Groq call script (both models) | Returns a completion; latency logged; tool-calling flag confirmed |
| T0.4 | `energyplus.exe --version` | `26.1.0` |

### Edge cases
- **32-bit Python** → `OSError: [WinError 193]` on DLL load. Fix: install 64-bit Python.
- **OneDrive/spaces in path**: workspace is `C:\Mayukh Main\...` (has a space).
  Always pass quoted absolute paths to EnergyPlus; never rely on relative cwd.
- **Groq outage or account issue** → Ollama with `llama3.1:8b` locally is the
  documented backup (same OpenAI-compatible client, different base URL). Pull
  the Ollama model tonight so the backup actually exists.

**Exit gate:** all four tests green, repo pushed. ⛔ Do not proceed otherwise.

---

## Phase 1 — Model Preparation + Baseline Run (45 min)

**Objective:** a trimmed, instrumented `runtime.idf` and a completed baseline
simulation in `data/baseline_results/` that the dashboard can diff against.

### Tasks
1. **Trim run period** in *both* `baseline.idf` and `runtime.idf`: delete
   `Run Period 1` (Feb), change `Run Period 2` to Jun 1 → Jun 1.
   Result: exactly 96 timesteps of 15 min = 24 simulated hours.
2. **Add output variables** to `runtime.idf` *and* `baseline.idf` (identical —
   INV-9), 15-min reporting frequency:
   - `Zone Mean Air Temperature`, `Zone People Occupant Count`,
     `Site Outdoor Air Drybulb Temperature`,
     `Zone Thermostat Cooling Setpoint Temperature`,
     `Zone Thermostat Heating Setpoint Temperature`
   - `Output:Meter,Electricity:Facility,TimeStep;`
3. **CO2 decision** (pick one, timebox 15 min):
   - *Preferred:* add `ZoneAirContaminantBalance` (CO2=Yes, outdoor schedule
     400 ppm via `Schedule:Compact`) + `Output:Variable` for
     `Zone Air CO2 Concentration`. People objects emit CO2 by default.
   - *Fallback:* skip CO2 entirely; report IAQ as an occupancy-derived proxy in
     `agent/comfort.py` and say so honestly in `architecture.md`. **Do not**
     leave dead CO2 code that reads −1 handles.
4. **Add EMS visibility** to `runtime.idf` only (does not change physics):
   `Output:EnergyManagementSystem, Verbose, Verbose, Verbose;` — produces the
   `.edd` file listing every legal actuator name. This is your actuator oracle.
5. Implement `scripts/run_baseline.py`: subprocess call to `energyplus.exe -w
   <epw> -d data/baseline_results -r baseline.idf` (the `-r` gives readable
   CSV). Run it.

### Test cases
| ID | Test | Pass condition |
|---|---|---|
| T1.1 | Baseline run completes | `eplusout.end` says "EnergyPlus Completed Successfully"; 0 severe errors in `eplusout.err` |
| T1.2 | Timestep count | Output CSV has exactly 96 data rows |
| T1.3 | Sanity physics | Zone temps in 15–30 °C band; facility electricity > 0 every occupied step |
| T1.4 | `.edd` exists (runtime run only, Phase 2) | Contains `Zone Temperature Control` and `Lights` actuator entries for all 5 SPACE zones |
| T1.5 | Baseline total kWh recorded | Write `data/baseline_results/summary.json` with total kWh — the dashboard's denominator |

### Edge cases
- **Warnings vs errors**: `eplusout.err` will contain warnings — only `** Severe **`
  and `** Fatal **` block the gate.
- **June in Chicago** = cooling-dominated day. Good: cooling setpoint relaxation
  is where the savings are. If savings look thin, switching to a hotter EPW
  (e.g. Phoenix from the same WeatherData dir) is a legitimate one-line lever.
- **Editing IDF**: prefer direct text edits over eppy for these few objects —
  eppy version pinned in requirements may not know the V26 IDD. If eppy fights
  you, drop it; it is not on the critical path.

**Exit gate:** T1.1–T1.3 + T1.5 green. Baseline numbers are frozen — never
re-run baseline after agent tuning starts unless the IDF physics changed.

---

## Phase 2 — Bridge Layer (90 min) — highest technical risk

**Objective:** Python reads live sensors and writes one hardcoded setpoint into
a running simulation, provably.

### 2a. `state_manager.py` + `ep_runner.py`
- Singleton module holding `EnergyPlusAPI` instance + one state object. Reader,
  writer, runner all import from here (prevents the classic two-state crash).
- Runner registers `callback_begin_zone_timestep_after_init_heat_balance`
  (fires once per zone timestep — cleaner than the system-timestep callback,
  which can fire multiple times per 15-min step during HVAC iteration).
- **Warmup guard** (the #1 EnergyPlus API mistake): the callback fires during
  sizing and warmup days too. First lines of every callback:

```python
if not api.exchange.api_data_fully_ready(state):
    return
if api.exchange.warmup_flag(state):
    return
```

- Request variables **before** `run_energyplus`:
  `api.exchange.request_variable(state, name, key)` for every sensor —
  handles are −1 otherwise even if the IDF has Output:Variable lines.
- `run()` blocks until sim completes; that is fine — the dashboard is a
  separate process reading files (never share state across processes).

### 2b. `ep_reader.py`
- Zone list constant: `CONTROLLED_ZONES = ["SPACE1-1", ..., "SPACE5-1"]`.
- Handle cache; on first read, **assert every handle ≥ 0** and if any is −1,
  dump `api.exchange.list_available_api_data_csv(state)` to
  `data/logs/available_api_data.csv` and raise. Fail loud, fail early.
- Energy: use `get_meter_handle(state, "Electricity:Facility")` +
  `get_meter_value` (Joules for the current timestep) → accumulate → kWh.
  This is more robust than the demand-power variable.
- Also read current thermostat setpoints (so the agent and the ramp limiter
  know the true starting point, not a guess).

### 2c. `ep_writer.py`
- Actuators (names verified against the `.edd` from Phase 1):
  - `("Zone Temperature Control", "Cooling Setpoint", "<ZONE>")`
  - `("Zone Temperature Control", "Heating Setpoint", "<ZONE>")`
  - `("Lights", "Electric Power Level", "<ZONE> Lights 1")` — note: value is
    **Watts**, not a 0–1 fraction. Read each zone's design lighting level once
    (from IDF: 1584 W-class values) and multiply: `watts = level * design_watts`.
- Implements INV-1 … INV-5. Keeps `last_applied: dict[zone, (cool, heat)]` for
  the ramp limiter. Every clamp event is logged with before/after values —
  these log lines are *evidence for the judges* that safety is code-enforced.

### 2d. `fallback.py`
- `safe_action() -> ControlAction`: 22 °C cooling / 20 °C heating all zones,
  lights untouched. Called by the orchestrator on any agent exception.

### Test cases
| ID | Test | Pass condition |
|---|---|---|
| T2.1 | Callback smoke: run sim with a callback that only counts invocations | Exactly 96 non-warmup calls |
| T2.2 | Reader values print each step | Temps 15–30 °C, occupancy 0–~30, energy monotonically accumulating |
| T2.3 | All handles valid | No −1 after data-ready; T fails loud otherwise |
| T2.4 | Hardcoded write: force `SPACE1-1` cooling to 26 °C from step 20 | `Zone Thermostat Cooling Setpoint Temperature` output for SPACE1-1 shows 26 after step 20; zone temp drifts up; facility kWh **drops** vs baseline |
| T2.5 | Clamp unit tests (pure Python, mocked api) | 35 °C in → 28 out; heating 25 + cooling 24 in → deadband enforced; ramp: 22→28 requested → 24 applied |
| T2.6 | Lights actuator | Setting level 0.0 for SPACE2-1 shows lights electricity drop in output CSV |

### Edge cases
- **Callback exceptions kill the sim silently** or hang it — wrap the entire
  callback body in try/except and log; never let an exception escape (INV-7).
- **Sizing periods**: `api_data_fully_ready` is false during sizing — guard
  handles that (already in 2a).
- **Actuator released**: once you set an actuator you own it for the rest of the
  run. Don't call `reset_actuator` mid-run unless intentionally returning
  control to schedules.
- **Two runs in one process**: EnergyPlus state cannot be trivially reused.
  For repeated runs, spawn a fresh Python process (`scripts/` wrappers do this).

**Exit gate:** T2.1–T2.6 green. This is tonight's hardest gate — everything
after it is normal Python.

---

## Phase 3 — Agent Layer (75 min)

**Objective:** an LLM that receives real sensor JSON and returns valid tool
calls, with memory, comfort math, and cost/latency under control.

### 3a. `llm_client.py` — Groq, open-source models only
- Client: the standard `openai` SDK pointed at Groq —
  `OpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")`.
  No new dependency; swap `base_url` to Ollama for the offline backup.
- **Two-model strategy** (env `MODEL_NAME` / `DEV_MODEL_NAME`):
  - Dev/tuning runs: `llama-3.1-8b-instant` — 500K tokens/day, blazing fast,
    good enough to validate the loop mechanics.
  - Scored/final runs: `llama-3.3-70b-versatile` (best tool-use quality;
    "Llama 3" matches the brief's examples verbatim) — but only ~1 full run/day
    on the 100K-token free budget. Alternative with 2× budget:
    `openai/gpt-oss-120b` (open-weight, JSON mode, 200K tokens/day).
- API mechanics: system prompt is `{"role": "system", ...}` at index 0 of
  `messages` (there is **no `system=` kwarg** — bug in the original plan).
  Tools adapter converts the MCP registry's `input_schema` into
  `{"type": "function", "function": {name, description, parameters}}`.
- `temperature=0.2`, `max_tokens=600`, `tool_choice="auto"`. Low temperature is
  non-negotiable with open-source models — determinism beats creativity in a
  control loop.
- Hard timeout (15 s) + one retry with 2 s backoff; on second failure raise
  `LLMUnavailable` → orchestrator applies fallback. Never let a hung HTTPS
  call stall the sim.
- Rate-limit discipline: 30 req/min → enforce ≥2 s spacing between calls
  (a simple `time.monotonic()` gate). On HTTP 429, honor `retry-after`.
- Log tokens + latency per call into the decision log — running token total
  lets you see the daily budget burning down *before* it bites.

### 3a-bis. Self-correction loop (explicitly scored in Criterion 4)
Structure it as a named, visible feature — judges are told to look for it:
1. LLM responds → every tool call's args validated through the pydantic models.
2. On violation (out-of-range setpoint, unknown zone, >2 °C ramp request,
   missing REASONING block), do **not** silently clamp yet — send one
   corrective turn back: `{"role": "tool", ...}` result containing the exact
   violation, e.g. *"REJECTED: cooling_setpoint 17.0 below minimum 20.0 for
   occupied SPACE3-1. Re-issue within constraints."*
3. LLM retries once. If still invalid, the writer clamps (INV-1..5) and the
   log records `"self_correction": {"attempted": true, "succeeded": false}`.
4. Cap: 1 corrective round per timestep (budget + latency). Log every round —
   the JSONL trace showing violation → correction → valid action is the single
   best artifact for the 15% autonomy criterion.

### 3b. `prompts.py`
- System prompt with the corrected zone names (`SPACE1-1…SPACE5-1`), real
  constraints (INV table verbatim), and the enforced
  `REASONING / ACTIONS / EXPECTED` output shape.
- Timestep prompt = compact JSON sensor snapshot + memory block (last 3
  decisions) + cumulative kWh vs baseline-so-far. Keep it under ~800 tokens:
  96 calls × (prompt + completion) is your entire bill and latency budget.

### 3c. `mcp_server.py` + `tools.py`
- 5 tools as scaffolded. `tools.ToolExecutor.execute()` dispatch table:
  - `read_sensors` → latest cached `SensorReading` (do **not** re-read EP
    mid-callback; the orchestrator reads once per step and caches).
  - `set_hvac_setpoint` / `set_lighting_level` → accumulate into one
    `ControlAction`, applied **once** at end of step (batching means the ramp
    limiter sees one change per zone per step — INV-4 stays sound).
  - `get_energy_report` → agent cumulative kWh vs baseline kWh *for the same
    elapsed steps* (precompute baseline per-step series from Phase 1 CSV).
  - `predict_comfort` → `comfort.py`.
- Unknown tool name / malformed args → return an error string to the LLM
  (it can self-correct), never raise.

### 3d. `comfort.py`
- Simplified PMV (Fanger) with fixed assumptions: met = 1.1, clo = 0.7 summer,
  air speed 0.1 m/s, RH 50%. Document the assumptions in the docstring — judges
  reward honesty about simplification more than fake precision.
- `pmv(temp_c) -> float` and `comfort_ok(pmv) -> bool` (|PMV| ≤ 0.5).

### 3e. `memory.py`
- `deque(maxlen=3)` of `{timestep, summary, actions}`; `render()` returns the
  formatted block for the prompt. This is what prevents setpoint oscillation
  and is your "it's a real agent" talking point.

### 3f. `grid.py` — carbon intensity + peak demand (brief-mandated inputs)
The brief's Reasoning bullet names "peak demand thresholds and local carbon
grid intensity" — cheap to add, directly scored:
- Static 24-hour carbon-intensity profile (gCO2/kWh) for the Indian grid shape
  (low overnight, evening peak) hardcoded as a 24-element list with a source
  comment. `carbon_intensity(hour) -> float`.
- `PEAK_DEMAND_THRESHOLD_KW` env var; `peak_status(current_kw) -> str`
  ("OK" / "APPROACHING" / "EXCEEDED").
- Both injected into every timestep prompt and returned by `get_energy_report`
  so the agent can reason "grid is dirty + demand near peak → shed load now,
  pre-cool later when grid is clean." One such reasoning line in the demo
  video is worth the whole module.

### Test cases
| ID | Test | Pass condition |
|---|---|---|
| T3.1 | Offline prompt test: feed a canned `SensorReading` (SPACE2-1 empty + cold, SPACE3-1 hot + occupied) | LLM relaxes SPACE2-1, cools SPACE3-1 within ramp limit, cuts SPACE2-1 lights |
| T3.2 | Tools adapter round-trip | OpenAI accepts the converted schema; tool_call args parse back through pydantic models |
| T3.3 | PMV sanity | pmv(24.0) ≈ within [−0.5, 0.5]; pmv(29) > 0.5; pmv(18) < −0.5 |
| T3.4 | Memory window | 5 appends → only last 3 rendered, oldest evicted |
| T3.5 | Timeout drill: point client at a black-hole URL | `LLMUnavailable` raised in <20 s; no hang |
| T3.6 | Malformed tool args (`cooling_setpoint: "cold"`) | Executor returns error string; no exception escapes |
| T3.7 | Self-correction drill: canned prompt engineered to tempt a violation (e.g. "zone is 30 °C" → model wants 18 °C cooling) | Rejection message sent; second response within constraints; both rounds in log |
| T3.8 | Grid module | `carbon_intensity(3) < carbon_intensity(19)`; peak_status transitions at threshold |
| T3.9 | Rate-limit pacing | 10 back-to-back calls take ≥ 18 s (2 s gate working) |

### Edge cases (several are specific to open-source models)
- **LLM returns prose but no tool calls** → treat as "no change this step";
  log it; that's a valid decision, not an error.
- **Tool call embedded in content as JSON text** instead of the `tool_calls`
  field — smaller open models (especially 8B) do this. Add a salvage parser:
  if `tool_calls` is empty but content contains a fenced JSON block matching a
  tool schema, parse and use it (and count it as a self-correction event).
- **Hallucinated tool name** (`set_temperature` instead of
  `set_hvac_setpoint`) → rejection message with the valid tool list; the
  self-correction loop handles it.
- **Hallucinated zone name** (`ZONE_1` — the model may "know" generic examples)
  → rejection message listing the five real `SPACE*-1` zones.
- **LLM calls set_hvac twice for the same zone in one step** → last write wins
  inside the batched `ControlAction`; ramp limit applied to the final value.
- **Rate limit (429)** → single retry with 2 s backoff, then fallback. 96 calls
  at ~1/loop-iteration won't hit limits, but a retry storm mid-demo would.
- **Prompt drift**: temps as `24.183333` bloat tokens — round to 1 decimal in
  the serializer.

**Exit gate:** T3.1–T3.6 green *offline* (no EnergyPlus involved). The agent
layer must be fully testable without a running sim — that separation is also an
"elegance" scoring point.

---

## Phase 4 — Closed-Loop Integration (60 min)

**Objective:** one full 96-step run, end to end, zero crashes, decision log on
disk, energy result different from baseline.

### Tasks
1. `orchestrator.py` per-step sequence:
   read → memory.render → prompt → LLM (timeout-guarded) → execute tools →
   batch-apply `ControlAction` via writer → memory.append → **append + flush**
   JSONL line. Whole body in try/except → `fallback.safe_action()` (INV-6/7).
2. **LLM cadence throttle**: env var `AGENT_EVERY_N_STEPS=1` (every 15 min).
   If token budget or latency bites, set 2 (every 30 min) — the writer holds
   last setpoints between decisions. Build the knob now, decide later.
3. `main.py`: wire runner/reader/writer/llm/orchestrator; on completion print a
   summary (total kWh, vs baseline %, fallback count, self-corrections, LLM
   error count, total tokens used) and write `data/agent_results/summary.json`.
4. **Modified-IDF deliverable** (brief requires "modified versions generated
   during runtime"): at run end, write
   `data/agent_results/runtime_final_state.idf` (runtime.idf + a generated
   comment header + `Schedule:Compact` objects encoding the final agent
   setpoints) and `data/agent_results/actuator_timeline.csv` (step, zone,
   cooling, heating, lights — every applied override). Together these *are*
   the runtime-modified building model.
5. Full runs: all integration shakeout on `llama-3.1-8b-instant` (cheap
   budget); once T4.1–T4.4 pass, one scored run on `llama-3.3-70b-versatile`.
   Then a second 8B run to confirm crash-free repeatability.
6. Commit + push. Tag `v0.1-closed-loop`.

### Test cases
| ID | Test | Pass condition |
|---|---|---|
| T4.1 | Full run completes | 96 steps, `eplusout.end` success, exit 0 |
| T4.2 | Decision log integrity | `agent_decisions.jsonl` has 96 lines, each parses, each has reasoning + actions + sensor snapshot |
| T4.3 | Chaos drill: unset `GROQ_API_KEY`, run | Sim **still completes** on fallback defaults; log marks every step `"fallback": true` |
| T4.3b | Modified-IDF artifacts exist | `runtime_final_state.idf` parses (EnergyPlus dry run) and `actuator_timeline.csv` has one row per applied override |
| T4.4 | Kill-mid-run drill: Ctrl-C at step ~40 | JSONL contains all completed steps (flush-per-step works); no corrupt last line |
| T4.5 | Savings direction | Agent total kWh < baseline total kWh (any margin — tuning is Phase 5) |
| T4.6 | Comfort audit script | % of occupied zone-steps with \|PMV\| ≤ 0.5 reported; target ≥ 90% |

### Edge cases
- **First timestep**: memory is empty, no baseline delta yet — prompt must
  render cleanly with "no prior decisions" text, not `None`.
- **Occupancy schedule edges** (6–7 AM ramp-in): agent must re-tighten relaxed
  setpoints *before* people arrive is ideal but not required; the writer's
  occupied-zone clamps make late reaction safe, just less efficient.
- **kWh vs baseline early in day**: near-zero denominators make % savings
  explode — report absolute kWh alongside % and guard divide-by-zero.
- If T4.5 fails (agent *uses more* energy): usual cause is the LLM tightening
  setpoints in occupied zones "for comfort". Fix in prompt: "never set cooling
  below current zone temperature unless PMV > +0.5".

**Exit gate:** T4.1–T4.5 green, T4.6 measured. This gate = 30% of the rubric
banked. Everything after this is presentation.

---

## Phase 5 — Comparison Data + Dashboard (90 min, day 2)

**Objective:** the quantitative-savings dashboard: judge opens it, sees the gap
between two lines, sees the agent thinking.

### Tasks
1. `scripts/generate_comparison.py`: reads baseline + agent `eplusout.csv` and
   the JSONL; writes tidy CSVs to `data/comparison/`:
   `energy_timeseries.csv` (step, baseline_kwh_cum, agent_kwh_cum),
   `zone_temps.csv`, `kpis.json` (savings %, comfort %, fallback count,
   decisions count, avg LLM latency). **Dashboard never recomputes — it only
   renders these files.**
2. `dashboard/app.py` + components:
   - KPI row: Energy Saved %, Comfort Compliance %, Timesteps, Model.
   - Cumulative energy chart (baseline red, agent green, shaded gap).
   - Zone temp timeline with comfort band (20–26 °C) shaded; setpoint-change
     markers from the decision log.
   - Reasoning trace: last 10 decisions, expandable, fallback steps flagged.
   - Use `st_autorefresh`-style rerun **only** when a `--live` flag is set;
     static mode for judging (auto-rerun during a judge's click is annoying).
3. Screenshot the dashboard for slides.

### Test cases
| ID | Test | Pass condition |
|---|---|---|
| T5.1 | Comparison script on real Phase 4 outputs | CSVs written; kpis.json savings matches main.py summary within 0.1% |
| T5.2 | Dashboard cold start with **no** data dir | Friendly "run simulation first" message, no traceback |
| T5.3 | Dashboard with partial data (baseline only) | Renders baseline, marks agent "pending" |
| T5.4 | All charts render with the real 96-step data | No empty figures, axes labeled with units |

### Edge cases
- EnergyPlus CSV column headers are exact strings like
  `Electricity:Facility [J](TimeStep)` — pin them in one constants module;
  a header typo here is the classic silent-zero bug.
- Timestamp column has EnergyPlus's ` 24:00:00` convention — parse by row
  index (step number), not by datetime, for the demo.

**Exit gate:** T5.1–T5.4 green + screenshot saved to `docs/`.

---## Phase 6 — Hardening, Docs, Video, Submission (rest of day 2)

### Tasks
1. **Savings tuning pass** (timeboxed 60 min max): adjust prompt aggressiveness
   toward the 15–25% target. Levers, in order of safety: unoccupied relaxation
   (biggest, safest), lighting cuts in empty zones, pre-cooling before
   occupancy, +1 °C occupied cooling setpoint (comfort-check first). Re-run
   comfort audit (T4.6) after every change — do not trade comfort % for kWh %.
2. `docs/architecture.md` completed: layer diagram, data-flow table, prompt
   strategy, INV table, known limitations (LLM latency, synthetic model,
   single-agent). Export `docs/diagrams/system_flow.png`.
3. README: quick start that works on a clean clone (test it: fresh venv, follow
   your own README verbatim).
4. 3-min video script: 0:00 problem → 0:30 architecture diagram → 1:00 live
   console (reasoning scrolling) → 2:00 dashboard gap + KPI zoom → 2:40 rubric
   mapping. Record with OBS; keep the raw closed-loop console visible — the
   reasoning trace scrolling live *is* the wow moment.
5. Slides on Honeywell template. Final commit, tag `v1.0-submission`, ZIP.

### Final acceptance checklist (the S-grade bar)
- [ ] Clean clone → README steps → full loop runs (tested on a second machine or fresh folder if possible)
- [ ] 96/96 steps, zero crashes, chaos drill (no API key) still completes
- [ ] Savings 15–25% shown in dashboard, absolute kWh also shown
- [ ] Comfort compliance ≥ 90% of occupied zone-steps, audited by script
- [ ] JSONL trace: every step has reasoning, actions, snapshot
- [ ] All safety clamps unit-tested; clamp events visible in logs
- [ ] architecture.md, diagram, video, slides, ZIP done

---

## Risk Register

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| R1 | Actuator names wrong → writes silently ignored | Med | Fatal to savings | `.edd` file is the oracle (Phase 1 task 4); T2.4 proves effect in output CSV |
| R2 | Warmup callbacks pollute logic/logs | High if unguarded | High | Warmup guard in 2a; T2.1 counts exactly 96 |
| R3 | LLM hang mid-demo | Med | Fatal to demo | 15 s timeout + retry + fallback; chaos drill T4.3 |
| R4 | Agent *increases* energy | Med | High | Prompt rule + Phase 6 tuning levers; unoccupied relaxation alone guarantees savings |
| R5 | CO2 handles −1 crash reader | Certain if unpatched | Med | Phase 1 task 3 decision; fail-loud handle check T2.3 |
| R6 | Two-state API crash | Med | High | `state_manager.py` singleton |
| R7 | Runs out of time day 2 | Med | Med | Phases 5–6 are presentation-only; Phase 4 gate already banks 75% of rubric weight |
| R8 | **Groq daily token budget exhausted mid-tuning** (70B = 100K tokens/day ≈ 1 full run) | High if ignored | High | Develop on `llama-3.1-8b-instant` (500K/day); 70B only for scored runs; running token counter in logs; `openai/gpt-oss-120b` (200K/day) as second wallet |
| R9 | Small OSS model emits malformed/hallucinated tool calls | High | Med | Self-correction loop (3a-bis), salvage parser, pydantic validation, writer clamps as last line |
| R10 | Groq 30 RPM limit hit by retry storms | Low | Med | 2 s call spacing gate; honor `retry-after`; max 1 correction round per step |

## Rubric Mapping (where each point is won)

| Criterion | Weight | Won by | Proven by |
|---|---|---|---|
| System integration | 30% | INV-7 crash-proofing, fallback, state singleton, warmup guard | T4.1, T4.3, T4.4 |
| Energy efficiency | 25% | Unoccupied relaxation + lighting + tuning levers | Dashboard gap, kpis.json |
| Thermal comfort | 20% | PMV math + writer clamps + comfort audit | T4.6 report, clamp logs |
| Agentic autonomy | 15% | **Open-source LLM on Groq** + 5 MCP tools + memory window + **self-correction loop** + grid-aware reasoning | JSONL log with correction rounds, T3.1, T3.7 |
| Presentation | 10% | Dashboard, architecture.md, video, slides | Phase 5–6 checklist |
