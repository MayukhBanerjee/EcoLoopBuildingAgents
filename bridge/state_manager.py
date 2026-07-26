"""
state_manager.py — process-wide EnergyPlusAPI + state singleton.

Prevents the classic crash: two bridge objects holding different EP states.
"""

from __future__ import annotations

import os
import sys
from typing import Any

_api: Any = None
_state: Any = None


def energyplus_dir() -> str:
    return os.getenv("ENERGYPLUS_DIR", r"C:\EnergyPlusV26-1-0")


def get_api() -> Any:
    """Return the process-wide EnergyPlusAPI (lazy import from install dir)."""
    global _api
    if _api is None:
        ep_dir = energyplus_dir()
        if ep_dir not in sys.path:
            sys.path.insert(0, ep_dir)
        from pyenergyplus.api import EnergyPlusAPI

        _api = EnergyPlusAPI()
    return _api


def get_state() -> Any:
    """Return the process-wide state, creating it on first call."""
    global _state
    if _state is None:
        _state = get_api().state_manager.new_state()
    return _state


def reset_state() -> Any:
    """Delete and recreate state. Prefer a fresh Python process between full runs."""
    global _state
    api = get_api()
    if _state is not None:
        api.state_manager.delete_state(_state)
    _state = api.state_manager.new_state()
    return _state
