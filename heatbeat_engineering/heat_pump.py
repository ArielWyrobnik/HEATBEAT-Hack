"""Large electric heat pump (and the direct heat exchanger alternative).

COP_heating = eta_carnot x T_cond / (T_cond - T_evap)          (temperatures in K)
    T_evap = T_source - evap_drop - approach    (source water is cooled by evap_drop in the evaporator)
    T_cond = T_sink_supply + approach
Energy balance: Q_cond = Q_evap + W, W = Q_cond / COP, Q_evap = Q_cond (1 - 1/COP).
The evaporator heat comes out of the data center loop, so it no longer has to be rejected.

A direct heat exchanger is enough when T_source - hx_approach >= T_sink_supply.
Source: Carnot fraction 0.4 to 0.6 for industrial heat pumps, Arpagaus et al. 2018 (see params).
"""
from __future__ import annotations

import numpy as np


def needs_hp(t_source_c: float, t_sink_c: float, P: dict) -> bool:
    return t_source_c - P["hx_approach_k"] < t_sink_c


def cop(t_source_c, t_sink_c, P: dict):
    te = np.asarray(t_source_c, float) - P["hp_evap_drop_k"] - P["hp_approach_k"] + 273.15
    tc = np.asarray(t_sink_c, float) + P["hp_approach_k"] + 273.15
    lift = np.maximum(tc - te, 1.0)
    return np.minimum(P["hp_carnot_fraction"] * tc / lift, P["hp_cop_max"])


def carnot_cop(t_source_c, t_sink_c):
    tc = np.asarray(t_sink_c, float) + 273.15
    return tc / np.maximum(tc - (np.asarray(t_source_c, float) + 273.15), 1e-6)


def source_heat_for(q_delivered, t_source_c, t_sink_c, P: dict):
    """(evaporator heat drawn from the DC loop, electricity) to deliver q at t_sink_c. Direct HX: no work."""
    q = np.asarray(q_delivered, float)
    if not needs_hp(t_source_c, t_sink_c, P):
        return q, np.zeros_like(q), None
    c = float(cop(t_source_c, t_sink_c, P))
    return q * (1 - 1 / c), q / c, c


def delivered_from_source(q_source, t_source_c, t_sink_c, P: dict):
    """Inverse: heat delivered and electricity when q_source is drawn from the loop."""
    q = np.asarray(q_source, float)
    if not needs_hp(t_source_c, t_sink_c, P):
        return q, np.zeros_like(q), None
    c = float(cop(t_source_c, t_sink_c, P))
    qd = q / (1 - 1 / c)
    return qd, qd / c, c
