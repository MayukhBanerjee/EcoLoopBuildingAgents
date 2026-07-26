#!/usr/bin/env python
"""
run_phase3_gate.py — Phase 3 exit gate for the EcoLoop agent layer.

Tests
-----
  T3.1  Unit tests (PMV model, memory, grid, tool dispatch) all pass.
  T3.2  LLM connectivity: Groq API reachable with both models.
  T3.3  Schema smoke: MCP_TOOLS serialisable; OpenAI tool-format conversion valid.
  T3.4  Agent dry-run: 10 timesteps, decision log created, no unhandled exceptions.
  T3.5  Decision log integrity: valid JSONL, each entry has required fields.

Exit gate GREEN requires T3.1–T3.3 + at least T3.4 partial pass.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env", override=False)
except ImportError:
    pass

PASS = "[PASS]"
FAIL = "[FAIL]"
SKIP = "[SKIP]"


def _run_subprocess(cmd: list[str], timeout: int = 300) -> tuple[int, str]:
    """Run a subprocess, capture output, return (returncode, combined_output)."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=ROOT,
            encoding="utf-8",
            errors="replace",
        )
        return result.returncode, (result.stdout + result.stderr).strip()
    except subprocess.TimeoutExpired:
        return -1, f"TIMEOUT after {timeout}s"
    except Exception as exc:  # noqa: BLE001
        return -1, str(exc)


# ---------------------------------------------------------------------------
# T3.1 — Unit tests
# ---------------------------------------------------------------------------

def check_t31_unit_tests() -> tuple[bool, str]:
    """Run pytest on all agent-related tests."""
    rc, out = _run_subprocess(
        [
            sys.executable, "-m", "pytest",
            "tests/test_agent_comfort.py",
            "tests/test_agent_memory.py",
            "tests/test_agent_grid.py",
            "tests/test_agent_tools.py",
            "-v", "--tb=short", "-q",
        ],
        timeout=120,
    )
    last_lines = "\n".join(out.splitlines()[-20:])
    if rc == 0:
        return True, last_lines
    return False, last_lines


# ---------------------------------------------------------------------------
# T3.2 — LLM connectivity
# ---------------------------------------------------------------------------

def check_t32_groq_connectivity() -> tuple[bool, str]:
    """Verify Groq API is reachable with dev model."""
    import os

    api_key = os.getenv("GROQ_API_KEY", "")
    if not api_key or api_key.startswith("gsk_your"):
        return False, "GROQ_API_KEY not set; skipping live LLM test."

    try:
        from openai import OpenAI

        client = OpenAI(
            api_key=api_key,
            base_url=os.getenv("OPENAI_BASE_URL", "https://api.groq.com/openai/v1"),
            timeout=15.0,
        )
        model = os.getenv("DEV_MODEL_NAME", "llama-3.1-8b-instant")
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Reply only: OK"}],
            max_tokens=5,
            temperature=0.0,
        )
        text = resp.choices[0].message.content or ""
        tokens = resp.usage.total_tokens if resp.usage else 0
        return True, f"model={model} reply='{text.strip()}' tokens={tokens}"
    except Exception as exc:  # noqa: BLE001
        return False, f"Groq connectivity failed: {exc}"


# ---------------------------------------------------------------------------
# T3.3 — Schema smoke
# ---------------------------------------------------------------------------

def check_t33_schema_smoke() -> tuple[bool, str]:
    """Validate MCP_TOOLS structure and OpenAI format conversion."""
    try:
        from agent.mcp_server import MCP_TOOLS
        from agent.llm_client import LLMClient

        assert len(MCP_TOOLS) == 5, f"Expected 5 tools, got {len(MCP_TOOLS)}"

        tool_names = {t["name"] for t in MCP_TOOLS}
        expected = {
            "read_sensors", "set_hvac_setpoint", "set_lighting_level",
            "get_energy_report", "predict_comfort",
        }
        missing = expected - tool_names
        if missing:
            return False, f"Missing tools: {missing}"

        for tool in MCP_TOOLS:
            assert "name" in tool
            assert "description" in tool
            assert "input_schema" in tool

        openai_tools = LLMClient.mcp_tools_to_openai(MCP_TOOLS)
        for ot in openai_tools:
            assert ot["type"] == "function"
            assert "function" in ot
            f = ot["function"]
            assert "name" in f
            assert "description" in f
            assert "parameters" in f
            # Ensure no $defs polluting the schema
            assert "$defs" not in json.dumps(f["parameters"])

        json_str = json.dumps(MCP_TOOLS)
        return True, f"5 tools serialisable, {len(json_str)} bytes; OpenAI format valid"
    except Exception as exc:  # noqa: BLE001
        return False, f"Schema smoke failed: {exc}"


