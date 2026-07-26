"""
Phase 0 gate runner — executes T0.1–T0.4 and prints a pass/fail matrix.

Usage:
  uv run python scripts/run_phase0_gate.py
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable
EP_DIR = os.getenv("ENERGYPLUS_DIR", r"C:\EnergyPlusV26-1-0")
EP_EXE = Path(EP_DIR) / "energyplus.exe"


def run(cmd: list[str], *, env: dict | None = None) -> tuple[int, str]:
    merged = os.environ.copy()
    if env:
        merged.update(env)
    proc = subprocess.run(
        cmd,
        cwd=str(ROOT),
        env=merged,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    # Windows consoles may not render all Unicode; keep gate output ASCII-safe
    out = out.encode("ascii", errors="replace").decode("ascii")
    return proc.returncode, out.strip()


def main() -> int:
    rows: list[tuple[str, bool, str]] = []

    # T0.1
    code, out = run([PY, str(ROOT / "scripts" / "verify_energyplus_api.py")])
    rows.append(("T0.1 verify_energyplus_api.py", code == 0, out.splitlines()[-1] if out else ""))

    # T0.2
    code, out = run(
        [
            PY,
            "-c",
            (
                "import sys; "
                f"sys.path.insert(0, r'{EP_DIR}'); "
                "from pyenergyplus.api import EnergyPlusAPI; "
                "print(EnergyPlusAPI.api_version())"
            ),
        ]
    )
    rows.append(("T0.2 EnergyPlusAPI.api_version()", code == 0, out.splitlines()[-1] if out else out))

    # T0.3
    code, out = run([PY, str(ROOT / "scripts" / "verify_groq.py")])
    rows.append(("T0.3 verify_groq.py (both models + tools)", code == 0, out.splitlines()[-1] if out else ""))

    # T0.4
    if EP_EXE.is_file():
        code, out = run([str(EP_EXE), "--version"])
        ok = code == 0 and "26.1.0" in out
        rows.append(("T0.4 energyplus.exe --version", ok, out.splitlines()[-1] if out else ""))
    else:
        rows.append(("T0.4 energyplus.exe --version", False, f"missing: {EP_EXE}"))

    print("\n=== Phase 0 Gate ===")
    for tid, ok, detail in rows:
        mark = "PASS" if ok else "FAIL"
        print(f"[{mark}] {tid}")
        if detail:
            print(f"       {detail}")

    all_ok = all(ok for _, ok, _ in rows)
    print("\nEXIT GATE:", "GREEN - proceed to Phase 1" if all_ok else "RED - fix failures before Phase 1")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
