"""
llm_client.py — OpenAI / Ollama wrapper.

Job: Thin chat-completions client with tool-calling support.
Swap MODEL_NAME or OPENAI_BASE_URL for Ollama.

Build: after bridge writer works; before orchestrator.
"""

from __future__ import annotations

import os
from typing import Any


class LLMClient:
    """OpenAI-compatible client with tool calling."""

    def __init__(self) -> None:
        self.api_key = os.getenv("OPENAI_API_KEY")
        self.model = os.getenv("MODEL_NAME", "gpt-4o-mini")
        self.base_url = os.getenv("OPENAI_BASE_URL")  # set for Ollama
        self.client: Any = None

    def run_with_tools(self, system: str, messages: list, tools: list) -> Any:
        """Call the model with tools; return the assistant message."""
        raise NotImplementedError("Wire openai.OpenAI chat.completions.create.")
