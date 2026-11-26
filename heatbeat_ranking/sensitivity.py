"""Sensitivity analysis.

- `tornado(x, t_amb, option_key)`: one at a time low/high swing of every numeric input, effect on
  one option's net value (USD/yr) and viability score. Data for a tornado chart.
- `input_influence(x, t_amb)`: how much each input changes the whole ranking when swung across its
  plausible US range. Used to decide which missing GIS inputs are worth sourcing first.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .engine import evaluate
from .inputs import INPUT_SPEC


def _swing(x, key):
    rng = INPUT_SPEC[key][1]
    if rng is None:
        return None
    return rng


def tornado(x: dict, t_amb: np.ndarray, option_key: str, mode: str = "corrected",
            metric: str = "net_value_usd_yr") -> pd.DataFrame:
    base = evaluate(x, t_amb, mode).set_index("key").loc[option_key, metric]
    rows = []
    for k in INPUT_SPEC:
        rng = _swing(x, k)
        if rng is None or k not in x:
            continue
        vals = []
        for v in rng:
            y = dict(x, **{k: v})
            vals.append(float(evaluate(y, t_amb, mode).set_index("key").loc[option_key, metric]))
        rows.append({"input": k, "low_value": rng[0], "high_value": rng[1], "metric_low": vals[0],
                     "metric_high": vals[1], "swing": abs(vals[1] - vals[0])})
    df = pd.DataFrame(rows).sort_values("swing", ascending=False).reset_index(drop=True)
    df.attrs.update(base=float(base), metric=metric, option=option_key)
    return df


def _ranking(df):
    ok = df[df["ko_gate"] == 1].sort_values("viability_score", ascending=False)
    return list(ok["key"])


def input_influence(x: dict, t_amb: np.ndarray, mode: str = "corrected",
                    keys: list[str] | None = None) -> pd.DataFrame:
    """For each input: options whose KO gate flips, change of the top option, mean |score change|."""
    base = evaluate(x, t_amb, mode).set_index("key")
    base_rank = _ranking(base.reset_index())
    rows = []
    for k in keys or list(INPUT_SPEC):
        rng = _swing(x, k)
        if rng is None or k not in x:
            continue
        flips, top_changes, dscore = set(), 0, []
        for v in rng:
            r = evaluate(dict(x, **{k: v}), t_amb, mode).set_index("key").reindex(base.index)
            flips |= set(r.index[r["ko_gate"] != base["ko_gate"]])
            rk = _ranking(r.reset_index())
            top_changes += int((rk[:1] or [None]) != (base_rank[:1] or [None]))
            dscore.append((r["viability_score"] - base["viability_score"]).abs().mean())
        rows.append({"input": k, "range": f"{rng[0]} to {rng[1]}", "gates_flipped": len(flips),
                     "options_flipped": ", ".join(sorted(flips)), "top_option_changes": top_changes,
                     "mean_abs_score_change": round(float(np.mean(dscore)), 3)})
    return (pd.DataFrame(rows)
            .sort_values(["gates_flipped", "top_option_changes", "mean_abs_score_change"], ascending=False)
            .reset_index(drop=True))
