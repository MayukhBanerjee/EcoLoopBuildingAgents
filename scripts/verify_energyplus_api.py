"""
Smoke-check EnergyPlus Python API import + version.
Run after EnergyPlus install; before implementing ep_runner.
"""

from __future__ import annotations

import os
import sys


def main() -> None:
    ep_dir = os.getenv("ENERGYPLUS_DIR", r"C:\EnergyPlusV26-1-0")
    if ep_dir not in sys.path:
        sys.path.insert(0, ep_dir)
    from pyenergyplus.api import EnergyPlusAPI  # noqa: F401

    print(f"OK — EnergyPlus Python API importable from {ep_dir}")


if __name__ == "__main__":
    main()
