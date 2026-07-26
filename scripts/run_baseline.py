#!/usr/bin/env python
"""
run_baseline.py — uncontrolled baseline EnergyPlus run (Phase 1).

Runs baseline.idf with no agent attached and writes data/baseline_results/,
including the summary.json that main.py and the dashboard read to compute
percentage savings.

INV-9: the baseline and the agent run must share identical physics and
weather, or the savings number means nothing. The only difference between
baseline.idf and runtime.idf is EMS *visibility* (actuator dictionary output),
which does not change the simulated building. Both are produced by
scripts/prepare_models.py from the same source model.

The kWh total is summed from the "Electricity:Facility [J](TimeStep)" column
of eplusout.csv — the same column the comparison generator reads — so the
baseline figure is always traceable to a raw EnergyPlus output file.

Usage
-----
    uv run python scripts/run_baseline.py
    uv run python scripts/run_baseline.py --keep-existing   # skip if present
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env", override=False)
except ImportError:
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("EcoLoop.baseline")

ENERGYPLUS_DIR = os.getenv("ENERGYPLUS_DIR", r"C:\EnergyPlusV26-1-0")
IDF = ROOT / "energyplus" / "models" / "baseline.idf"
EPW = ROOT / "energyplus" / "weather" / "usa_il_chicago.epw"
OUT_DIR = ROOT / "data" / "baseline_results"

JOULES_TO_KWH = 1.0 / 3_600_000.0
EXPECTED_TIMESTEPS = 96

ELEC_COL = "Electricity:Facility [J](TimeStep)"


def _check_prereqs() -> None:
    if not Path(ENERGYPLUS_DIR).is_dir():
        logger.error("ENERGYPLUS_DIR not found: %s", ENERGYPLUS_DIR)
        sys.exit(1)
    if not IDF.is_file():
        logger.error(
            "baseline.idf not found at %s — run scripts/prepare_models.py first.", IDF
        )
        sys.exit(1)
    if not EPW.is_file():
        logger.error("Weather file not found: %s", EPW)
        sys.exit(1)


def _run_energyplus() -> int:
    """Invoke EnergyPlus through the Python API (same API the bridge uses)."""
    sys.path.insert(0, ENERGYPLUS_DIR)
    from pyenergyplus.api import EnergyPlusAPI

    api = EnergyPlusAPI()
    state = api.state_manager.new_state()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    args = ["-w", str(EPW), "-d", str(OUT_DIR), "-r", str(IDF)]
    logger.info("run_energyplus %s", " ".join(args))
    exit_code = int(api.runtime.run_energyplus(state, args))
    api.state_manager.delete_state(state)
    return exit_code


def _find_column(header: list[str], target: str) -> int | None:
    for i, h in enumerate(header):
        if h.strip() == target.strip():
            return i
    # EnergyPlus sometimes pads or reorders; fall back to a tolerant match.
    for i, h in enumerate(header):
        if "Electricity:Facility" in h and "TimeStep" in h:
            return i
    return None


def _read_series(csv_path: Path) -> tuple[list[float], dict[str, list[float]]]:
    """Return (per-step kWh, {zone: temps}) straight from eplusout.csv."""
    if not csv_path.is_file():
        raise FileNotFoundError(f"EnergyPlus CSV not produced: {csv_path}")

    with csv_path.open(encoding="utf-8", errors="replace", newline="") as fh:
        reader = csv.reader(fh)
        header = next(reader)
        elec_idx = _find_column(header, ELEC_COL)
        if elec_idx is None:
            raise RuntimeError(
                f"Column {ELEC_COL!r} not found in {csv_path.name}. "
                "Check the Output:Variable block in baseline.idf."
            )
        temp_idx = {
            h.split(":")[0]: i
            for i, h in enumerate(header)
            if "Zone Mean Air Temperature" in h and "TimeStep" in h
        }

        per_step: list[float] = []
        temps: dict[str, list[float]] = {z: [] for z in temp_idx}
        for row in reader:
            if len(row) <= elec_idx:
                continue
            try:
                per_step.append(max(0.0, float(row[elec_idx])) * JOULES_TO_KWH)
            except ValueError:
                continue
            for zone, idx in temp_idx.items():
                if len(row) > idx:
                    try:
                        temps[zone].append(float(row[idx]))
                    except ValueError:
                        pass
    return per_step, temps


def _count_err(path: Path) -> tuple[int, int]:
    if not path.is_file():
        return 0, 0
    text = path.read_text(encoding="utf-8", errors="replace")
    return text.count("** Severe  **"), text.count("**  Fatal  **")


def _write_summary(per_step: list[float], temps: dict[str, list[float]]) -> dict[str, Any]:
    total_kwh = sum(per_step)
    severe, fatal = _count_err(OUT_DIR / "eplusout.err")

    per_zone = {
        zone: {"min_c": round(min(vals), 2), "max_c": round(max(vals), 2)}
        for zone, vals in sorted(temps.items())
        if vals
    }
    all_temps = [v for vals in temps.values() for v in vals]

    summary: dict[str, Any] = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "idf": str(IDF),
        "epw": str(EPW),
        "energyplus_dir": ENERGYPLUS_DIR,
        "timesteps": len(per_step),
        "timestep_minutes": 15,
        "electricity_facility_joules": round(total_kwh / JOULES_TO_KWH, 4),
        "electricity_facility_kwh": round(total_kwh, 6),
        "zone_temp_min_c": round(min(all_temps), 3) if all_temps else None,
        "zone_temp_max_c": round(max(all_temps), 3) if all_temps else None,
        "zone_temp_per_zone": per_zone,
        "csv": str(OUT_DIR / "eplusout.csv"),
        "source_column": ELEC_COL,
        "severe_errors": severe,
        "fatal_errors": fatal,
        "notes": {
            "run_period": "June 1 single day (96 x 15-min steps)",
            "control": "none — schedule-driven baseline (INV-9 reference)",
        },
        "per_step_kwh": [round(v, 8) for v in per_step],
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / "summary.json"
    path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    logger.info("Wrote %s", path)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the uncontrolled baseline.")
    parser.add_argument(
        "--keep-existing",
        action="store_true",
        help="Exit successfully if a baseline summary already exists.",
    )
    args = parser.parse_args()

    summary_path = OUT_DIR / "summary.json"
    if args.keep_existing and summary_path.is_file():
        existing = json.loads(summary_path.read_text(encoding="utf-8"))
        logger.info(
            "Baseline already present: %.3f kWh — keeping it.",
            existing.get("electricity_facility_kwh", 0.0),
        )
        sys.exit(0)

    _check_prereqs()
    exit_code = _run_energyplus()
    if exit_code != 0:
        logger.error("EnergyPlus exited %d — see %s", exit_code, OUT_DIR / "eplusout.err")
        sys.exit(1)

    per_step, temps = _read_series(OUT_DIR / "eplusout.csv")
    if not per_step:
        logger.error("No electricity timesteps parsed — baseline is unusable.")
        sys.exit(1)

    summary = _write_summary(per_step, temps)

    print(
        f"\n{'=' * 60}\n"
        f"  EcoLoop Baseline (uncontrolled)\n"
        f"  Timesteps : {summary['timesteps']}\n"
        f"  Total     : {summary['electricity_facility_kwh']:.3f} kWh\n"
        f"  Zone temp : {summary['zone_temp_min_c']} – {summary['zone_temp_max_c']} °C\n"
        f"  Severe/Fatal : {summary['severe_errors']}/{summary['fatal_errors']}\n"
        f"{'=' * 60}\n"
    )

    if summary["timesteps"] != EXPECTED_TIMESTEPS:
        logger.warning(
            "Expected %d timesteps, got %d — check the RunPeriod in baseline.idf.",
            EXPECTED_TIMESTEPS,
            summary["timesteps"],
        )
    sys.exit(0)


if __name__ == "__main__":
    main()
