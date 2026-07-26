"""
prepare_models.py — Phase 1 model instrumentation (idempotent).

Transforms the stock 5ZoneAutoDXVAV IDF into:
  energyplus/models/baseline.idf  — physics + EcoLoop outputs (no EMS)
  energyplus/models/runtime.idf   — identical + EMS actuator dictionary

Changes applied:
  1. Single RunPeriod: June 1 → June 1 (96 x 15-min timesteps)
  2. ZoneAirContaminantBalance + Outdoor CO2 Schedule @ 400 ppm
  3. People CO2 generation rate (3.82E-8 m3/s-W) on all SPACE people
  4. Timestep Output:Variable / Output:Meter block (INV-9 identical)
  5. runtime only: Output:EnergyManagementSystem, Verbose, Verbose, Verbose

Usage:
  uv run python scripts/prepare_models.py
  uv run python scripts/prepare_models.py --source "C:\\EnergyPlusV26-1-0\\ExampleFiles\\5ZoneAutoDXVAV.idf"
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODELS = ROOT / "energyplus" / "models"
DEFAULT_SOURCE = Path(r"C:\EnergyPlusV26-1-0\ExampleFiles\5ZoneAutoDXVAV.idf")
MARKER = "!- EcoLoop Phase 1 instrumentation"

SINGLE_RUN_PERIOD = """\
  RunPeriod,
    EcoLoop Demo Day,        !- Name
    6,                       !- Begin Month
    1,                       !- Begin Day of Month
    ,                        !- Begin Year
    6,                       !- End Month
    1,                       !- End Day of Month
    ,                        !- End Year
    Tuesday,                 !- Day of Week for Start Day
    Yes,                     !- Use Weather File Holidays and Special Days
    Yes,                     !- Use Weather File Daylight Saving Period
    No,                      !- Apply Weekend Holiday Rule
    Yes,                     !- Use Weather File Rain Indicators
    Yes;                     !- Use Weather File Snow Indicators
"""

CO2_BALANCE = """\
  ZoneAirContaminantBalance,
    Yes,                     !- Carbon Dioxide Concentration
    Outdoor CO2 Schedule;    !- Outdoor Carbon Dioxide Schedule Name
"""

CO2_SCHEDULE = """\
  Schedule:Compact,
    Outdoor CO2 Schedule,    !- Name
    Any Number,              !- Schedule Type Limits Name
    Through: 12/31,          !- Field 1
    For: AllDays,            !- Field 2
    Until: 24:00,400.0;      !- Field 3
"""

ECOLOOP_OUTPUTS = """\
  !- === EcoLoop Phase 1 timestep outputs (do not remove) ===
  Output:Variable,*,Zone Mean Air Temperature,Timestep;
  Output:Variable,*,Zone People Occupant Count,Timestep;
  Output:Variable,*,Site Outdoor Air Drybulb Temperature,Timestep;
  Output:Variable,*,Zone Thermostat Cooling Setpoint Temperature,Timestep;
  Output:Variable,*,Zone Thermostat Heating Setpoint Temperature,Timestep;
  Output:Variable,*,Zone Air CO2 Concentration,Timestep;
  Output:Meter,Electricity:Facility,Timestep;
  Output:VariableDictionary,IDF;
"""

EMS_OUTPUT = """\
  Output:EnergyManagementSystem,
    Verbose,                 !- Actuator Availability Dictionary Reporting
    Verbose,                 !- Internal Variable Availability Dictionary Reporting
    Verbose;                 !- EMS Runtime Language Debug Output Level
