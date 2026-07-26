"""
llm_client.py — Groq wrapper (open-source models, OpenAI-compatible API).

Features
--------
- Two-model strategy:
    DEV  → DEV_MODEL_NAME  (llama-3.1-8b-instant,  500 K tokens/day free)
    PROD → MODEL_NAME      (llama-3.3-70b-versatile, 100 K tokens/day free)
- Hard 15 s timeout + one retry → LLMUnavailable → orchestrator applies fallback.
- ≥ 2 s spacing between calls (Groq free tier: 30 req / min).
- Self-correction round: pydantic validates tool args; on failure injects a
  rejection tool-message and fires one corrective call.
- Salvage parser: extracts tool-calls from freeform text when the model skips
  the function-calling format (common with 8 B models on complex prompts).
- Per-call token + latency accounting logged at DEBUG level.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any

logger = logging.getLogger("EcoLoop.agent.llm")

CALL_SPACING_S: float = 2.0
TIMEOUT_S: float = 15.0
TEMPERATURE: float = 0.2
MAX_TOKENS: int = 600
MAX_SELF_CORRECTION_ROUNDS: int = 1


class LLMUnavailable(Exception):
    """Raised after timeout + retry both fail; orchestrator applies fallback."""


class LLMClient:
    """OpenAI SDK pointed at Groq; swap OPENAI_BASE_URL for Ollama backup."""

    def __init__(self, dev_mode: bool = False) -> None:
        from openai import OpenAI

        api_key = os.getenv("GROQ_API_KEY")
        base_url = os.getenv("OPENAI_BASE_URL", "https://api.groq.com/openai/v1")
        model_var = "DEV_MODEL_NAME" if dev_mode else "MODEL_NAME"
        default_model = "llama-3.1-8b-instant" if dev_mode else "llama-3.3-70b-versatile"
        self.model = os.getenv(model_var, default_model)
        self.dev_mode = dev_mode
        self.total_tokens: int = 0
        self.total_calls: int = 0
        self._last_call_ts: float = 0.0
        self._client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=TIMEOUT_S,
        )
        logger.info(
            "LLMClient ready: model=%s base=%s dev=%s",
            self.model,
            base_url,
            dev_mode,
        )

    # ------------------------------------------------------------------
    # Schema converters
    # ------------------------------------------------------------------

    @staticmethod
    def mcp_to_openai_tool(tool: dict) -> dict:
        """Convert a single MCP tool definition to OpenAI function-calling format.

        Strips Pydantic-generated noise ($defs, title, description on properties)
        that confuses small-context models.
        """
        schema = tool.get("input_schema", {})
        props: dict = schema.get("properties", {})
        # Keep only type + description on each property — no titles, no allOf noise
        clean_props = {
            k: {kk: vv for kk, vv in v.items() if kk in ("type", "description", "enum")}
            for k, v in props.items()
        }
        parameters = {
            "type": "object",
            "properties": clean_props,
        }
        required = schema.get("required", [])
        if required:
            parameters["required"] = required

        return {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool["description"],
                "parameters": parameters,
            },
        }

    @classmethod
    def mcp_tools_to_openai(cls, tools: list[dict]) -> list[dict]:
        return [cls.mcp_to_openai_tool(t) for t in tools]

    # ------------------------------------------------------------------
    # Rate limiting
    # ------------------------------------------------------------------

    def _enforce_spacing(self) -> None:
        elapsed = time.monotonic() - self._last_call_ts
        if elapsed < CALL_SPACING_S:
            wait = CALL_SPACING_S - elapsed
            logger.debug("Rate-limit spacing: sleeping %.2fs", wait)
            time.sleep(wait)

    # ------------------------------------------------------------------
    # Core API call (single attempt, no retry logic)
    # ------------------------------------------------------------------

    def _call_raw(self, messages: list[dict], openai_tools: list[dict]) -> Any:
        """Fire one completion request.  Returns the raw response object."""
        import openai

        self._enforce_spacing()
        t0 = time.monotonic()
        try:
            resp = self._client.chat.completions.create(
                model=self.model,
                messages=messages,  # type: ignore[arg-type]
                tools=openai_tools,  # type: ignore[arg-type]
                tool_choice="auto",
                temperature=TEMPERATURE,
                max_tokens=MAX_TOKENS,
            )
        except openai.APITimeoutError as exc:
            logger.warning("LLM timeout (%.0fs): %s", TIMEOUT_S, exc)
            raise
        except openai.RateLimitError as exc:
            # Extract Retry-After header when available
            retry_after = getattr(exc, "retry_after", None)
            wait = float(retry_after) if retry_after else CALL_SPACING_S * 5
            wait = min(wait, 30.0)
            logger.warning("Rate-limited. Sleeping %.1fs before propagating.", wait)
            time.sleep(wait)
            raise
        except openai.APIError as exc:
            logger.warning("LLM API error: %s", exc)
            raise
        finally:
            self._last_call_ts = time.monotonic()

        latency_ms = int((time.monotonic() - t0) * 1000)
        usage = resp.usage
        tokens = usage.total_tokens if usage else 0
        self.total_tokens += tokens
        self.total_calls += 1
        logger.debug(
            "LLM call #%d: %d ms, tokens=%d, finish=%s",
            self.total_calls,
            latency_ms,
            tokens,
            resp.choices[0].finish_reason if resp.choices else "?",
        )
        return resp

    def _attempt(self, messages: list[dict], openai_tools: list[dict]) -> Any | None:
        """Single attempt; returns None on any recoverable failure."""
        import openai

        try:
            return self._call_raw(messages, openai_tools)
        except (openai.APITimeoutError, openai.RateLimitError, openai.APIError):
            return None

    # ------------------------------------------------------------------
    # Salvage parser
    # ------------------------------------------------------------------

    @staticmethod
    def _salvage_tool_calls(content: str, tool_names: set[str]) -> list[dict] | None:
        """Extract tool calls from freeform text as a last resort.

        Small models sometimes emit JSON inside the text content instead of using
        the function-calling channel.  We accept these two patterns:
          {"tool": "name", "arguments": {...}}
          {"name": "name", "input": {...}}
        """
        patterns = [
            r'"tool"\s*:\s*"([^"]+)"[^{}]*"(?:arguments?|input)"\s*:\s*(\{[^}]+\})',
            r'"name"\s*:\s*"([^"]+)"[^{}]*"(?:arguments?|input)"\s*:\s*(\{[^}]+\})',
            r'"function"\s*:\s*"([^"]+)"[^{}]*"(?:arguments?|input)"\s*:\s*(\{[^}]+\})',
        ]
        for pattern in patterns:
            for m in re.finditer(pattern, content, re.DOTALL):
                name, args_str = m.group(1), m.group(2)
                if name not in tool_names:
                    continue
                try:
                    args = json.loads(args_str)
                    logger.info("Salvaged tool call from text: %s(%s)", name, args)
                    return [{"function": {"name": name, "arguments": json.dumps(args)}}]
                except json.JSONDecodeError:
                    pass
        return None

    # ------------------------------------------------------------------
    # Pydantic validation for self-correction
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_tool_call(name: str, args: dict) -> str | None:
        """Return a rejection reason string or None if args are valid."""
        from agent.mcp_server import (
            GetEnergyReportInput,
            PredictComfortInput,
            ReadSensorsInput,
            SetHVACInput,
            SetLightingInput,
        )

        schema_map: dict[str, Any] = {
            "read_sensors": ReadSensorsInput,
            "set_hvac_setpoint": SetHVACInput,
            "set_lighting_level": SetLightingInput,
            "get_energy_report": GetEnergyReportInput,
            "predict_comfort": PredictComfortInput,
        }
        model_cls = schema_map.get(name)
        if model_cls is None:
            return f"Unknown tool '{name}'"
        try:
            model_cls(**args)
            return None
        except Exception as exc:  # noqa: BLE001
            return str(exc)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_with_tools(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict],
    ) -> Any:
        """Execute one LLM decision round.

        Args:
            system:   System prompt string.
            messages: Conversation history (user / assistant / tool messages).
            tools:    MCP tool definitions (will be converted to OpenAI format).

        Returns:
            Raw OpenAI response.  Caller reads .choices[0].message for
            tool_calls or text content.

        Raises:
            LLMUnavailable: Both initial + retry attempts failed.
        """
        openai_tools = self.mcp_tools_to_openai(tools)
        full_messages: list[dict] = [{"role": "system", "content": system}, *messages]

        # --- initial call (+ one retry on failure) ---
        resp = self._attempt(full_messages, openai_tools)
        if resp is None:
            logger.info("Initial LLM call failed; retrying once.")
            resp = self._attempt(full_messages, openai_tools)
        if resp is None:
            raise LLMUnavailable("Both LLM attempts failed (timeout / rate-limit).")

        msg = resp.choices[0].message

        # --- self-correction round ---
        if msg.tool_calls:
            tc = msg.tool_calls[0]
            try:
                args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                args = {}
            rejection = self._validate_tool_call(tc.function.name, args)
            if rejection:
                logger.info(
                    "Self-correction triggered for %s: %s",
                    tc.function.name,
                    rejection,
                )
                correction_msgs: list[dict] = [
                    *full_messages,
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {
                                    "name": tc.function.name,
                                    "arguments": tc.function.arguments,
                                },
                            }
                        ],
                    },
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": (
                            f"REJECTED: {rejection}\n"
                            "Fix the arguments and call the tool again with valid values."
                        ),
                    },
                ]
                corrected = self._attempt(correction_msgs, openai_tools)
                if corrected is not None:
                    logger.info("Self-correction succeeded.")
                    return corrected
                logger.warning(
                    "Self-correction call also failed; returning original response."
                )

        # --- salvage tool calls from text (small-model fallback) ---
        if not msg.tool_calls and msg.content:
            tool_names = {t["name"] for t in tools}
            salvaged = self._salvage_tool_calls(msg.content, tool_names)
            if salvaged:
                # Attach as synthetic tool_calls so orchestrator's normal path handles them
                object.__setattr__(msg, "tool_calls", salvaged)  # type: ignore[call-overload]

        return resp
