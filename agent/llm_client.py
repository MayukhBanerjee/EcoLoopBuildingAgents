"""
llm_client.py — Groq wrapper (open-source models, OpenAI-compatible API).

Job: Tool-calling client for Llama 3.x on Groq, with:
  - hard timeout (15 s) + one retry -> LLMUnavailable -> orchestrator fallback
  - >=2 s spacing between calls (Groq free tier: 30 req/min)
  - self-correction round: invalid tool call -> rejection message -> 1 retry
  - per-call token + latency accounting into the decision log

Two-model strategy: DEV_MODEL_NAME (llama-3.1-8b-instant, 500K tokens/day)
for development runs; MODEL_NAME (llama-3.3-70b-versatile, 100K tokens/day)
for scored runs only.

Build: Phase 3a. See docs/prompt_playbook.md for prompt strategy.
"""

from __future__ import annotations

import os
from typing import Any

CALL_SPACING_S = 2.0
TIMEOUT_S = 15.0
TEMPERATURE = 0.2
MAX_TOKENS = 600


class LLMUnavailable(Exception):
    """Raised after timeout + retry both fail; orchestrator applies fallback."""


class LLMClient:
    """OpenAI SDK pointed at Groq; swap base_url for Ollama backup."""

    def __init__(self, dev_mode: bool = False) -> None:
        self.api_key = os.getenv("GROQ_API_KEY")
        self.base_url = os.getenv("OPENAI_BASE_URL", "https://api.groq.com/openai/v1")
        model_var = "DEV_MODEL_NAME" if dev_mode else "MODEL_NAME"
        self.model = os.getenv(model_var, "llama-3.1-8b-instant")
        self.total_tokens = 0
        self.client: Any = None

    def run_with_tools(self, system: str, messages: list, tools: list) -> Any:
        """One decision round: system+messages+tools -> assistant message.

        Must implement: MCP input_schema -> OpenAI function format adapter,
        call spacing gate, timeout+retry, 429 retry-after handling,
        token accounting, and the salvage parser for tool-calls-in-content.
        """
        raise NotImplementedError("Phase 3a")
