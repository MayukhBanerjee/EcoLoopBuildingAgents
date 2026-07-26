"""
run_baseline.py — Phase 1 uncontrolled EnergyPlus baseline run + gate checks.

Runs:
  energyplus.exe -w <epw> -d data/baseline_results -r <baseline.idf>

Writes:
  data/baseline_results/eplusout.csv
  data/baseline_results/summary.json   (dashboard denominator)

Exit 0 only if T1.1, T1.2, T1.3, T1.5 pass.

Usage:
  uv run python scripts/prepare_models.py
  uv run python scripts/run_baseline.py
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

EP_DIR = Path(os.getenv("ENERGYPLUS_DIR", r"C:\EnergyPlusV26-1-0"))
EP_EXE = EP_DIR / "energyplus.exe"
IDF = ROOT / "energyplus" / "models" / "baseline.idf"
EPW = ROOT / "energyplus" / "weather" / "usa_il_chicago.epw"
OUT_DIR = ROOT / "data" / "baseline_results"

EXPECTED_STEPS = 96
JOULES_TO_KWH = 1.0 / 3_600_000.0
CONTROLLED_ZONES = ("SPACE1-1", "SPACE2-1", "SPACE3-1", "SPACE4-1", "SPACE5-1")


def _die(msg: str, code: int = 1) -> None:
    print(f"FAIL - {msg}")
    raise SystemExit(code)


def _count_severe_fatal(err_text: str) -> tuple[int, int]:
    severe = len(re.findall(r"\*\* Severe  \*\*", err_text))
    fatal = len(re.findall(r"\*\*  Fatal  \*\*", err_text))
    return severe, fatal


def _find_col(columns: list[str], *needles: str) -> str | None:
    for col in columns:
        if all(n.lower() in col.lower() for n in needles):
            return col
    return None


def run_energyplus() -> None:
    if not EP_EXE.is_file():
        _die(f"energyplus.exe not found at {EP_EXE}")
    if not IDF.is_file():
        _die(f"baseline.idf missing at {IDF}. Run scripts/prepare_models.py first.")
    if not EPW.is_file():
        _die(f"weather file missing at {EPW}")

    # Fresh output directory (keep .gitkeep)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for child in OUT_DIR.iterdir():
        if child.name == ".gitkeep":
            continue
        if child.is_file():
            child.unlink()
        elif child.is_dir():
            shutil.rmtree(child)

    cmd = [
        str(EP_EXE),
        "-w",
        str(EPW.resolve()),
        "-d",
        str(OUT_DIR.resolve()),
        "-r",
        str(IDF.resolve()),
    ]
    print("Running:", " ".join(f'"{c}"' if " " in c else c for c in cmd))
    proc = subprocess.run(
        cmd,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    (OUT_DIR / "energyplus_stdout.txt").write_text(proc.stdout or "", encoding="utf-8")
    (OUT_DIR / "energyplus_stderr.txt").write_text(proc.stderr or "", encoding="utf-8")
    if proc.returncode != 0:
        _die(f"energyplus exited {proc.returncode}\n{proc.stderr[-2000:]}")


def validate_and_summarize() -> dict:
    end_path = OUT_DIR / "eplusout.end"
    err_path = OUT_DIR / "eplusout.err"
    csv_path = OUT_DIR / "eplusout.csv"

    # --- T1.1 ---
    if not end_path.is_file():
        _die("T1.1: eplusout.end missing")
    end_text = end_path.read_text(encoding="utf-8", errors="replace")
    if "EnergyPlus Completed Successfully" not in end_text:
        _die(f"T1.1: success banner missing in eplusout.end:\n{end_text[:500]}")
    print("PASS T1.1 - EnergyPlus Completed Successfully")

    if not err_path.is_file():
        _die("T1.1: eplusout.err missing")
    err_text = err_path.read_text(encoding="utf-8", errors="replace")
    severe, fatal = _count_severe_fatal(err_text)
    if severe or fatal:
        _die(f"T1.1: found {severe} Severe and {fatal} Fatal in eplusout.err")
    print(f"PASS T1.1 - 0 Severe / 0 Fatal (warnings are OK)")

    # --- T1.2 ---
    if not csv_path.is_file():
        # Some builds write eplusout.csv only with -r; fallback names
        candidates = list(OUT_DIR.glob("*.csv"))
        if not candidates:
            _die("T1.2: no CSV output found (was -r passed?)")
        csv_path = candidates[0]
        print(f"WARN - using CSV {csv_path.name}")

    df = pd.read_csv(csv_path)
    # Drop possible footer / blank rows
    df = df.dropna(how="all")
    n = len(df)
    if n != EXPECTED_STEPS:
        _die(f"T1.2: expected {EXPECTED_STEPS} data rows, got {n}")
    print(f"PASS T1.2 - CSV has {n} timestep rows")

    # --- T1.3 ---
    cols = list(df.columns)
    elec_col = _find_col(cols, "Electricity:Facility")
    if not elec_col:
        _die(f"T1.3: Electricity:Facility column missing. Columns sample: {cols[:8]}")

    temp_cols = [
        c
        for c in cols
        if "Zone Mean Air Temperature" in c
        and any(z in c for z in CONTROLLED_ZONES)
        and "TimeStep" in c
    ]
    if not temp_cols:
        temp_cols = [
            c
            for c in cols
            if "Mean Air Temperature" in c
            and any(z in c for z in CONTROLLED_ZONES)
        ]
    if not temp_cols:
        _die("T1.3: no Zone Mean Air Temperature columns found")

    temps = df[temp_cols].apply(pd.to_numeric, errors="coerce")
    tmin, tmax = float(temps.min().min()), float(temps.max().max())
    per_zone = {
        c.split(":")[0]: {
            "min_c": round(float(temps[c].min()), 2),
            "max_c": round(float(temps[c].max()), 2),
        }
        for c in temp_cols
    }
    # Soft comfort band 15-30 C; hard fail only on absurd physics
    if tmin < 5.0 or tmax > 45.0:
        _die(f"T1.3: zone temps out of hard sanity band ({tmin:.1f}..{tmax:.1f} C)")
    if tmin < 15.0 or tmax > 30.0:
        print(
            f"WARN T1.3 - some SPACE zone temps outside 15-30 C soft band "
            f"({tmin:.1f}..{tmax:.1f} C); per-zone={per_zone}"
        )
    else:
        print(f"PASS T1.3 - zone temps {tmin:.1f}..{tmax:.1f} C")

    elec_j = pd.to_numeric(df[elec_col], errors="coerce").fillna(0.0)
    if not (elec_j > 0).any():
        _die("T1.3: facility electricity never > 0")

    occ_cols = [
        c
        for c in cols
        if "Zone People Occupant Count" in c
        and "TimeStep" in c
        and any(z in c for z in CONTROLLED_ZONES)
    ]
    if not occ_cols:
        occ_cols = [
            c
            for c in cols
            if "People Occupant Count" in c and any(z in c for z in CONTROLLED_ZONES)
        ]
    if occ_cols:
        occ = df[occ_cols].apply(pd.to_numeric, errors="coerce").fillna(0.0)
        occupied_mask = occ.sum(axis=1) > 0
        if occupied_mask.any() and not (elec_j[occupied_mask] > 0).all():
            zero_steps = int((elec_j[occupied_mask] <= 0).sum())
            _die(f"T1.3: {zero_steps} occupied steps with zero facility electricity")
        print("PASS T1.3 - facility electricity > 0 on occupied steps")
    else:
        print("PASS T1.3 - facility electricity has positive values")

    # --- T1.5 ---
    total_j = float(elec_j.sum())
    total_kwh = total_j * JOULES_TO_KWH
    per_step_kwh = (elec_j * JOULES_TO_KWH).tolist()

    summary = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "idf": str(IDF.resolve()),
        "epw": str(EPW.resolve()),
        "energyplus_dir": str(EP_DIR),
        "timesteps": n,
        "timestep_minutes": 15,
        "electricity_facility_joules": total_j,
        "electricity_facility_kwh": round(total_kwh, 6),
        "zone_temp_min_c": round(tmin, 3),
        "zone_temp_max_c": round(tmax, 3),
        "zone_temp_per_zone": per_zone,
        "csv": str(csv_path.resolve()),
        "columns": {
            "electricity": elec_col,
            "zone_temps": temp_cols,
            "occupancy": occ_cols,
        },
        "notes": {
            "co2_enabled": True,
            "run_period": "June 1 single day (96 x 15-min steps)",
            "lights_actuator_hint": "See data/runtime_oracle/eplusout.edd — Lights/Electricity Rate [W]",
        },
        "per_step_kwh": [round(x, 8) for x in per_step_kwh],
        "gate": {
            "T1.1": True,
            "T1.2": True,
            "T1.3": True,
            "T1.5": True,
        },
    }
    summary_path = OUT_DIR / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"PASS T1.5 - baseline total {total_kwh:.3f} kWh -> {summary_path}")
    return summary


def main() -> int:
    print("=== EcoLoop Phase 1 - Baseline Run ===")
    run_energyplus()
    summary = validate_and_summarize()
    print(
        f"OK - baseline frozen at {summary['electricity_facility_kwh']:.3f} kWh "
        f"over {summary['timesteps']} steps"
    )
    print("EXIT GATE: GREEN for T1.1 / T1.2 / T1.3 / T1.5")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
