"""
ep_runner.py — EnergyPlus launcher with timestep callbacks.

Registers user callbacks on begin_zone_timestep_after_init_heat_balance,
requests all sensor variables before run, and wraps every callback so
exceptions never escape into EnergyPlus (INV-7).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from bridge import state_manager
from bridge.constants import SENSOR_VARIABLES

logger = logging.getLogger("EcoLoop.bridge.runner")

Callback = Callable[[Any], None]


class EPRunner:
    """Launches EnergyPlus via the Python API and fires registered callbacks."""

    def __init__(
        self,
        idf_path: str | Path,
        epw_path: str | Path,
        output_dir: str | Path,
    ) -> None:
        self.idf_path = Path(idf_path).resolve()
        self.epw_path = Path(epw_path).resolve()
        self.output_dir = Path(output_dir).resolve()
        self.api = state_manager.get_api()
        self.state = state_manager.get_state()
        self._user_callbacks: list[Callback] = []
        self.callback_invocations = 0
        self.callback_errors = 0

    def register_callback(self, fn: Callback) -> None:
        """Register a function called every non-warmup zone timestep."""
        self._user_callbacks.append(fn)

    def _request_variables(self) -> None:
        ex = self.api.exchange
        for var_name, var_key in SENSOR_VARIABLES:
            ex.request_variable(self.state, var_name, var_key)

    def _guarded_callback(self, state: Any) -> None:
        """Warmup/ready guards + INV-7 exception firewall."""
        try:
            ex = self.api.exchange
            if not ex.api_data_fully_ready(state):
                return
            if ex.warmup_flag(state):
                return

            self.callback_invocations += 1
            for fn in self._user_callbacks:
                fn(state)
        except Exception:  # noqa: BLE001 — never let EP abort from agent code
            self.callback_errors += 1
            logger.exception(
                "Callback error at invocation %s (swallowed per INV-7)",
                self.callback_invocations,
            )

    def run(self) -> int:
        """
        Start simulation. Blocks until complete.

        Returns EnergyPlus exit code (0 = success).
        """
        if not self.idf_path.is_file():
            raise FileNotFoundError(f"IDF not found: {self.idf_path}")
        if not self.epw_path.is_file():
            raise FileNotFoundError(f"EPW not found: {self.epw_path}")

        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._request_variables()

        self.api.runtime.callback_begin_zone_timestep_after_init_heat_balance(
            self.state, self._guarded_callback
        )

        args = [
            "-w",
            str(self.epw_path),
            "-d",
            str(self.output_dir),
            "-r",
            str(self.idf_path),
        ]
        logger.info("run_energyplus %s", " ".join(args))
        return int(self.api.runtime.run_energyplus(self.state, args))

    def reset(self) -> None:
        """Recreate EP state and clear counters (prefer new process for full reruns)."""
        self.state = state_manager.reset_state()
        self.api = state_manager.get_api()
        self.callback_invocations = 0
        self.callback_errors = 0
        self._user_callbacks.clear()
