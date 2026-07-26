"""
Smoke-check EnergyPlus Python API import + version (Phase 0 / T0.1 + T0.2).

Usage:
  uv run python scripts/verify_energyplus_api.py

Exit 0 on success. Failures print a clear diagnostic (bitness, path, DLL).
"""

from __future__ import annotations

import os
import struct
import sys
from pathlib import Path


def main() -> int:
    ep_dir = os.getenv("ENERGYPLUS_DIR", r"C:\EnergyPlusV26-1-0")
    ep_path = Path(ep_dir)
    bits = struct.calcsize("P") * 8

    print(f"Python {sys.version.split()[0]} ({bits}-bit)")
    print(f"ENERGYPLUS_DIR={ep_dir}")

    if bits != 64:
        print(
            "FAIL - Python is not 64-bit. EnergyPlus DLLs require 64-bit Python "
            "(WinError 193 if mismatched)."
        )
        return 1

    if not ep_path.is_dir():
        print(f"FAIL - EnergyPlus directory not found: {ep_dir}")
        return 1

    api_marker = ep_path / "pyenergyplus" / "api.py"
    if not api_marker.is_file():
        print(f"FAIL - pyenergyplus.api not found at {api_marker}")
        return 1

    if str(ep_path) not in sys.path:
        sys.path.insert(0, str(ep_path))

    try:
        from pyenergyplus.api import EnergyPlusAPI
    except OSError as exc:
        print(f"FAIL - DLL load error importing pyenergyplus: {exc}")
        print("Hint: ensure 64-bit Python matches EnergyPlus x86_64 install.")
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL - import error: {exc}")
        return 1

    try:
        version = EnergyPlusAPI.api_version()
    except Exception as exc:  # noqa: BLE001
        # Some builds expose version via the runtime binary only
        print(f"WARN - api_version() unavailable ({exc}); import succeeded.")
        version = "unknown"

    print(f"OK - EnergyPlus Python API importable from {ep_dir}")
    print(f"OK - EnergyPlusAPI.api_version() = {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
