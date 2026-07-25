"""
ep_runner.py — EnergyPlus launcher.

Job: Start EnergyPlus via Python API and fire registered callbacks
every simulation timestep so the agent can read + write.

Build: after baseline IDF copy; before ep_reader / ep_writer.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any


class EPRunner:
    """Launches EnergyPlus with Python API hooks."""

    def __init__(self, idf_path: str, epw_path: str, output_dir: str) -> None:
        # Import here so the package loads even if ENERGYPLUS_DIR is unset
        # until runtime. Add ENERGYPLUS_DIR to sys.path before import.
        self.idf_path = idf_path
        self.epw_path = epw_path
        self.output_dir = output_dir
        self.api: Any = None
        self.state: Any = None
        self._callbacks: list[Callable] = []

    def register_callback(self, fn: Callable) -> None:
        """Register a function called every timestep."""
        self._callbacks.append(fn)

    def run(self) -> None:
        """Start simulation. Blocks until complete."""
        raise NotImplementedError("Implement EnergyPlusAPI runtime + callbacks.")

    def reset(self) -> None:
        """Delete and recreate EnergyPlus state."""
        raise NotImplementedError
