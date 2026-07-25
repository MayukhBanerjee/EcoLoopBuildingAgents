# EcoLoop Prompt Engineering Playbook

How we get reliable control decisions out of an open-source model
(`llama-3.3-70b-versatile` / `llama-3.1-8b-instant` on Groq). This document is
referenced by the System Architecture deliverable — the brief explicitly asks
for prompt engineering strategy, prompt latency management, and handling of
lengthy simulation logs.

## 1. Principles (why open-source models need different prompting)

Open 8B–70B models are weaker than frontier models at: staying in output
format over many turns, remembering constraints stated once, and resisting
"helpful" violations (e.g. overcooling a hot zone past the safe limit). Every
rule below exists to compensate for one of those failure modes.

1. **The prompt is advisory; code is law.** Constraints appear in the prompt so
   the model *plans* within them, but every constraint is re-enforced in
   `ep_writer.py`. Never rely on the prompt for safety.
2. **Determinism over creativity.** `temperature=0.2`, `max_tokens=600`.
   A control loop wants the same decision for the same state.
3. **Structure in, structure out.** Sensor state goes in as compact JSON
   (rounded to 1 decimal). Output shape is enforced:
   `REASONING / ACTIONS(tool calls) / EXPECTED`.
4. **Token budget is a hard resource.** Groq free tier = 100K tokens/day on
   70B. Target ≤ 700 prompt + ≤ 400 completion tokens per timestep.

## 2. System prompt — structure that works on Llama-class models

Order matters: identity → mission → hard constraints → decision procedure →
one worked example → output format. Put constraints BEFORE the procedure
(Llama models weight early tokens more for rule-following).

```text
You are EcoLoop, the autonomous energy-management agent for a 5-zone
commercial building simulated in EnergyPlus.

MISSION (in priority order):
1. Never violate a HARD CONSTRAINT.
2. Keep occupied zones comfortable: PMV within [-0.5, +0.5].
3. Minimize total facility kWh vs the uncontrolled baseline.
4. Prefer shedding load when grid carbon intensity is HIGH or demand is
   near the peak threshold.

HARD CONSTRAINTS (violations are rejected and you must re-issue):
- Zones are exactly: SPACE1-1, SPACE2-1, SPACE3-1, SPACE4-1, SPACE5-1.
- Cooling setpoint: 20.0-26.0 C occupied; up to 28.0 C only if occupancy=0.
- Heating setpoint: 18.0-24.0 C occupied; down to 16.0 C only if occupancy=0.
- Change no setpoint by more than 2.0 C in one timestep.
- Lighting level 0.0-1.0; minimum 0.3 in any zone with occupancy > 0.

EACH TIMESTEP:
1. Read the sensor snapshot below. Identify: unoccupied zones still
   conditioned, occupied zones outside comfort, grid/peak status.
2. If proposing a setpoint change larger than 1.0 C in an occupied zone,
   call predict_comfort first.
3. Issue tool calls. If you have nothing beneficial to change, issue none
   and say why.

EXAMPLE OF A GOOD DECISION:
Snapshot: SPACE2-1 is 21.4 C with 0 occupants; SPACE3-1 is 25.9 C with 8
occupants; grid intensity HIGH.
Good actions: set_hvac_setpoint(SPACE2-1, cooling=23.4, heating=18.0)
[+2 C ramp toward relaxed], set_lighting_level(SPACE2-1, 0.0),
predict_comfort(SPACE3-1, 24.0) then set_hvac_setpoint(SPACE3-1,
cooling=24.0, heating=20.0).

OUTPUT FORMAT (always, exactly):
REASONING: 2-3 sentences on what the state shows.
ACTIONS: your tool calls (or "none").
EXPECTED: 1 sentence on what should change next timestep.
```

Why each piece earns its tokens:
- **Priority-ordered mission** resolves the energy-vs-comfort tie the way we
  want, every time, instead of letting the model pick per-call.
