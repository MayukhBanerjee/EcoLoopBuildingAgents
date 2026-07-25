"""
tools.py — tool implementations executed by the orchestrator.

Job: Map MCP tool names → EPReader / EPWriter / comfort helpers.
LLM proposes calls; ToolExecutor runs them against the live sim.

Build: alongside mcp_server.py schemas.
"""

from __future__ import annotations

from typing import Any

from agent.mcp_server import MCP_TOOLS


class ToolExecutor:
    """Dispatches LLM tool calls to bridge + report helpers."""

    def __init__(self, reader: Any, writer: Any) -> None:
        self.reader = reader
        self.writer = writer
        self._latest_reading: Any = None
        self._energy_kwh: float = 0.0

    def get_tool_definitions(self) -> list[dict]:
        return MCP_TOOLS

    def execute(self, name: str, payload: dict) -> Any:
        raise NotImplementedError(f"Implement tool dispatch for '{name}'.")

    def get_energy_report(self, compare_to_baseline: bool = True) -> dict:
        raise NotImplementedError
