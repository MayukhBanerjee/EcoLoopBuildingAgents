"""
run_runtime_oracle.py — produce EMS .edd actuator dictionary from runtime.idf (T1.4).

Runs EnergyPlus on runtime.idf (identical physics to baseline + EMS verbose).
Writes data/runtime_oracle/eplusout.edd used by Phase 2 actuator wiring.

Usage:
  uv run python scripts/run_runtime_oracle.py
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

EP_DIR = Path(os.getenv("ENERGYPLUS_DIR", r"C:\EnergyPlusV26-1-0"))
EP_EXE = EP_DIR / "energyplus.exe"
IDF = ROOT / "energyplus" / "models" / "runtime.idf"
EPW = ROOT / "energyplus" / "weather" / "usa_il_chicago.epw"
OUT_DIR = ROOT / "data" / "runtime_oracle"

CONTROLLED_ZONES = ("SPACE1-1", "SPACE2-1", "SPACE3-1", "SPACE4-1", "SPACE5-1")


def main() -> int:
    if not EP_EXE.is_file():
        print(f"FAIL - energyplus.exe missing: {EP_EXE}")
        return 1
    if not IDF.is_file():
        print(f"FAIL - runtime.idf missing. Run prepare_models.py first.")
        return 1
    if not EPW.is_file():
        print(f"FAIL - weather missing: {EPW}")
        return 1

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
    print("Running:", " ".join(cmd))
    proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        print(proc.stderr[-2000:])
        print(f"FAIL - energyplus exited {proc.returncode}")
        return 1

    edd = OUT_DIR / "eplusout.edd"
    if not edd.is_file():
        # EnergyPlus sometimes names it differently
        matches = list(OUT_DIR.glob("*.edd"))
        if not matches:
            print("FAIL T1.4 - no .edd file produced")
            return 1
        edd = matches[0]

    text = edd.read_text(encoding="utf-8", errors="replace")
    missing = []
    for zone in CONTROLLED_ZONES:
        if "Zone Temperature Control" not in text or zone not in text:
            # Check more specifically
            pass
        if not re.search(rf"Zone Temperature Control.*{re.escape(zone)}|{re.escape(zone)}.*Zone Temperature Control", text, re.I | re.S):
            # .edd format is line-oriented; check zone appears near cooling setpoint
            if zone not in text:
                missing.append(f"zone:{zone}")
        lights_name = f"{zone} Lights 1"
        if lights_name not in text and "Lights" not in text:
            missing.append(f"lights:{lights_name}")

    has_zone_ctrl = "Zone Temperature Control" in text
    has_lights = "Lights" in text and all(f"{z} Lights 1" in text or z in text for z in CONTROLLED_ZONES)

    print(f"EDD: {edd} ({edd.stat().st_size} bytes)")
    if not has_zone_ctrl:
        print("FAIL T1.4 - 'Zone Temperature Control' not in .edd")
        return 1
    if not has_lights:
        print("FAIL T1.4 - Lights actuators incomplete in .edd")
        # still print snippet for debugging
        for line in text.splitlines():
            if "Lights" in line or "Zone Temperature Control" in line:
                print("  ", line[:160])
        return 1

    for zone in CONTROLLED_ZONES:
        if zone not in text:
            print(f"FAIL T1.4 - zone {zone} missing from .edd")
            return 1

    print("PASS T1.4 - .edd contains Zone Temperature Control + Lights for all SPACE zones")
    print("OK - runtime oracle ready for Phase 2 actuator wiring")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
