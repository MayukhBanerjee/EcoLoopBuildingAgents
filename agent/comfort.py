"""
comfort.py — simplified Fanger PMV (ISO 7730 / ASHRAE 55) thermal comfort model.

Fixed office assumptions (documented deliberately — honesty > fake precision):
  metabolic rate   met = 1.1  (light office work)
  clothing         clo = 0.7  (summer business casual)
  air velocity     v   = 0.1 m/s
  relative humidity RH  = 50 %
  mean radiant temp T_mrt = T_air  (conservative; no solar load modelled)

The iterative clothing-temperature loop converges in < 20 iterations for
temperatures in [16, 32] °C.  Pure Python — no dependencies.

References
----------
  ISO 7730:2005, Annex D
  Fanger, P.O. (1970) Thermal Comfort, McGraw-Hill
"""

from __future__ import annotations

import math

PMV_COMFORT_LIMIT: float = 0.5   # |PMV| ≤ 0.5 → ASHRAE 55 comfort band

# Fixed occupant / clothing parameters
_MET: float = 1.1          # metabolic rate, met
_CLO: float = 0.7          # clothing insulation, clo
_V_AR: float = 0.1         # air velocity, m/s
_RH: float = 50.0          # relative humidity, %

# Derived physical constants
_M: float = _MET * 58.15   # metabolic rate W/m²
_W: float = 0.0            # external work W/m² (office = 0)
_I_CL: float = _CLO * 0.155  # clothing thermal resistance m²K/W
# Clothing area factor (ISO 7730 eq. A.4)
_F_CL: float = 1.05 + 1.97 * _I_CL if _CLO > 0.5 else 1.0 + 1.29 * _I_CL
# Forced-convection heat transfer coefficient (constant for fixed air speed)
_H_C_FORCED: float = 12.1 * math.sqrt(_V_AR)


def _solve_t_cl(T_a: float, T_mrt: float) -> tuple[float, float]:
    """Solve for clothing surface temperature T_cl using bisection (ISO 7730).

    The fixed-point iteration in the original Fanger formulation can oscillate
    for typical office conditions; bisection is unconditionally convergent since
    the residual f(T_cl) is monotonically increasing over physical bounds.

    Returns (T_cl, h_c) at convergence.
    """
    def _residual(T_cl: float) -> float:
        h_c = max(2.38 * abs(T_cl - T_a) ** 0.25, _H_C_FORCED)
        return (
            T_cl
            - (35.7 - 0.028 * (_M - _W))
            + _I_CL * (
                3.96e-8 * _F_CL * ((T_cl + 273.0) ** 4 - (T_mrt + 273.0) ** 4)
                + _F_CL * h_c * (T_cl - T_a)
            )
        )

    # Bisect over [T_a - 30, T_a + 40] — always brackets the solution
    T_lo, T_hi = T_a - 30.0, T_a + 40.0
    for _ in range(60):  # 60 steps → < 7e-16 °C precision from 70 °C range
        T_mid = 0.5 * (T_lo + T_hi)
        val = _residual(T_mid)
        if abs(val) < 1e-4:
            break
        if _residual(T_lo) * val < 0.0:
            T_hi = T_mid
        else:
            T_lo = T_mid
    T_cl = 0.5 * (T_lo + T_hi)
    h_c = max(2.38 * abs(T_cl - T_a) ** 0.25, _H_C_FORCED)
    return T_cl, h_c


def pmv(temp_c: float) -> float:
    """Predicted Mean Vote for a zone air temperature under fixed conditions.

    Returns a value in roughly [-3, +3]:
      -0.5 to +0.5  comfortable (ASHRAE 55)
      < -1          too cold
      > +1          too warm

    Args:
        temp_c: Zone mean air temperature in °C.
    """
    T_a = temp_c
    T_mrt = temp_c  # radiant = air (conservative)

    # Partial water vapour pressure (Pa) — Antoine equation
    p_sat_kpa = math.exp(16.6536 - 4030.183 / (T_a + 235.0))
    p_a = _RH / 100.0 * p_sat_kpa * 1000.0  # Pa

    T_cl, h_c_final = _solve_t_cl(T_a, T_mrt)

    # Thermal load (W/m²) — net heat that must be dissipated to maintain comfort
    L = (
        (_M - _W)
        # Evaporative sweating
        - 3.05e-3 * (5733.0 - 6.99 * (_M - _W) - p_a)
        # Regulatory sweating (only positive)
        - max(0.0, 0.42 * ((_M - _W) - 58.15))
        # Respiratory latent heat
        - 1.7e-5 * _M * (5867.0 - p_a)
        # Respiratory sensible heat
        - 0.0014 * _M * (34.0 - T_a)
        # Radiation from clothing surface
        - 3.96e-8 * _F_CL * ((T_cl + 273.0) ** 4 - (T_mrt + 273.0) ** 4)
        # Convection from clothing surface
        - _F_CL * h_c_final * (T_cl - T_a)
    )

    result = (0.303 * math.exp(-0.036 * _M) + 0.028) * L
    return round(result, 3)


def comfort_ok(pmv_value: float) -> bool:
    """True when |PMV| ≤ 0.5 (ASHRAE 55 comfort band)."""
    return abs(pmv_value) <= PMV_COMFORT_LIMIT


def pmv_label(pmv_value: float) -> str:
    """Human-readable comfort label for prompt injection."""
    if pmv_value < -2:
        return "VERY_COLD"
    if pmv_value < -1:
        return "COLD"
    if pmv_value < -0.5:
        return "SLIGHTLY_COOL"
    if pmv_value <= 0.5:
        return "COMFORTABLE"
    if pmv_value <= 1.0:
        return "SLIGHTLY_WARM"
    if pmv_value <= 2.0:
        return "WARM"
    return "VERY_HOT"
