"""
run_bridge_read.py — T2.2 + T2.3 live sensor read test.

Prints a compact sensor line each timestep; fails loud on -1 handles.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bridge import state_manager
from bridge.constants import EXPECTED_TIMESTEPS
from bridge.ep_reader import EPReader, HandleError
from bridge.ep_runner import EPRunner


def main() -> int:
    state_manager.reset_state()
    out = ROOT / "data" / "bridge_read"
    out.mkdir(parents=True, exist_ok=True)
    log_path = out / "sensor_trace.jsonl"

    runner = EPRunner(
        idf_path=ROOT / "energyplus" / "models" / "runtime.idf",
        epw_path=ROOT / "energyplus" / "weather" / "usa_il_chicago.epw",
        output_dir=out,
    )
    reader = EPReader(runner.api, runner.state, dump_dir=ROOT / "data" / "logs")
    readings: list[dict] = []
    energy_series: list[float] = []
    fatal: list[str] = []

    def on_step(state) -> None:
        nonlocal reader
        # state object is the same; reader already bound
        step = runner.callback_invocations
        try:
            reading = reader.read(step)
        except HandleError as exc:
            fatal.append(str(exc))
            raise
        compact = reading.to_compact()
        readings.append(compact)
        energy_series.append(reading.energy_consumption_kwh)
        if step <= 3 or step % 24 == 0 or step == EXPECTED_TIMESTEPS:
            z1 = compact["zones"]["SPACE1-1"]
            print(
                f"t{step:02d} out={compact['outdoor_temp']:.1f}C "
                f"SPACE1-1 T={z1['temp']:.1f} occ={z1['occ']} "
                f"CO2={z1['co2']:.0f} cool={z1['cool_sp']:.1f} "
                f"kWh={compact['energy_kwh_cum']:.3f}"
            )

    runner.register_callback(on_step)
    code = runner.run()

    with log_path.open("w", encoding="utf-8") as f:
        for row in readings:
            f.write(json.dumps(row) + "\n")

    if fatal:
        print("FAIL T2.3 - handle errors")
        print(fatal[0][:500])
        return 1

    if code != 0 or len(readings) != EXPECTED_TIMESTEPS:
        print(f"FAIL T2.2 - exit={code} readings={len(readings)}")
        return 1

    # Energy should be monotonically non-decreasing
    mono = all(energy_series[i] <= energy_series[i + 1] + 1e-9 for i in range(len(energy_series) - 1))
    if not mono:
        print("FAIL T2.2 - energy not monotonic")
        return 1

    # Soft temp sanity on SPACE zones
    temps = [r["zones"][z]["temp"] for r in readings for z in r["zones"]]
    tmin, tmax = min(temps), max(temps)
    print(f"Temp band SPACE zones: {tmin:.1f} .. {tmax:.1f} C")
    print(f"Final cumulative kWh: {energy_series[-1]:.3f}")
    print(f"Wrote {log_path}")
    print("PASS T2.2 + T2.3")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