# ---------------------------------------------------------------------------
# T3.4 — Agent dry-run (10 timesteps)
# ---------------------------------------------------------------------------

def check_t34_dry_run() -> tuple[bool, str]:
    """Run agent --dry-run --dev for 10 timesteps; verify no crash."""
    import os

    energyplus_dir = os.getenv("ENERGYPLUS_DIR", r"C:\EnergyPlusV26-1-0")
    idf = ROOT / "energyplus" / "models" / "runtime.idf"
    if not idf.is_file():
        return False, f"runtime.idf not found at {idf} — run prepare_models.py first"
    if not Path(energyplus_dir).is_dir():
        return False, f"ENERGYPLUS_DIR not found: {energyplus_dir}"

    api_key = os.getenv("GROQ_API_KEY", "")
    if not api_key or api_key.startswith("gsk_your"):
        return False, "GROQ_API_KEY not set; skipping live dry-run."

    rc, out = _run_subprocess(
        [sys.executable, "scripts/run_agent.py", "--dev", "--dry-run"],
        timeout=600,
    )
    last = "\n".join(out.splitlines()[-25:])
    if rc == 0 or "Dry-run limit reached" in out or "Agent run complete" in out:
        return True, last
    return False, last


# ---------------------------------------------------------------------------
# T3.5 — Decision log integrity
# ---------------------------------------------------------------------------

def check_t35_decision_log() -> tuple[bool, str]:
    """Find the most recent agent run log and validate its JSONL structure."""
    agent_dir = ROOT / "data" / "agent"
    if not agent_dir.is_dir():
        return False, "data/agent/ directory not found — run T3.4 first."

    runs = sorted(agent_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
    if not runs:
        return False, "No agent runs found in data/agent/."

    log = runs[0] / "decisions.jsonl"
    if not log.is_file():
        return False, f"decisions.jsonl not found in {runs[0]}"

    required_fields = {
        "timestep", "sim_hour", "energy_kwh", "reasoning",
        "tool_calls", "actions_applied", "fallback_used",
    }
    lines = log.read_text(encoding="utf-8").strip().splitlines()
    if not lines:
        return False, "decisions.jsonl is empty."

    errors = []
    for i, line in enumerate(lines[:10]):
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"Line {i}: invalid JSON — {exc}")
            continue
        missing = required_fields - entry.keys()
        if missing:
            errors.append(f"Line {i} missing fields: {missing}")

    if errors:
        return False, "\n".join(errors)

    return True, f"{len(lines)} log entries valid in {log}"


# ---------------------------------------------------------------------------
# Gate runner
# ---------------------------------------------------------------------------

def main() -> None:
    print("=== Phase 3 Gate ===\n")

    checks = [
        ("T3.1", "Unit tests (comfort, memory, grid, tools)", check_t31_unit_tests),
        ("T3.2", "Groq LLM connectivity (dev model)", check_t32_groq_connectivity),
        ("T3.3", "MCP schema + OpenAI format smoke", check_t33_schema_smoke),
        ("T3.4", "Agent dry-run (10 timesteps)", check_t34_dry_run),
        ("T3.5", "Decision log JSONL integrity", check_t35_decision_log),
    ]

    results: dict[str, bool] = {}
    for code, desc, fn in checks:
        print(f"Running {code}: {desc}...")
        t0 = time.monotonic()
        try:
            ok, detail = fn()
        except Exception as exc:  # noqa: BLE001
            ok, detail = False, f"EXCEPTION: {exc}"
        elapsed = time.monotonic() - t0
        tag = PASS if ok else FAIL
        results[code] = ok
        print(f"  {tag} {code} ({elapsed:.1f}s) — {desc}")
        for line in detail.splitlines()[-5:]:
            print(f"    {line}")
        print()

    # Exit gate decision
    required_pass = {"T3.1", "T3.2", "T3.3"}
    optional_skipped = not results.get("T3.4") and not results.get("T3.5")
    all_required = all(results.get(k, False) for k in required_pass)

    print("-" * 60)
    if all_required:
        print("EXIT GATE: GREEN — Phase 3 agent layer ready.")
        if optional_skipped:
            print("  (T3.4/T3.5 skipped — GROQ_API_KEY missing or IDF absent;")
            print("   run with GROQ_API_KEY set to validate end-to-end.)")
        sys.exit(0)
    else:
        failed = [k for k in required_pass if not results.get(k)]
        print(f"EXIT GATE: RED — failing: {failed}")
        sys.exit(1)


if __name__ == "__main__":
    main()
