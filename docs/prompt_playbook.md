# EcoLoop Prompt Engineering Playbook

How we get reliable control decisions out of open-source Llama models on Groq
(`llama-3.1-8b-instant` for `--dev`, `llama-3.3-70b-versatile` for scored runs).

This document matches the **current** code in `agent/prompts.py`,
`agent/llm_client.py`, `agent/orchestrator.py`, and `agent/memory.py`.
It is the detailed companion to §4–§5 of [`architecture.md`](architecture.md).

---

## 1. Principles

Open 8B–70B models are weaker than frontier models at: staying on format for
many turns, remembering constraints stated once, and resisting “helpful”
violations (e.g. overcooling past the safe limit). Every rule below exists
to compensate for one of those failure modes.

1. **The prompt is advisory; code is law.** Constraints are listed in
   `SYSTEM_PROMPT`, but `bridge/clamps.py` re-enforces INV-1…5 on every write.
2. **Determinism over creativity.** `temperature=0.2`, `max_tokens=600`
   (`agent/llm_client.py`). A control loop wants the same decision for the
   same state.
3. **Act first, narrate second.** Sensor data is pre-injected. The model’s
   first response must contain **control tool calls**. Prose is optional
   (`REASONING` / `EXPECTED_OUTCOME`); empty content with valid tools is OK.
4. **Token budget is a hard resource.** Groq free tier ≈ 100K tokens/day on
   70B (500K on 8B). Prefer cadence (`AGENT_EVERY_N_STEPS=4`) over longer
   prompts when budget is tight.

---

## 2. System prompt — what the code actually sends

Source of truth: `SYSTEM_PROMPT` in `agent/prompts.py`. Order in the live
prompt:

| Block | Purpose |
|---|---|
| Identity + mission | Minimise kWh; PMV in [-0.5, +0.5] occupied; CO2 below 1000 ppm; respect peak |
| Exact zone list | `SPACE1-1` … `SPACE5-1` — kills `ZONE_1` hallucinations |
| **CRITICAL RULE — YOU MUST ACT** | Do **not** call `read_sensors`; data is already in the user message |
| Control playbook A–E | Mechanical defaults per occupancy / PMV / grid |
| Tools | Primary writes vs optional reads; `read_sensors` marked **avoid** |
| Hard constraints 1–5 | Mirror INV-1…5 so the model *plans* inside the envelope |
| Output format | `REASONING:` + `EXPECTED_OUTCOME:` (actions = tool calls, not prose) |

### Playbook (embedded in system prompt)

| Rule | When | Default action |
|---|---|---|
| A | `occ = 0` | cool 28 °C, heat 16 °C, lights 0.0 |
| B | occupied, PMV in band | cool 25 °C, heat 20 °C |
| C | occupied, PMV > +0.5 | cool 24 °C, heat 20 °C |
| D | occupied, PMV < -0.5 | cool 26 °C, heat 21 °C |
| E | grid HIGH + demand approaching/exceeded | prefer A-style setbacks; dim occupied lights to 0.5 |

Why this beats a free-form “think carefully” prompt: 8B models follow
**numbered / lettered procedures** more reliably than abstract goals.

There is **no few-shot narrative example** in the current system prompt —
token cost was redirected into the per-timestep **REQUIRED ACTIONS** block
(below), which is higher leverage for “issue these tools now.”

---

## 3. Timestep (user) prompt

Built by `build_timestep_prompt()` every LLM cadence step:

```text
=== TIMESTEP {n} | HH:MM ===

## Current building state (LIVE SENSOR DATA — do not call read_sensors)
{compact JSON from SensorReading.to_compact()}

## Grid context
  Carbon intensity : … gCO2/kWh  [HIGH|LOW]
  Demand status    : OK | APPROACHING | EXCEEDED
  Threshold        : PEAK_DEMAND_THRESHOLD_KW

## Agent memory
{AgentMemory.render() — last 3 decisions}

## REQUIRED ACTIONS THIS TIMESTEP (issue these tool calls NOW)
  - SPACE2-1: UNOCCUPIED -> set_hvac_setpoint(cooling 28.0, heating 16.0)
               + set_lighting_level(0.0)
  - SPACE3-1: OCCUPIED (temp 25.2 C) -> set_hvac_setpoint per comfort playbook

Issue the set_hvac_setpoint / set_lighting_level tool calls listed above,
adjusting values with your judgement (playbook rules A–E). Then give your
REASONING and EXPECTED_OUTCOME as text.
```

