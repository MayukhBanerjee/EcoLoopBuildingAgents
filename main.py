#!/usr/bin/env python
"""
main.py — EcoLoop Phase 4 closed-loop entry point.

Wires EPRunner + EPReader + EPWriter + LLMClient + EcoLoopOrchestrator,
runs a full 96-step day, and writes:

  data/agent_results/<run_id>/
      agent_decisions.jsonl
      summary.json
      actuator_timeline.csv
      runtime_final_state.idf

Usage
-----
    uv run python main.py --dev              # 8B shakeout (recommended first)
    uv run python main.py                    # 70B scored run
    uv run python main.py --dev --dry-run    # 10-step smoke
    uv run python main.py --dev --chaos      # T4.3: force fallback (no LLM)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parent.resolve()
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env", override=False)
except ImportError:
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(name)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("EcoLoop.main")

ENERGYPLUS_DIR = os.getenv("ENERGYPLUS_DIR", r"C:\EnergyPlusV26-1-0")
IDF = ROOT / "energyplus" / "models" / "runtime.idf"
EPW = ROOT / "energyplus" / "weather" / "usa_il_chicago.epw"
RESULTS_ROOT = ROOT / "data" / "agent_results"
BASELINE_SUMMARY = ROOT / "data" / "baseline_results" / "summary.json"

sys.path.insert(0, ENERGYPLUS_DIR)


def _check_prereqs() -> None:
    if not Path(ENERGYPLUS_DIR).is_dir():
        logger.error("ENERGYPLUS_DIR not found: %s", ENERGYPLUS_DIR)
        sys.exit(1)
    if not IDF.is_file():
        logger.error("runtime.idf not found at %s (run prepare_models.py first)", IDF)
        sys.exit(1)
    if not EPW.is_file():
        logger.error("Weather file not found: %s", EPW)
        sys.exit(1)


def _load_baseline_kwh() -> float:
    if BASELINE_SUMMARY.is_file():
        try:
            data = json.loads(BASELINE_SUMMARY.read_text(encoding="utf-8"))
            kwh = float(data["electricity_facility_kwh"])
            logger.info("Baseline: %.3f kWh", kwh)
            return kwh
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not parse baseline summary: %s", exc)
    logger.warning("Using default baseline 172.48 kWh")
    return 172.48


def _print_banner(summary: dict[str, Any]) -> None:
    print(
        f"\n{'=' * 64}\n"
        f"  EcoLoop Closed-Loop Result\n"
        f"  Run ID     : {summary.get('run_id', '?')}\n"
        f"  Timesteps  : {summary.get('total_timesteps', '?')}\n"
        f"  Baseline   : {summary.get('baseline_kwh', '?')} kWh\n"
        f"  Agent      : {summary.get('agent_final_kwh', '?')} kWh\n"
        f"  Savings    : {summary.get('savings_kwh', '?')} kWh"
        f" ({summary.get('savings_pct', '?')}%)\n"
        f"  LLM calls  : {summary.get('llm_calls', '?')}"
        f"  tokens: {summary.get('total_tokens', '?')}\n"
        f"  Fallbacks  : {summary.get('fallback_count', '?')}\n"
        f"  Clamps     : {summary.get('total_clamp_events', '?')}\n"
        f"{'=' * 64}\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="EcoLoop Phase 4 closed-loop run")
    parser.add_argument(
        "--dev",
        action="store_true",
        help="Use DEV_MODEL_NAME (llama-3.1-8b-instant).",
    )
    parser.add_argument(
        "--steps",
        type=int,
        default=None,
        help="LLM every N timesteps (default AGENT_EVERY_N_STEPS or 1).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Stop after 10 timesteps (smoke test).",
    )
    parser.add_argument(
        "--chaos",
        action="store_true",
        help="T4.3: clear GROQ_API_KEY so every step uses fallback.",
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=None,
        help="Stop simulation after N agent timesteps (for gate smoke).",
    )
    parser.add_argument(
        "--stream",
        action="store_true",
        help="Render the live EnergyPlus->LLM->actuator flow in the terminal.",
    )
    parser.add_argument(
        "--no-stream-file",
        action="store_true",
        help="Skip writing stream_events.jsonl (terminal output only).",
    )
    args = parser.parse_args()

    if args.chaos:
        os.environ.pop("GROQ_API_KEY", None)
        os.environ["GROQ_API_KEY"] = ""
        logger.warning("CHAOS MODE: GROQ_API_KEY cleared — fallback every step.")

    _check_prereqs()
    baseline_kwh = _load_baseline_kwh()

    mode = "chaos" if args.chaos else ("dev" if args.dev else "prod")
    run_id = time.strftime("%Y%m%d_%H%M%S") + f"_{mode}"
    out_dir = RESULTS_ROOT / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    stop_after = 10 if args.dry_run else args.max_steps
    if stop_after:
        # Must set BEFORE importing/constructing LLMClient (spacing read at import)
        os.environ.setdefault("AGENT_MAX_TOOL_ROUNDS", "2")
        os.environ.setdefault("AGENT_CALL_SPACING_S", "0.5")

    logger.info("=== EcoLoop Phase 4: %s ===", run_id)
    logger.info("IDF=%s EPW=%s out=%s", IDF, EPW, out_dir)

    from bridge.ep_reader import EPReader
    from bridge.ep_runner import EPRunner
    from bridge.ep_writer import EPWriter
    from agent.llm_client import LLMClient
    from agent.orchestrator import EcoLoopOrchestrator
    from agent.stream import ConsoleSink, JsonlSink, StreamBus

    # Fresh EP state for each run
    from bridge import state_manager

    state_manager.reset_state()

    # Observability bus: always records to disk, renders to terminal on --stream.
    stream = StreamBus()
    if not args.no_stream_file:
        stream.add(JsonlSink(out_dir / "stream_events.jsonl"))
    if args.stream:
        # EnergyPlus writes progress to stdout; keep the flow readable.
        logging.getLogger("EcoLoop.agent.orchestrator").setLevel(logging.WARNING)
        stream.add(ConsoleSink())
        logger.info("Live stream enabled — rendering EnergyPlus -> LLM flow.")

    runner = EPRunner(IDF, EPW, out_dir / "eplus")
    reader = EPReader(runner.api, runner.state, dump_dir=out_dir)
    writer = EPWriter(runner.api, runner.state)
    llm = LLMClient(dev_mode=args.dev or args.chaos)

    orch = EcoLoopOrchestrator(
        reader,
        writer,
        llm,
        baseline_kwh=baseline_kwh,
        run_id=run_id,
        agent_every_n_steps=args.steps,
        output_dir=out_dir,
        source_idf=IDF,
        stream=stream,
    )

    if stop_after:
        original = orch.step
        _stop_requested = {"n": 0}

        def limited(state: Any) -> None:
            original(state)
            if orch.timestep >= stop_after:
                _stop_requested["n"] += 1
                logger.info(
                    "Stop limit reached (%d timesteps). Requesting EP stop (%d).",
                    stop_after,
                    _stop_requested["n"],
                )
                try:
                    runner.api.runtime.stop_simulation(state)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("stop_simulation failed: %s", exc)

        orch.step = limited  # type: ignore[method-assign]

    runner.register_callback(orch.step)

    logger.info("Starting EnergyPlus closed-loop simulation...")
    t0 = time.monotonic()
    exit_code = runner.run()
    elapsed = time.monotonic() - t0
    stream.close()
    logger.info(
        "Finished in %.1fs | exit=%d | callbacks=%d | errors=%d",
        elapsed,
        exit_code,
        runner.callback_invocations,
        runner.callback_errors,
    )

    summary_path = orch.save_summary()
    # Also copy/symlink summary to data/agent_results/summary.json (latest pointer)
    latest = RESULTS_ROOT / "summary.json"
    try:
        latest.write_text(summary_path.read_text(encoding="utf-8"), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not write latest summary pointer: %s", exc)

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    _print_banner(summary)

    # Soft success: EP exit 0 OR dry-run stopped early with decisions
    ok = exit_code == 0 or (stop_after is not None and orch.timestep >= 1)
    if not ok:
        logger.error("Run failed (EnergyPlus exit %d).", exit_code)
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
