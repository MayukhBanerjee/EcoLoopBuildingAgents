"""
EcoLoop entry point.

Wires EPRunner + EPReader + EPWriter + LLM + Orchestrator,
registers the timestep callback, runs the closed-loop simulation,
and writes data/logs/agent_decisions.jsonl.
"""

from dotenv import load_dotenv

load_dotenv()


def main() -> None:
    raise NotImplementedError("Wire bridge + agent here (see plan §5).")


if __name__ == "__main__":
    main()
