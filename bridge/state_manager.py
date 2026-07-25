"""
state_manager.py — singleton EnergyPlus API + state holder.

Job: One EnergyPlusAPI instance and one state object for the whole process.
Reader, writer, and runner all import from here. Prevents the most common
EP Python API crash: two objects fighting over state.

Build: Phase 2a, before reader/writer.
"""

from __future__ import annotations

import os
import sys
from typing import Any

_api: Any = None
_state: Any = None


def get_api() -> Any:
    """Return the process-wide EnergyPlusAPI, importing pyenergyplus lazily."""
    global _api
    if _api is None:
        ep_dir = os.getenv("ENERGYPLUS_DIR", r"C:\EnergyPlusV26-1-0")
        if ep_dir not in sys.path:
            sys.path.insert(0, ep_dir)
        from pyenergyplus.api import EnergyPlusAPI

        _api = EnergyPlusAPI()
    return _api


def get_state() -> Any:
    """Return the process-wide state, creating it on first call."""
    global _state
    if _state is None:
        api = get_api()
        _state = api.state_manager.new_state()
    return _state


def reset_state() -> Any:
    """Delete and recreate state (needed between runs in one process)."""
    global _state
    api = get_api()
    if _state is not None:
        api.state_manager.delete_state(_state)
    _state = api.state_manager.new_state()
    return _state
