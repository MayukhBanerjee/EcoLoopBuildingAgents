"""
grid.py — carbon grid intensity + peak demand reasoning inputs.

Job: The brief's Reasoning bullet explicitly names "peak demand thresholds
and local carbon grid intensity" as inputs the LLM must evaluate. This
module provides both, injected into every timestep prompt and returned by
the get_energy_report tool.

Build: Phase 3f. Pure Python, no simulator needed.
"""

from __future__ import annotations

import os

# 24-hour carbon intensity profile, gCO2/kWh, Indian grid shape:
# coal-heavy base overnight, solar dip midday, evening peak ramp.
# Shape approximated from CEA/Ember daily curves — documented simplification.
CARBON_INTENSITY_G_PER_KWH = [
    680, 675, 670, 665, 660, 665,  # 00-05 overnight coal base
    670, 660, 630, 590, 550, 520,  # 06-11 solar ramps in
    500, 495, 505, 530, 570, 630,  # 12-17 solar peak then decline
    700, 730, 740, 725, 705, 690,  # 18-23 evening demand peak
]

HIGH_INTENSITY_THRESHOLD = 650.0


def carbon_intensity(hour: int) -> float:
    """gCO2/kWh for the simulated hour of day (0-23)."""
    return CARBON_INTENSITY_G_PER_KWH[hour % 24]


def intensity_label(hour: int) -> str:
    return "HIGH" if carbon_intensity(hour) >= HIGH_INTENSITY_THRESHOLD else "LOW"


def peak_status(current_kw: float) -> str:
    """OK / APPROACHING (>=80% of threshold) / EXCEEDED."""
    threshold = float(os.getenv("PEAK_DEMAND_THRESHOLD_KW", "55.0"))
    if current_kw >= threshold:
        return "EXCEEDED"
    if current_kw >= 0.8 * threshold:
        return "APPROACHING"
    return "OK"
