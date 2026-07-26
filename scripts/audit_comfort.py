#!/usr/bin/env python
"""
audit_comfort.py — Phase 4 T4.6 comfort compliance audit.

Reads agent_decisions.jsonl (sensor snapshots) and reports the % of
occupied zone-steps with |PMV| <= 0.5.

Usage
-----
    uv run python scripts/audit_comfort.py
    uv run python scripts/audit_comfort.py --log data/agent_results/<run>/agent_decisions.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))

from agent.comfort import comfort_ok, pmv  # noqa: E402


def _latest_log() -> Path | None:
    root = ROOT / "data" / "agent_results"
    if not root.is_dir():
        return None
    candidates: list[Path] = []
    for p in root.iterdir():
        if not p.is_dir():
            continue
        for name in ("agent_decisions.jsonl", "decisions.jsonl"):
            f = p / name
            if f.is_file():
                candidates.append(f)
                break
    if not candidates:
        return None
    return max(candidates, key=lambda x: x.stat().st_mtime)


def audit(log_path: Path) -> dict:
    occupied = 0
    comfortable = 0
    samples: list[dict] = []

    for line in log_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        entry = json.loads(line)
        snap = entry.get("sensor_snapshot") or {}
        zones = snap.get("zones") or {}
        for zone, zd in zones.items():
            occ = int(zd.get("occ", 0) or 0)
            if occ <= 0:
                continue
            temp = float(zd.get("temp", 22.0))
            val = pmv(temp)
            occupied += 1
            ok = comfort_ok(val)
            if ok:
                comfortable += 1
            samples.append(
                {
                    "timestep": entry.get("timestep"),
                    "zone": zone,
                    "temp": temp,
                    "pmv": val,
                    "ok": ok,
                }
            )

    pct = (comfortable / occupied * 100.0) if occupied else None
    return {
        "log": str(log_path),
        "occupied_zone_steps": occupied,
        "comfortable_zone_steps": comfortable,
        # None (not 100.0) when nothing was occupied — a compliance rate over an
        # empty sample is undefined, and reporting 100% there overstates the result.
        "comfort_compliance_pct": round(pct, 1) if pct is not None else None,
        "target_pct": 90.0,
        "pass": (pct >= 90.0) if pct is not None else False,
        "verdict": (
            "no occupied zone-steps — comfort not exercised, nothing to certify"
            if occupied == 0
            else ("meets the 90% target" if pct >= 90.0 else "below the 90% target")
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="EcoLoop comfort audit (T4.6)")
    parser.add_argument("--log", type=Path, default=None)
    args = parser.parse_args()

    log_path = args.log or _latest_log()
    if log_path is None or not Path(log_path).is_file():
        print("FAIL: no agent_decisions.jsonl found. Run main.py first.")
        sys.exit(1)

    result = audit(Path(log_path))
    print(json.dumps(result, indent=2))
    out = Path(log_path).parent / "comfort_audit.json"
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"Wrote {out}")

    occupied = result["occupied_zone_steps"]
    if occupied == 0:
        print(
            "[NOT MEASURED] No occupied zone-steps in this log — "
            "comfort compliance is undefined, not 100%. "
            "Re-run over occupied hours before quoting a comfort figure."
        )
    else:
        tag = "PASS" if result["pass"] else "MEASURED (below 90% target)"
        print(
            f"[{tag}] comfort={result['comfort_compliance_pct']}% "
            f"({result['comfortable_zone_steps']}/{occupied} occupied zone-steps)"
        )
    # T4.6 is "measured" — do not hard-fail the process on <90%
    sys.exit(0)


if __name__ == "__main__":
    main()
