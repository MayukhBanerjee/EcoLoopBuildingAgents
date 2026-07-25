"""
orchestrator.py — closed-loop heartbeat.

Job: Called every EnergyPlus timestep:
  read sensors → prompt LLM → execute tools → log decisions.

Build: last agent piece; wire into main.py callback.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("EcoLoop")


class EcoLoopOrchestrator:
    """Main closed-loop control orchestrator."""

    def __init__(self, reader: Any, writer: Any, llm: Any) -> None:
        self.reader = reader
        self.writer = writer
        self.llm = llm
        self.timestep = 0
        self.decision_log: list[dict] = []

    def step(self, state: Any) -> None:
        """Called by EnergyPlus at each timestep."""
        raise NotImplementedError("Implement read → LLM → tools → log loop.")
