#!/usr/bin/env python
"""
run_phase5_gate.py — Phase 5 exit gate (comparison data + dashboard cold-start).

  T5.1  generate_comparison.py writes CSVs; kpis savings consistent
  T5.2  Dashboard module imports; empty/missing data path handled
  T5.3  Baseline-only comparison status == baseline_only
  T5.4  energy + zone CSVs non-empty with labeled columns
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))

PASS, FAIL = "[PASS]", "[FAIL]"
COMPARISON = ROOT / "data" / "comparison"


def _run(cmd: list[str], timeout: int = 120) -> tuple[int, str]:
    r = subprocess.run(
        cmd,
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=timeout,
        encoding="utf-8",
        errors="replace",
    )
    return r.returncode, (r.stdout + r.stderr).strip()


def t51() -> tuple[bool, str]:
    rc, out = _run([sys.executable, "scripts/generate_comparison.py"], timeout=120)
    if rc != 0:
        return False, out[-800:]
    kpis_path = COMPARISON / "kpis.json"
    energy = COMPARISON / "energy_timeseries.csv"
    zones = COMPARISON / "zone_temps.csv"
    if not (kpis_path.is_file() and energy.is_file() and zones.is_file()):
        return False, "Missing comparison artifacts"
    kpis = json.loads(kpis_path.read_text(encoding="utf-8"))
    # If agent summary exists for same run, savings should be coherent
    run_id = kpis.get("run_id")
    if run_id and kpis.get("status") in ("complete", "partial"):
        summary = ROOT / "data" / "agent_results" / run_id / "summary.json"
        if summary.is_file() and kpis.get("status") == "complete":
            s = json.loads(summary.read_text(encoding="utf-8"))
            if s.get("savings_pct") is not None and kpis.get("savings_pct") is not None:
                delta = abs(float(s["savings_pct"]) - float(kpis["savings_pct"]))
                if delta > 0.1:
                    return False, f"savings mismatch summary vs kpis: {delta}"
    return True, f"status={kpis.get('status')} savings={kpis.get('savings_pct')}%"


def t52() -> tuple[bool, str]:
    # Import dashboard pieces without launching Streamlit server
    try:
        from dashboard.components.metrics import render_kpi_row
        from dashboard.components.timeline import render_timeline
        from dashboard.components.agent_log import render_agent_log

        assert callable(render_kpi_row)
        assert callable(render_timeline)
        assert callable(render_agent_log)
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)

    # Cold-start message path: app detects missing kpis
    app_src = (ROOT / "dashboard" / "app.py").read_text(encoding="utf-8")
    if "No comparison data found" not in app_src:
        return False, "Missing friendly empty-state message in app.py"
    return True, "dashboard imports OK; empty-state message present"


def t53() -> tuple[bool, str]:
    rc, out = _run(
        [sys.executable, "scripts/generate_comparison.py", "--baseline-only"],
        timeout=120,
    )
    if rc != 0:
        return False, out[-500:]
    kpis = json.loads((COMPARISON / "kpis.json").read_text(encoding="utf-8"))
    if kpis.get("status") != "baseline_only":
        return False, f"expected baseline_only, got {kpis.get('status')}"
    # Restore full comparison for the rest of the gate / user
    _run([sys.executable, "scripts/generate_comparison.py"], timeout=120)
    return True, "baseline-only mode OK; full comparison restored"


def t54() -> tuple[bool, str]:
    energy = COMPARISON / "energy_timeseries.csv"
    zones = COMPARISON / "zone_temps.csv"
    if not energy.is_file() or not zones.is_file():
        return False, "CSVs missing — run T5.1 first"
    e_lines = energy.read_text(encoding="utf-8").strip().splitlines()
    z_lines = zones.read_text(encoding="utf-8").strip().splitlines()
    if len(e_lines) < 2 or len(z_lines) < 2:
        return False, "Empty timeseries"
    e_header = e_lines[0]
    z_header = z_lines[0]
    for col in ("step", "baseline_kwh_cum", "agent_kwh_cum"):
        if col not in e_header:
            return False, f"energy CSV missing column {col}"
    for col in ("step", "zone", "baseline_temp_c", "agent_temp_c"):
        if col not in z_header:
            return False, f"zone CSV missing column {col}"
    return True, f"energy_rows={len(e_lines)-1} zone_rows={len(z_lines)-1}"


def main() -> None:
    print("=== Phase 5 Gate ===\n")
    checks = [
        ("T5.1", "Comparison artifacts", t51),
        ("T5.2", "Dashboard cold-start contract", t52),
        ("T5.3", "Baseline-only mode", t53),
        ("T5.4", "Chart data completeness", t54),
    ]
    results = {}
    for code, desc, fn in checks:
        try:
            ok, detail = fn()
        except Exception as exc:  # noqa: BLE001
            ok, detail = False, f"EXCEPTION: {exc}"
        results[code] = ok
        print(f"  {PASS if ok else FAIL} {code} {desc} — {detail}\n")

    if all(results.values()):
        print("EXIT GATE: GREEN - Phase 5 comparison + dashboard ready.")
        print("  Open UI: uv run streamlit run dashboard/app.py")
        sys.exit(0)
    failed = [k for k, v in results.items() if not v]
    print(f"EXIT GATE: RED - failing: {failed}")
    sys.exit(1)


if __name__ == "__main__":
    main()
