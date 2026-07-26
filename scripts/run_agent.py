#!/usr/bin/env python
"""
run_agent.py — EcoLoop Phase 3 main entry point.

Wires EPRunner + EPReader + EPWriter + LLMClient + EcoLoopOrchestrator
into a closed-loop simulation run on runtime.idf.

Usage
-----
    uv run python scripts/run_agent.py            # prod model (70B)
    uv run python scripts/run_agent.py --dev      # dev model (8B, faster)
    uv run python scripts/run_agent.py --dev --steps 4   # call LLM every 4 timesteps

Outputs
-------
    data/agent/<run_id>/decisions.jsonl   per-timestep decision log
    data/agent/<run_id>/summary.json      run-level energy savings summary
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Resolve project root and load .env before any other imports
# ---------------------------------------------------------------------------
ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env", override=False)
except ImportError:
    pass  # python-dotenv optional; user must set env vars manually

# ---------------------------------------------------------------------------
# Logging — INFO to console, DEBUG to file
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(name)s — %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("EcoLoop.run_agent")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ENERGYPLUS_DIR = os.getenv("ENERGYPLUS_DIR", r"C:\EnergyPlusV26-1-0")
IDF = ROOT / "energyplus" / "models" / "runtime.idf"
EPW = ROOT / "energyplus" / "weather" / "usa_il_chicago.epw"
OUTPUT_DIR = ROOT / "data" / "agent_run"
BASELINE_SUMMARY = ROOT / "data" / "baseline_results" / "summary.json"

# ---------------------------------------------------------------------------
# EnergyPlus API bootstrap (must happen before bridge imports)
# ---------------------------------------------------------------------------
sys.path.insert(0, ENERGYPLUS_DIR)


def _check_prereqs() -> None:
    if not Path(ENERGYPLUS_DIR).is_dir():
        logger.error("ENERGYPLUS_DIR not found: %s", ENERGYPLUS_DIR)
        sys.exit(1)
    if not IDF.is_file():
        logger.error("runtime.idf not found at %s  (run prepare_models.py first)", IDF)
        sys.exit(1)
    if not EPW.is_file():
        logger.error("Weather file not found: %s", EPW)
        sys.exit(1)
    api_key = os.getenv("GROQ_API_KEY", "")
    if not api_key or api_key.startswith("gsk_your"):
        logger.warning(
            "GROQ_API_KEY is not set. Set it in .env or the agent will use fallback for every step."
        )


def _load_baseline_kwh() -> float:
    """Read baseline from Phase 1 summary.json (frozen reference)."""
    if BASELINE_SUMMARY.is_file():
        try:
            data = json.loads(BASELINE_SUMMARY.read_text(encoding="utf-8"))
            kwh = float(data["electricity_facility_kwh"])
            logger.info("Baseline: %.3f kWh (from %s)", kwh, BASELINE_SUMMARY)
            return kwh
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not parse baseline summary: %s", exc)
    logger.warning("Baseline summary not found. Using default 172.48 kWh.")
    return 172.48


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="EcoLoop agent run")
    parser.add_argument(
        "--dev",
        action="store_true",
        help="Use dev model (llama-3.1-8b-instant) instead of scored model.",
    )
    parser.add_argument(
        "--steps",
        type=int,
        default=None,
        help="Call LLM every N timesteps (default: AGENT_EVERY_N_STEPS env or 1).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Stop after first 10 timesteps (quick smoke test).",
    )
    args = parser.parse_args()

    _check_prereqs()
    baseline_kwh = _load_baseline_kwh()

    run_id = time.strftime("%Y%m%d_%H%M%S") + ("_dev" if args.dev else "_prod")
    logger.info("=== EcoLoop Agent Run: %s ===", run_id)
    logger.info("IDF: %s", IDF)
    logger.info("EPW: %s", EPW)
    logger.info("dev_mode=%s every_n=%s dry_run=%s", args.dev, args.steps, args.dry_run)

    # --- Bridge components ---
    from bridge.ep_reader import EPReader
    from bridge.ep_runner import EPRunner
    from bridge.ep_writer import EPWriter

    runner = EPRunner(IDF, EPW, OUTPUT_DIR / run_id)
    reader = EPReader(runner.api, runner.state, dump_dir=OUTPUT_DIR / run_id)
    writer = EPWriter(runner.api, runner.state)

    # --- LLM ---
    from agent.llm_client import LLMClient

    llm = LLMClient(dev_mode=args.dev)

    # --- Orchestrator ---
    from agent.orchestrator import EcoLoopOrchestrator

    orch = EcoLoopOrchestrator(
        reader,
        writer,
        llm,
        baseline_kwh=baseline_kwh,
        run_id=run_id,
        agent_every_n_steps=args.steps,
    )

    # Dry-run guard: stop after 10 timesteps
    if args.dry_run:
        _original_step = orch.step

        def _limited_step(state: Any) -> None:  # type: ignore[name-defined]
            _original_step(state)
            if orch.timestep >= 10:
                logger.info("Dry-run limit reached (10 timesteps). Stopping.")
                runner.api.runtime.stop_simulation(state)

        orch.step = _limited_step  # type: ignore[method-assign]

    runner.register_callback(orch.step)

    # --- Run ---
    logger.info("Starting EnergyPlus simulation…")
    t0 = time.monotonic()
    exit_code = runner.run()
    elapsed = time.monotonic() - t0

    logger.info(
        "Simulation finished in %.1fs. EP exit_code=%d  callbacks=%d  errors=%d",
        elapsed,
        exit_code,
        runner.callback_invocations,
        runner.callback_errors,
    )

    if exit_code != 0:
        logger.error("EnergyPlus exited with code %d — check EP output.", exit_code)

    # --- Save summary ---
    summary_path = orch.save_summary()
    logger.info("Agent run complete. Summary: %s", summary_path)

    # Print quick result
    if summary_path.is_file():
        s = json.loads(summary_path.read_text(encoding="utf-8"))
        print(
            f"\n{'='*60}\n"
            f"  Baseline : {s.get('baseline_kwh', '?')} kWh\n"
            f"  Agent    : {s.get('agent_final_kwh', '?')} kWh\n"
            f"  Savings  : {s.get('savings_kwh', '?')} kWh ({s.get('savings_pct', '?')}%)\n"
            f"  LLM calls: {s.get('llm_calls', '?')}  tokens: {s.get('total_tokens', '?')}\n"
            f"  Fallbacks: {s.get('fallback_count', '?')}\n"
            f"  Clamps   : {s.get('total_clamp_events', '?')}\n"
            f"{'='*60}"
        )

    sys.exit(0 if exit_code == 0 else 1)


if __name__ == "__main__":
    # Type hint fix for the dry-run closure
    from typing import Any  # noqa: F401
    main()