- **Exact zone list** kills the most common hallucination (`ZONE_1`).
- **One worked example** (few-shot n=1) is the single highest-leverage trick
  for small models — it anchors both format and policy. Two examples were
  tested to add tokens without improving compliance.
- **"Issue none and say why"** gives the model a legal no-op, which prevents
  invented actions when the building is already optimal.

## 3. Timestep prompt — lean, structured, stateful

```text
TIMESTEP 34/96 | sim time 08:30 | outdoor 29.3 C
GRID: carbon intensity HIGH (evening ramp in 9h) | demand 41.2 kW /
peak threshold 55.0 kW (OK)
ENERGY: agent 118.4 kWh cumulative vs baseline 131.0 kWh (-9.6%)

MEMORY (your last 3 decisions):
T31: relaxed SPACE2-1 (unoccupied), cut its lights to 0
T32: cooled SPACE3-1 to 24.0 after predict_comfort OK
T33: no change (stable)

SENSORS:
{"SPACE1-1": {"temp": 23.1, "occ": 11, "cool_sp": 23.5, "heat_sp": 20.0},
 "SPACE2-1": {"temp": 24.8, "occ": 0,  "cool_sp": 25.4, "heat_sp": 18.0}, ...}

Decide your actions for this timestep.
```

Rules:
- **Round everything to 1 decimal.** `24.183333` wastes tokens and invites the
  model to echo noise back.
- **Memory as 3 one-line summaries**, not raw transcripts. This is the anti-
  oscillation mechanism: the model can see "I already relaxed SPACE2-1."
- **Deltas, not dumps** — never paste EnergyPlus logs or CSVs into a prompt.
  The bridge reduces the whole simulation state to ~15 numbers. (This is the
  answer to the brief's "handling lengthy simulation logs" question: logs go
  to JSONL on disk for audit; the LLM only ever sees the structured snapshot.)
- Include **current setpoints** so a 2 °C ramp is computable by the model, not
  guessed.

## 4. Self-correction loop (Criterion 4 evidence)

On any invalid tool call, one corrective turn is sent back as the tool result:

```text
REJECTED: cooling_setpoint 17.0 is below the occupied minimum 20.0 for
SPACE3-1 (occupancy=8). Valid range now: 22.0-26.0 (2.0 C ramp limit from
current 24.0). Re-issue this action within constraints.
```

Rejection message anatomy — each element measurably improves the retry:
state the violated rule, state the *currently* legal range (after ramp
math — don't make the model redo it), and give an imperative instruction.
One retry max; then the writer clamps and the log records the failure.

## 5. Latency and budget management (brief-mandated topic)

- Groq serves Llama 3.3 70B at ~275 tokens/s → a full decision round is
  ~1–2 s. 96 steps ≈ 3–5 min wall-clock for a 24-h simulated day.
- 2 s minimum spacing between calls (30 req/min limit), `retry-after` honored
  on 429.
- Per-call token accounting in the JSONL; a run prints its total so you know
  what's left of the 100K/day budget before starting another 70B run.
- Cadence knob `AGENT_EVERY_N_STEPS` degrades gracefully to 30-min decisions
  if budget or latency demands it.

## 6. Anti-patterns (tried or foreseeable — do not do these)

| Anti-pattern | Failure it causes |
|---|---|
| Restating constraints only in the timestep prompt | Model drifts after ~20 turns; keep them in the system prompt, which is resent every call anyway (stateless API) |
| `temperature` ≥ 0.7 | Oscillating setpoints, format breaks |
| Asking for JSON output *and* tool calls | 8B models pick one at random; use tool calls only, prose for REASONING |
| Pasting the CSV/err log "for context" | Blows the token budget; model quotes the log instead of deciding |
| Threatening/roleplay pressure ("you will be shut down") | No measurable compliance gain, wastes tokens |
| Letting the model compute the ramp math | Off-by-one violations; give it the pre-computed legal range in rejections |
