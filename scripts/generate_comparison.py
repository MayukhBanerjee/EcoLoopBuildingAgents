#!/usr/bin/env python
"""
generate_comparison.py — Phase 5 comparison artifacts for the dashboard.

Reads frozen baseline + a chosen agent run, writes ONLY tidy files under
data/comparison/. The Streamlit dashboard never recomputes — it only renders.

Outputs
-------
  data/comparison/energy_timeseries.csv
  data/comparison/zone_temps.csv
  data/comparison/decisions.jsonl   (trimmed agent trace for the UI)
  data/comparison/kpis.json

Usage
-----
    uv run python scripts/generate_comparison.py
    uv run python scripts/generate_comparison.py --run data/agent_results/20260726_180746_dev
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))

from agent.comfort import comfort_ok, pmv  # noqa: E402
from bridge.constants import CONTROLLED_ZONES  # noqa: E402

BASELINE_DIR = ROOT / "data" / "baseline_results"
AGENT_ROOT = ROOT / "data" / "agent_results"
OUT_DIR = ROOT / "data" / "comparison"
JOULES_TO_KWH = 1.0 / 3_600_000.0

# Exact EnergyPlus CSV headers (silent-zero class bugs if these typo)
EP_ELEC_COL = "Electricity:Facility [J](TimeStep)"
EP_ZONE_TEMP = {
    z: f"{z}:Zone Mean Air Temperature [C](TimeStep)" for z in CONTROLLED_ZONES
}
EP_ZONE_OCC = {
    z: f"{z}:Zone People Occupant Count [](TimeStep)" for z in CONTROLLED_ZONES
}


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def _load_baseline() -> dict[str, Any]:
    summary_path = BASELINE_DIR / "summary.json"
    if not summary_path.is_file():
        raise FileNotFoundError(f"Baseline summary missing: {summary_path}")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))

    per_step = [float(x) for x in summary.get("per_step_kwh", [])]
    if not per_step:
        # Fall back to CSV accumulation
        csv_path = BASELINE_DIR / "eplusout.csv"
        per_step = _elec_steps_from_csv(csv_path)

    cum: list[float] = []
    total = 0.0
    for v in per_step:
        total += v
        cum.append(round(total, 6))

    temps, occ = _zone_series_from_csv(BASELINE_DIR / "eplusout.csv")
    return {
        "summary": summary,
        "per_step_kwh": per_step,
        "cum_kwh": cum,
        "temps": temps,
        "occ": occ,
        "baseline_kwh": float(summary.get("electricity_facility_kwh", cum[-1] if cum else 0.0)),
    }


def _find_col(header: list[str], exact: str) -> int | None:
    # Exact first, then strip-space fuzzy
    for i, h in enumerate(header):
        if h == exact or h.strip() == exact.strip():
            return i
    # Prefix match (EP sometimes pads trailing spaces)
    target = exact.strip()
    for i, h in enumerate(header):
        if h.strip().startswith(target.split(" [")[0]) and target.split(" [")[-1] in h:
            if exact.split(":")[0] in h or exact.startswith("Electricity"):
                if "TimeStep" in exact and "TimeStep" not in h:
                    continue
                if exact.split("[")[0].strip() in h:
                    return i
    for i, h in enumerate(header):
        if exact.split("[")[0].rstrip() in h and ("TimeStep" in h or "Electricity:Facility" in exact):
            if "Electricity:Facility" in exact and "Electricity:Facility" in h and "TimeStep" in h:
                return i
            if exact.split("[")[0].rstrip() in h and "TimeStep" in h and "Mean Air Temperature" in exact:
                zone = exact.split(":")[0]
                if h.startswith(zone):
                    return i
            if "Occupant Count" in exact and "Occupant Count" in h and "TimeStep" in h:
                zone = exact.split(":")[0]
                if h.startswith(zone):
                    return i
    return None


def _elec_steps_from_csv(csv_path: Path) -> list[float]:
    if not csv_path.is_file():
        return []
    with csv_path.open(encoding="utf-8", errors="replace", newline="") as fh:
        reader = csv.reader(fh)
        header = next(reader)
        idx = _find_col(header, EP_ELEC_COL)
        if idx is None:
            # try any Electricity:Facility TimeStep
            for i, h in enumerate(header):
                if "Electricity:Facility" in h and "TimeStep" in h:
                    idx = i
                    break
        if idx is None:
            return []
        steps: list[float] = []
        for row in reader:
            if len(row) <= idx:
                continue
            try:
                j = float(row[idx])
            except ValueError:
                continue
            steps.append(max(0.0, j) * JOULES_TO_KWH)
        return steps


def _zone_series_from_csv(csv_path: Path) -> tuple[dict[str, list[float]], dict[str, list[float]]]:
    temps: dict[str, list[float]] = {z: [] for z in CONTROLLED_ZONES}
    occ: dict[str, list[float]] = {z: [] for z in CONTROLLED_ZONES}
    if not csv_path.is_file():
        return temps, occ
    with csv_path.open(encoding="utf-8", errors="replace", newline="") as fh:
        reader = csv.reader(fh)
        header = next(reader)
        t_idx = {z: _find_col(header, EP_ZONE_TEMP[z]) for z in CONTROLLED_ZONES}
        o_idx = {z: _find_col(header, EP_ZONE_OCC[z]) for z in CONTROLLED_ZONES}
        for row in reader:
            for z in CONTROLLED_ZONES:
                ti = t_idx[z]
                oi = o_idx[z]
                if ti is not None and len(row) > ti:
                    try:
                        temps[z].append(float(row[ti]))
                    except ValueError:
                        temps[z].append(float("nan"))
                if oi is not None and len(row) > oi:
                    try:
                        occ[z].append(float(row[oi]))
                    except ValueError:
                        occ[z].append(0.0)
    return temps, occ


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _pick_agent_run(explicit: Path | None) -> Path | None:
    if explicit is not None:
        return explicit if explicit.is_dir() else None
    if not AGENT_ROOT.is_dir():
        return None
    candidates: list[tuple[int, float, Path]] = []
    for p in AGENT_ROOT.iterdir():
        if not p.is_dir():
            continue
        log = p / "agent_decisions.jsonl"
        if not log.is_file():
            log = p / "decisions.jsonl"
        if not log.is_file():
            continue
        n = sum(1 for ln in log.read_text(encoding="utf-8").splitlines() if ln.strip())
        # Prefer non-chaos, longer runs
        chaos_penalty = 0 if "_chaos" not in p.name else -10_000
        candidates.append((n + chaos_penalty, p.stat().st_mtime, p))
    if not candidates:
        return None
    candidates.sort(key=lambda t: (t[0], t[1]), reverse=True)
    return candidates[0][2]


def _load_agent(run_dir: Path) -> dict[str, Any]:
    summary_path = run_dir / "summary.json"
    summary = {}
    if summary_path.is_file():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))

    log_path = run_dir / "agent_decisions.jsonl"
    if not log_path.is_file():
        log_path = run_dir / "decisions.jsonl"
    decisions = _load_jsonl(log_path)

    # Cumulative energy + zone temps from decision snapshots (authoritative for agent)
    cum: list[float] = []
    temps: dict[str, list[float]] = {z: [] for z in CONTROLLED_ZONES}
    occ: dict[str, list[float]] = {z: [] for z in CONTROLLED_ZONES}
    for d in decisions:
        cum.append(float(d.get("energy_kwh", 0.0)))
        snap = d.get("sensor_snapshot") or {}
        zones = snap.get("zones") or {}
        for z in CONTROLLED_ZONES:
            zd = zones.get(z) or {}
            temps[z].append(float(zd.get("temp", float("nan"))))
            occ[z].append(float(zd.get("occ", 0)))

    # Prefer CSV if it has more timesteps than JSONL (full EP export)
    for candidate in (
        run_dir / "eplus" / "eplusout.csv",
        run_dir / "eplusout.csv",
    ):
        csv_steps = _elec_steps_from_csv(candidate)
        if len(csv_steps) > len(cum):
            total = 0.0
            cum = []
            for v in csv_steps:
                total += v
                cum.append(round(total, 6))
            t2, o2 = _zone_series_from_csv(candidate)
            if any(t2[z] for z in CONTROLLED_ZONES):
                temps, occ = t2, o2
            break

    agent_kwh = float(summary.get("agent_final_kwh", cum[-1] if cum else 0.0))
    return {
        "run_dir": run_dir,
        "summary": summary,
        "decisions": decisions,
        "cum_kwh": cum,
        "temps": temps,
        "occ": occ,
        "agent_kwh": agent_kwh,
    }


# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------

def _comfort_pct(decisions: list[dict[str, Any]]) -> tuple[float, int, int]:
    occupied = 0
    comfortable = 0
    for d in decisions:
        snap = d.get("sensor_snapshot") or {}
        zones = snap.get("zones") or {}
        for z, zd in zones.items():
            if int(zd.get("occ", 0) or 0) <= 0:
                continue
            occupied += 1
            if comfort_ok(pmv(float(zd.get("temp", 22.0)))):
                comfortable += 1
    if occupied == 0:
        return 100.0, 0, 0
    return round(comfortable / occupied * 100.0, 1), comfortable, occupied


def write_comparison(baseline: dict[str, Any], agent: dict[str, Any] | None) -> dict[str, Any]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    b_cum = baseline["cum_kwh"]
    n_base = len(b_cum)
    a_cum = (agent or {}).get("cum_kwh") or []
    n_agent = len(a_cum)
    n = max(n_base, n_agent, 1)

    # --- energy_timeseries.csv ---
    energy_path = OUT_DIR / "energy_timeseries.csv"
    with energy_path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(
            fh,
            fieldnames=[
                "step",
                "sim_hour",
                "sim_minute",
                "baseline_kwh_cum",
                "agent_kwh_cum",
                "savings_kwh_cum",
            ],
        )
        w.writeheader()
        last_a = 0.0
        for i in range(n):
            minute_total = i * 15
            b = b_cum[i] if i < n_base else (b_cum[-1] if b_cum else 0.0)
            if i < n_agent:
                a = a_cum[i]
                last_a = a
            else:
                a = "" if not a_cum else last_a
            a_val = float(a) if a != "" else None
            w.writerow(
                {
                    "step": i + 1,
                    "sim_hour": (minute_total // 60) % 24,
                    "sim_minute": minute_total % 60,
                    "baseline_kwh_cum": round(b, 6),
                    "agent_kwh_cum": "" if a_val is None else round(a_val, 6),
                    "savings_kwh_cum": ""
                    if a_val is None
                    else round(b - a_val, 6),
                }
            )

    # --- zone_temps.csv (long format) ---
    zone_path = OUT_DIR / "zone_temps.csv"
    with zone_path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(
            fh,
            fieldnames=[
                "step",
                "zone",
                "baseline_temp_c",
                "agent_temp_c",
                "baseline_occ",
                "agent_occ",
            ],
        )
        w.writeheader()
        b_temps = baseline["temps"]
        b_occ = baseline["occ"]
        a_temps = (agent or {}).get("temps") or {z: [] for z in CONTROLLED_ZONES}
        a_occ = (agent or {}).get("occ") or {z: [] for z in CONTROLLED_ZONES}
        for i in range(n):
            for z in CONTROLLED_ZONES:
                bt = b_temps[z][i] if i < len(b_temps[z]) else ""
                at = a_temps[z][i] if i < len(a_temps[z]) else ""
                bo = b_occ[z][i] if i < len(b_occ[z]) else ""
                ao = a_occ[z][i] if i < len(a_occ[z]) else ""
                w.writerow(
                    {
                        "step": i + 1,
                        "zone": z,
                        "baseline_temp_c": bt if bt == "" else round(float(bt), 3),
                        "agent_temp_c": at if at == "" else round(float(at), 3),
                        "baseline_occ": bo if bo == "" else int(float(bo)),
                        "agent_occ": ao if ao == "" else int(float(ao)),
                    }
                )

    # --- decisions.jsonl (UI trace) ---
    decisions_out = OUT_DIR / "decisions.jsonl"
    decisions = (agent or {}).get("decisions") or []
    with decisions_out.open("w", encoding="utf-8") as fh:
        for d in decisions:
            slim = {
                "timestep": d.get("timestep"),
                "sim_hour": d.get("sim_hour"),
                "sim_minute": d.get("sim_minute"),
                "fallback": d.get("fallback") or d.get("fallback_used", False),
                "held": d.get("held", False),
                "energy_kwh": d.get("energy_kwh"),
                "grid_label": d.get("grid_label"),
                "peak_status": d.get("peak_status"),
                "reasoning": d.get("reasoning", ""),
                "actions": d.get("actions") or d.get("actions_applied") or [],
                "tool_calls": [
                    {"tool": t.get("tool"), "args": t.get("args")}
                    for t in (d.get("tool_calls") or [])
                ],
                "clamp_events": d.get("clamp_events") or [],
                "sensor_snapshot": d.get("sensor_snapshot") or {},
            }
            fh.write(json.dumps(slim, default=str) + "\n")

    # --- kpis.json ---
    baseline_kwh = float(baseline["baseline_kwh"])
    agent_kwh = float((agent or {}).get("agent_kwh") or 0.0)
    if agent and a_cum:
        # For partial runs, report projected-day savings vs proportional baseline
        if n_agent < n_base and n_base > 0:
            expected_partial = baseline_kwh * (n_agent / n_base)
            savings_kwh = expected_partial - agent_kwh
            savings_pct = (savings_kwh / expected_partial * 100.0) if expected_partial > 0 else 0.0
            status = "partial"
        else:
            savings_kwh = baseline_kwh - agent_kwh
            savings_pct = (savings_kwh / baseline_kwh * 100.0) if baseline_kwh > 0 else 0.0
            status = "complete"
    elif agent is None:
        savings_kwh = 0.0
        savings_pct = 0.0
        status = "baseline_only"
    else:
        savings_kwh = 0.0
        savings_pct = 0.0
        status = "empty"

    comfort_pct, comfort_ok_n, comfort_occ_n = _comfort_pct(decisions)
    summary = (agent or {}).get("summary") or {}
    fallback_count = int(
        summary.get(
            "fallback_count",
            sum(1 for d in decisions if d.get("fallback") or d.get("fallback_used")),
        )
    )

    kpis = {
        "status": status,
        "run_id": summary.get("run_id") or ((agent or {}).get("run_dir").name if agent else None),
        "model": "llama-3.1-8b-instant" if (agent and "dev" in str((agent or {}).get("run_dir"))) else (
            "llama-3.3-70b-versatile" if agent else None
        ),
        "baseline_kwh": round(baseline_kwh, 3),
        "agent_kwh": round(agent_kwh, 3) if agent else None,
        "savings_kwh": round(savings_kwh, 3) if agent else None,
        "savings_pct": round(savings_pct, 1) if agent else None,
        "comfort_compliance_pct": comfort_pct,
        "comfort_occupied_steps": comfort_occ_n,
        "comfort_ok_steps": comfort_ok_n,
        "fallback_count": fallback_count,
        "decisions_count": len(decisions),
        "llm_calls": summary.get("llm_calls"),
        "total_tokens": summary.get("total_tokens"),
        "timesteps_baseline": n_base,
        "timesteps_agent": n_agent,
        "total_clamp_events": summary.get(
            "total_clamp_events",
            sum(len(d.get("clamp_events") or []) for d in decisions),
        ),
        "files": {
            "energy_timeseries": str(energy_path.relative_to(ROOT)),
            "zone_temps": str(zone_path.relative_to(ROOT)),
            "decisions": str(decisions_out.relative_to(ROOT)),
        },
    }
    kpis_path = OUT_DIR / "kpis.json"
    kpis_path.write_text(json.dumps(kpis, indent=2), encoding="utf-8")
    return kpis


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate EcoLoop Phase 5 comparison data")
    parser.add_argument(
        "--run",
        type=Path,
        default=None,
        help="Agent run directory (default: best non-chaos run under data/agent_results)",
    )
    parser.add_argument(
        "--baseline-only",
        action="store_true",
        help="Write comparison with baseline only (agent pending).",
    )
    args = parser.parse_args()

    print("=== EcoLoop comparison generator ===")
    baseline = _load_baseline()
    print(f"Baseline: {baseline['baseline_kwh']:.3f} kWh, {len(baseline['cum_kwh'])} steps")

    agent = None
    if not args.baseline_only:
        run_dir = _pick_agent_run(args.run.resolve() if args.run else None)
        if run_dir is None:
            print("WARNING: no agent run found — writing baseline-only comparison.")
        else:
            print(f"Agent run: {run_dir}")
            agent = _load_agent(run_dir)
            print(
                f"Agent: {agent['agent_kwh']:.3f} kWh, "
                f"{len(agent['cum_kwh'])} steps, "
                f"{len(agent['decisions'])} decisions"
            )

    kpis = write_comparison(baseline, agent)
    print(f"Wrote artifacts to {OUT_DIR}")
    print(json.dumps(kpis, indent=2))
    print("DONE")


if __name__ == "__main__":
    main()
