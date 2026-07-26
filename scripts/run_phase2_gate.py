"""
run_phase2_gate.py — Phase 2 exit gate (T2.1-T2.6).

Usage:
  uv run python scripts/run_phase2_gate.py
  uv run python scripts/run_phase2_gate.py --quick   # unit tests + smoke only
  uv run python scripts/run_phase2_gate.py --full    # all integration sims
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable


def run(label: str, cmd: list[str]) -> tuple[bool, str]:
    print(f"\n>>> {label}")
    print(" ".join(cmd))
    proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = (proc.stdout or "") + (proc.stderr or "")
    # show last lines for visibility
    lines = [ln for ln in out.splitlines() if ln.strip()]
    for ln in lines[-12:]:
        print(ln)
    return proc.returncode == 0, out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--full", action="store_true", default=True)
    args = parser.parse_args()
    if args.quick:
        args.full = False

    results: list[tuple[str, bool]] = []

    # T2.5 unit tests (always)
    ok, _ = run(
        "T2.5 clamp unit tests",
        [PY, "-m", "pytest", "tests/test_ep_writer_clamps.py", "-q"],
    )
    if not ok:
        # fallback without pytest
        ok2, _ = run(
            "T2.5 clamp unit tests (unittest fallback)",
            [PY, "-c", "from tests.test_ep_writer_clamps import *; "
             "test_inv1_cooling_hard_cap(); test_inv1_unoccupied_allows_28(); "
             "test_inv4_ramp_limit(); test_inv3_deadband(); "
             "test_inv5_occupied_lights_floor(); test_inv5_unoccupied_allows_off(); "
             "test_heating_25_cooling_24_deadband(); print('PASS T2.5')"],
        )
        ok = ok2
    results.append(("T2.5 clamps", ok))

    ok, _ = run("T2.1 callback smoke", [PY, str(ROOT / "scripts" / "run_bridge_smoke.py")])
    results.append(("T2.1 smoke", ok))

    if args.full:
        ok, _ = run("T2.2/T2.3 reader", [PY, str(ROOT / "scripts" / "run_bridge_read.py")])
        results.append(("T2.2+T2.3 read", ok))
        ok, _ = run("T2.4/T2.6 writer", [PY, str(ROOT / "scripts" / "run_bridge_write.py")])
        results.append(("T2.4+T2.6 write", ok))

    print("\n=== Phase 2 Gate ===")
    all_ok = True
    for name, ok in results:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}")
        all_ok = all_ok and ok
    print(
        "\nEXIT GATE:",
        "GREEN - bridge proven; proceed to Phase 3"
        if all_ok
        else "RED - fix bridge failures before Phase 3",
    )
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
