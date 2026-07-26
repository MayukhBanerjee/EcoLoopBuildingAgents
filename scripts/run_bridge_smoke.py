"""
run_bridge_smoke.py — T2.1 callback smoke test.

Runs runtime.idf with a counter-only callback.
Pass: exactly 96 non-warmup invocations, EP exit 0.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bridge.constants import EXPECTED_TIMESTEPS
from bridge.ep_runner import EPRunner
from bridge import state_manager


def main() -> int:
    state_manager.reset_state()
    out = ROOT / "data" / "bridge_smoke"
    out.mkdir(parents=True, exist_ok=True)

    runner = EPRunner(
        idf_path=ROOT / "energyplus" / "models" / "runtime.idf",
        epw_path=ROOT / "energyplus" / "weather" / "usa_il_chicago.epw",
        output_dir=out,
    )

    def _count(_state) -> None:
        pass

    runner.register_callback(_count)
    code = runner.run()
    n = runner.callback_invocations
    print(f"EnergyPlus exit={code}")
    print(f"Non-warmup callbacks={n} (expected {EXPECTED_TIMESTEPS})")
    print(f"Callback errors={runner.callback_errors}")

    ok = code == 0 and n == EXPECTED_TIMESTEPS and runner.callback_errors == 0
    print("PASS T2.1" if ok else "FAIL T2.1")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
