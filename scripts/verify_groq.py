"""
Verify Groq connectivity for both Phase 0 models (T0.3).

Tests:
  1. Minimal completion on llama-3.1-8b-instant (dev model)
  2. Minimal completion on llama-3.3-70b-versatile (scored model)
  3. Confirms tool-calling is accepted by the API for the scored model

Usage:
  uv run python scripts/verify_groq.py

Requires GROQ_API_KEY in environment or .env (never commit .env).
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

DEV_MODEL = os.getenv("DEV_MODEL_NAME", "llama-3.1-8b-instant")
SCORE_MODEL = os.getenv("MODEL_NAME", "llama-3.3-70b-versatile")
BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.groq.com/openai/v1")

SAMPLE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_sensors",
            "description": "Read current building sensor snapshot.",
            "parameters": {
                "type": "object",
                "properties": {
                    "zones": {
                        "type": "array",
                        "items": {"type": "string"},
                    }
                },
            },
        },
    }
]


def _client():
    from openai import OpenAI

    api_key = os.getenv("GROQ_API_KEY")
    if not api_key or api_key.startswith("gsk_your"):
        print(
            "FAIL - GROQ_API_KEY missing. Create a free key at "
            "https://console.groq.com/keys and put it in .env"
        )
        raise SystemExit(1)
    return OpenAI(api_key=api_key, base_url=BASE_URL)


def _timed_completion(client, model: str, *, with_tools: bool = False) -> tuple[str, float, object]:
    kwargs: dict = {
        "model": model,
        "messages": [
            {"role": "system", "content": "Reply with exactly one word: OK"},
            {"role": "user", "content": "ping"},
        ],
        "max_tokens": 8,
        "temperature": 0,
    }
    if with_tools:
        kwargs["tools"] = SAMPLE_TOOLS
        kwargs["tool_choice"] = "none"

    t0 = time.perf_counter()
    resp = client.chat.completions.create(**kwargs)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    text = (resp.choices[0].message.content or "").strip()
    return text, elapsed_ms, resp


def main() -> int:
    print(f"BASE_URL={BASE_URL}")
    print(f"DEV_MODEL={DEV_MODEL}")
    print(f"SCORE_MODEL={SCORE_MODEL}")
    client = _client()

    results: list[tuple[str, bool, str]] = []

    for label, model, tools in (
        ("T0.3a", DEV_MODEL, False),
        ("T0.3b", SCORE_MODEL, False),
        ("T0.3c-tools", SCORE_MODEL, True),
    ):
        try:
            text, ms, resp = _timed_completion(client, model, with_tools=tools)
            usage = getattr(resp, "usage", None)
            tokens = getattr(usage, "total_tokens", "?") if usage else "?"
            ok = bool(text)
            status = "PASS" if ok else "FAIL"
            print(
                f"{status} {label} model={model} latency={ms:.0f}ms "
                f"tokens={tokens} reply={text!r} tools={'on' if tools else 'off'}"
            )
            results.append((label, ok, f"{ms:.0f}ms"))
        except Exception as exc:  # noqa: BLE001
            print(f"FAIL {label} model={model}: {exc}")
            results.append((label, False, str(exc)))

    all_ok = all(ok for _, ok, _ in results)
    print("OK - Groq connectivity verified" if all_ok else "FAIL - Groq verification incomplete")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