"""

RUNPERIOD_BLOCK = re.compile(
    # Semicolon may be mid-line before an !- comment; consume through end of that line.
    r"(?ms)^\s*RunPeriod,.+?;[^\n]*\n",
)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()[:12]


def _strip_previous_ecoloop(text: str) -> str:
    """Allow re-running prepare on already-instrumented IDFs."""
    text = re.sub(
        r"\n\s*!- === EcoLoop Phase 1 timestep outputs.*?Output:VariableDictionary,IDF;\s*",
        "\n",
        text,
        flags=re.DOTALL,
    )
    text = re.sub(
        r"\n\s*Output:EnergyManagementSystem,.*?Verbose;\s*!- EMS Runtime.*?\n",
        "\n",
        text,
        flags=re.DOTALL,
    )
    text = re.sub(
        r"\n\s*ZoneAirContaminantBalance,.*?Outdoor CO2 Schedule;\s*!- Outdoor.*?\n",
        "\n",
        text,
        flags=re.DOTALL,
    )
    text = re.sub(
        r"\n\s*Schedule:Compact,\s*\n\s*Outdoor CO2 Schedule,.*?Until: 24:00,400\.0;\s*!- Field 3\s*\n",
        "\n",
        text,
        flags=re.DOTALL,
    )
    # Undo people CO2 extension if present
    text = re.sub(
        r"(ActSchd),\s*!- Activity Level Schedule Name\s*\n\s*3\.82E-8;\s*!- Carbon Dioxide Generation Rate.*?\n",
        r"\1;                 !- Activity Level Schedule Name\n",
        text,
    )
    text = text.replace(f"\n{MARKER}\n", "\n")
    return text


def transform(source_text: str, *, with_ems: bool) -> str:
    text = _strip_previous_ecoloop(source_text)

    # 1) Collapse all RunPeriod objects into one June 1 demo day
    periods = list(RUNPERIOD_BLOCK.finditer(text))
    if not periods:
        raise RuntimeError("No RunPeriod objects found in source IDF")
    first, last = periods[0], periods[-1]
    text = text[: first.start()] + "\n" + SINGLE_RUN_PERIOD + "\n" + text[last.end() :]

    # 2) Insert outdoor CO2 schedule AFTER Any Number limits (before balance refs it)
    if "Until: 24:00,400.0;" not in text:
        anchor = "ScheduleTypeLimits,\n    Any Number;              !- Name"
        if anchor not in text:
            m = re.search(r"ScheduleTypeLimits,\s*\n\s*Any Number;", text)
            if not m:
                raise RuntimeError("Could not find ScheduleTypeLimits Any Number anchor")
            insert_at = m.end()
            text = text[:insert_at] + "\n\n" + CO2_SCHEDULE + text[insert_at:]
        else:
            text = text.replace(anchor, anchor + "\n\n" + CO2_SCHEDULE, 1)

    # 3) Insert contaminant balance after Timestep (schedule must already exist)
    if "ZoneAirContaminantBalance" not in text:
        if "Timestep,4;" not in text:
            raise RuntimeError("Expected 'Timestep,4;' in source IDF")
        text = text.replace("Timestep,4;", "Timestep,4;\n\n" + CO2_BALANCE, 1)

    # 4) People CO2 generation rate (ASHRAE default)
    text = text.replace(
        "    ActSchd;                 !- Activity Level Schedule Name",
        "    ActSchd,                 !- Activity Level Schedule Name\n"
        "    3.82E-8;                 !- Carbon Dioxide Generation Rate {m3/s-W}",
    )

    # 5) Append EcoLoop timestep outputs (identical on both models)
    if "EcoLoop Phase 1 timestep outputs" not in text:
        text = text.rstrip() + "\n\n" + ECOLOOP_OUTPUTS + "\n"

    # 6) EMS oracle on runtime only
    if with_ems and "Output:EnergyManagementSystem" not in text:
        text = text.rstrip() + "\n" + EMS_OUTPUT + "\n"

    if MARKER not in text:
        text = text.replace("  Version,26.1;", f"  Version,26.1;\n\n{MARKER}", 1)

    return text


def write_models(source: Path) -> tuple[Path, Path]:
    MODELS.mkdir(parents=True, exist_ok=True)
    raw = source.read_text(encoding="utf-8", errors="replace")

    baseline_path = MODELS / "baseline.idf"
    runtime_path = MODELS / "runtime.idf"

    baseline_text = transform(raw, with_ems=False)
    runtime_text = transform(raw, with_ems=True)

    baseline_path.write_text(baseline_text, encoding="utf-8", newline="\n")
    runtime_path.write_text(runtime_text, encoding="utf-8", newline="\n")
    return baseline_path, runtime_path


def _quick_checks(baseline: Path, runtime: Path) -> None:
    b = baseline.read_text(encoding="utf-8")
    r = runtime.read_text(encoding="utf-8")

    assert "EcoLoop Demo Day" in b and "EcoLoop Demo Day" in r
    assert "Run Period 1" not in b and "Run Period 2" not in b
    assert b.count("RunPeriod,") == 1
    assert "SimulationControl" in b
    assert "Site:Location" in b
    assert "SizingPeriod:DesignDay" in b
    assert "Until: 24:00,400.0;" in b
    assert "Schedule:Compact," in b and "Outdoor CO2 Schedule," in b
    assert "ZoneAirContaminantBalance" in b
    assert "Zone Mean Air Temperature,Timestep" in b
    assert "Electricity:Facility,Timestep" in b
    assert "Zone Air CO2 Concentration,Timestep" in b
    assert b.count("3.82E-8;") >= 5
    assert "Output:EnergyManagementSystem" not in b
    assert "Output:EnergyManagementSystem" in r
    print("OK - static IDF checks passed")


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare EcoLoop baseline/runtime IDFs")
    parser.add_argument(
        "--source",
        type=Path,
        default=DEFAULT_SOURCE if DEFAULT_SOURCE.exists() else MODELS / "baseline.idf",
        help="Source IDF (defaults to EnergyPlus example file)",
    )
    args = parser.parse_args()

    if not args.source.exists():
        print(f"FAIL - source IDF not found: {args.source}")
        return 1

    # Prefer a clean stock copy when source is the example file
    source = args.source
    print(f"Source: {source} (sha { _sha256(source) })")

    # If preparing from an already-instrumented baseline, still OK (strip+reapply)
    baseline, runtime = write_models(source)
    _quick_checks(baseline, runtime)

    print(f"Wrote {baseline} ({baseline.stat().st_size} bytes)")
    print(f"Wrote {runtime} ({runtime.stat().st_size} bytes)")
    print("OK - prepare_models complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
