"""
generate_comparison.py — produce dashboard-ready comparison data.

Job: Read baseline + agent eplusout.csv and agent_decisions.jsonl; write
tidy CSVs and kpis.json to data/comparison/. The dashboard only renders
these files — it never recomputes.

Outputs:
  data/comparison/energy_timeseries.csv  (step, baseline_kwh_cum, agent_kwh_cum)
  data/comparison/zone_temps.csv
  data/comparison/kpis.json              (savings %, comfort %, fallbacks, latency)

Build: Phase 5, after the first full closed-loop run.
"""

from __future__ import annotations


def main() -> None:
    raise NotImplementedError("Implement after Phase 4 produces real outputs.")


if __name__ == "__main__":
    main()
