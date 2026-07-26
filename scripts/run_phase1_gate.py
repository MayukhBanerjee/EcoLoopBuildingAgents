"""
run_phase1_gate.py — Phase 1 exit gate (T1.1-T1.5).

Assumes prepare_models + run_baseline (+ optional run_runtime_oracle) already ran.
Re-validates artifacts without re-simulating unless --rerun.

Usage:
  uv run python scripts/run_phase1_gate.py
  uv run python scripts/run_phase1_gate.py --rerun
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rerun", action="store_true", help="Re-run prepare + baseline + oracle")
    args = parser.parse_args()

    if args.rerun:
        for script in ("prepare_models.py", "run_baseline.py", "run_runtime_oracle.py"):
            print(f"\n>>> {script}")
            proc = subprocess.run([PY, str(ROOT / "scripts" / script)], cwd=str(ROOT))
            if proc.returncode != 0:
                print(f"FAIL - {script} exited {proc.returncode}")
                return 1

    rows: list[tuple[str, bool, str]] = []

    summary_path = ROOT / "data" / "baseline_results" / "summary.json"
    end_path = ROOT / "data" / "baseline_results" / "eplusout.end"
    err_path = ROOT / "data" / "baseline_results" / "eplusout.err"
    csv_path = ROOT / "data" / "baseline_results" / "eplusout.csv"
    edd_path = ROOT / "data" / "runtime_oracle" / "eplusout.edd"
    baseline_idf = ROOT / "energyplus" / "models" / "baseline.idf"
    runtime_idf = ROOT / "energyplus" / "models" / "runtime.idf"

    # Model prep presence
    ok = baseline_idf.is_file() and runtime_idf.is_file()
    rows.append(("PREP baseline.idf + runtime.idf", ok, "present" if ok else "missing"))

    if baseline_idf.is_file():
        b = baseline_idf.read_text(encoding="utf-8", errors="replace")
        ok = (
            "EcoLoop Demo Day" in b
            and "ZoneAirContaminantBalance" in b
            and "Until: 24:00,400.0;" in b
            and "SimulationControl" in b
            and "Output:EnergyManagementSystem" not in b
        )
        rows.append(("PREP baseline instrumentation", ok, "CO2+outputs+1-day runperiod"))

    if runtime_idf.is_file():
        r = runtime_idf.read_text(encoding="utf-8", errors="replace")
        rows.append(("PREP runtime EMS verbose", "Output:EnergyManagementSystem" in r, "EMS block"))

    # T1.1
    ok = end_path.is_file() and "EnergyPlus Completed Successfully" in end_path.read_text(
        encoding="utf-8", errors="replace"
    )
    severe = fatal = -1
    if err_path.is_file():
        err = err_path.read_text(encoding="utf-8", errors="replace")
        severe = len(re.findall(r"\*\* Severe  \*\*", err))
        fatal = len(re.findall(r"\*\*  Fatal  \*\*", err))
        ok = ok and severe == 0 and fatal == 0
    rows.append(("T1.1 success + 0 severe/fatal", ok, f"severe={severe} fatal={fatal}"))

    # T1.2 / T1.5 via summary
    if summary_path.is_file():
        s = json.loads(summary_path.read_text(encoding="utf-8"))
        rows.append(("T1.2 timesteps==96", s.get("timesteps") == 96, str(s.get("timesteps"))))
        rows.append(
            (
                "T1.5 summary.json kWh",
                isinstance(s.get("electricity_facility_kwh"), (int, float))
                and s["electricity_facility_kwh"] > 0,
                f"{s.get('electricity_facility_kwh')} kWh",
            )
        )
        rows.append(("T1.3 gate flag", bool(s.get("gate", {}).get("T1.3")), "from summary.json"))
    else:
        rows.append(("T1.2/T1.5 summary.json", False, "missing"))

    # T1.4
    if edd_path.is_file():
        edd = edd_path.read_text(encoding="utf-8", errors="replace")
        zones_ok = all(z in edd for z in ("SPACE1-1", "SPACE2-1", "SPACE3-1", "SPACE4-1", "SPACE5-1"))
        ok = "Zone Temperature Control" in edd and "Lights" in edd and zones_ok
        rows.append(("T1.4 eplusout.edd actuators", ok, str(edd_path)))
        # Phase 2 hint
        if "Electricity Rate" in edd:
            rows.append(
                (
                    "NOTE lights actuator key",
                    True,
                    "Lights / Electricity Rate [W] (not Electric Power Level)",
                )
            )
    else:
        rows.append(("T1.4 eplusout.edd", False, "run scripts/run_runtime_oracle.py"))

    print("\n=== Phase 1 Gate ===")
    all_required_ok = True
    for name, ok, detail in rows:
        if name.startswith("NOTE"):
            print(f"[INFO] {name}: {detail}")
            continue
        mark = "PASS" if ok else "FAIL"
        if not ok and not name.startswith("NOTE"):
            all_required_ok = False
        print(f"[{mark}] {name}")
        if detail:
            print(f"       {detail}")

    print(
        "\nEXIT GATE:",
        "GREEN - baseline frozen; proceed to Phase 2"
        if all_required_ok
        else "RED - fix failures before Phase 2",
    )
    return 0 if all_required_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
