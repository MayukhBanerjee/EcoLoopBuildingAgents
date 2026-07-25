"""
Run uncontrolled baseline EnergyPlus simulation.
Writes outputs to data/baseline_results/.
Do this before the agent loop so the dashboard can compute % savings.
"""

from __future__ import annotations


def main() -> None:
    raise NotImplementedError("Invoke energyplus.exe on baseline.idf + weather.")


if __name__ == "__main__":
    main()
