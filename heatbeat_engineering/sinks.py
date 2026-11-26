"""Common interface of every heat use ("sink") in a chain.

A sink says what it needs (hourly demand at a delivery temperature, plus pipe losses and pump
power to get it there) and, once the chain has decided how much heat it actually gets, what that is
worth (revenue, avoided CO2, water produced, CAPEX). The chain simulator in `chains.py` does the
hourly allocation and the energy balance; sinks never see each other.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import numpy as np

H = 8760


@dataclass
class SinkPlan:
    name: str
    label: str
    t_req_c: float                      # temperature the sink needs at its inlet
    demand_mw: np.ndarray | None        # useful heat wanted per hour; None = takes whatever is left
    loss_mw: np.ndarray | float = 0.0   # heat lost on the way (pipes), supplied on top of the delivery
    aux_mw: np.ndarray | float = 0.0    # pumping electricity at full demand (scaled by delivery share)
    ko: str | None = None               # reason the sink is not feasible at this site
    settle: Callable[[np.ndarray], dict] | None = None
    direct_only: bool = False           # True: no heat pump allowed (e.g. adsorption chiller drive)
    notes: list[str] = field(default_factory=list)
    kind: str = "heat"                  # "heat" or "cold" (adsorption: handled by the chain)


def annuity(P: dict) -> float:
    r, n = P["discount_rate"], P["lifetime_yr"]
    return r / (1 - (1 + r) ** -n)


def ko_plan(name: str, label: str, reason: str) -> SinkPlan:
    return SinkPlan(name, label, 0.0, np.zeros(H), ko=reason, settle=lambda q: {})


# ---- shared pipe model --------------------------------------------------------------------------

def pipe(length_m: float, q_peak_mw: float, t_supply_c: float, t_return_c: float, t_ground_c: float, P: dict) -> dict:
    """Pre-insulated twin line (supply + return) sized for q_peak.

    Mass flow m = Q / (cp dT); inner diameter from the design velocity; U' per pipe = a + b DN.
    Heat loss (always on, the line stays hot) = U' L [(T_s - T_g) + (T_r - T_g)].
    Pump power at design = V dp / eta with dp = specific pressure drop x 2 L + 150 kPa (stations).
    """
    dT = max(t_supply_c - t_return_c, 5.0)
    m = q_peak_mw * 1e6 / (P["cp_water_kj_kgk"] * 1e3 * dT)  # kg/s
    vol = m / P["rho_water_kg_m3"]
    d_mm = max(np.sqrt(4 * vol / (np.pi * P["dh_velocity_ms"])) * 1000, 50.0)
    u = P["dh_u_a_w_mk"] + P["dh_u_b_w_mk_per_mm"] * d_mm
    loss_mw = u * length_m * ((t_supply_c - t_ground_c) + (t_return_c - t_ground_c)) / 1e6
    dp = P["dh_dp_pa_m"] * 2 * length_m + 150e3
    pump_mw = vol * dp / P["dh_pump_eff"] / 1e6
    capex = (P["capex_pipe_usd_m_a"] + P["capex_pipe_usd_m_b"] * d_mm) * length_m * P["capex_factor"]
    return {"dn_mm": d_mm, "u_w_mk": u, "loss_mw": max(loss_mw, 0.0), "pump_design_mw": pump_mw,
            "capex_usd": capex, "flow_kg_s": m, "length_m": length_m}