### Design rules (enforced in code)

- **Round to 1 decimal** in `to_compact()` — fewer tokens, less echo noise.
- **Inject sensors** — the #1 historical failure mode was “call `read_sensors`
  then stop.” Pre-loading removes that dead-end.
- **REQUIRED ACTIONS** — explicit per-zone checklist; the model still may
  adjust numbers, but it cannot claim it “didn’t know what to call.”
- **Memory = 3 one-line summaries** with last setpoints — anti-oscillation,
  not a transcript dump.
- **Never paste** EnergyPlus `.eso` / CSV / `.err` into the prompt. Logs stay
  on disk for audit; the LLM only sees the structured snapshot.

---

## 4. Action nudge (self-correction for “observed, never acted”)

If after the tool-call loop the pending `ControlAction` is still empty,
`orchestrator` appends `build_action_nudge_prompt()` and does **one** more
LLM round:

```text
Timestep N: your previous response contained NO control tool calls.
That is a protocol violation …
  set_hvac_setpoint(zone="SPACE1-1", …) and set_lighting_level(…)
  …
Respond ONLY with tool calls. No text.
```

If that still fails → `policy_action(reading)` (adaptive occupancy setbacks)
and the log is tagged `[NUDGE-MISS]` / `[AUTO]`.

Separately, `llm_client` may:

1. Reject invalid tool args with a precise range (including ramp-aware bounds)
   and allow **one** corrective call.
2. **Salvage** JSON tool calls from freeform text when the model skips the
   function-calling channel.

---

## 5. Latency and budget management

| Lever | Default | Effect |
|---|---|---|
| `TIMEOUT_S` | 15 s | Then retry once; then `LLMUnavailable` → policy |
| `AGENT_CALL_SPACING_S` | 2.0 s | Stay under Groq ~30 req/min |
| `AGENT_EVERY_N_STEPS` | often 4 in scored/demo runs | ~4× fewer LLM calls; holds re-apply last action |
| `AGENT_MAX_TOOL_ROUNDS` | env-tunable | Caps multi-tool chatter per step |
| Model | 8B vs 70B | Dev vs scored; same prompts |

A full 96-step day with `N=4` is on the order of ~24 LLM decisions, not 96 —
critical for free-tier demos and for wall-clock video recording.

Held steps log `reasoning: "[HOLD] Between LLM cadence steps — holding last
setpoints."` and `held: true`. The dashboard hides HOLD rows so judges see
decision steps, not cadence filler.

---

## 6. Empty reasoning is not a failure

Small models frequently return **tool_calls with `content=null`**. That still
counts as a successful control step: actions are applied and logged.

Do **not** display empty reasoning as “Holding previous settings” — that
label is reserved for `held=true` cadence steps. The UI maps empty prose to an
honest “tool calls, no separate text rationale” caption
(`dashboard/components/agent_log.py`).

---

## 7. Anti-patterns (do not regress to these)

| Anti-pattern | Failure |
|---|---|
| Forcing a `read_sensors` first turn | 8B stops after the read; building stays on schedule |
| `temperature` ≥ 0.7 | Oscillating setpoints, format breaks |
| Asking for JSON **and** tool calls as dual sources of truth | Model picks one at random; tools = actions, text = rationale only |
| Pasting CSV / `.err` “for context” | Token blow-up; model quotes the log |
| Restating constraints only in the user message | Drift after many turns; keep them in `SYSTEM_PROMPT` |
| Trusting the prompt for safety | Always clamp in `EPWriter` |
| Few-shot examples that contradict playbook A–E | Confuses small models; prefer REQUIRED ACTIONS |
| Inventing “issue none” as the happy path | Current contract is **must act**; policy covers true no-ops after nudge miss |

---

## 8. Where to edit

| Change | File |
|---|---|
| Mission, playbook, constraints, output labels | `agent/prompts.py` → `SYSTEM_PROMPT` |
| Per-step layout / REQUIRED ACTIONS | `agent/prompts.py` → `build_timestep_prompt` |
| Nudge wording | `agent/prompts.py` → `build_action_nudge_prompt` |
| Temp / tokens / timeout / spacing | `agent/llm_client.py` |
| Memory window | `agent/memory.py` (`window=3`) |
| Offline / chaos behaviour | `agent/policy.py` |
