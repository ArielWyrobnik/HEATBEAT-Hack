"""HEATBEAT ranking engine, ported from the team Excel model "Hack data.xlsx".

    from heatbeat_ranking import evaluate, excel_example_inputs, excel_example_t_amb
    evaluate(excel_example_inputs(), excel_example_t_amb(), mode="excel")

See docs/RANKING.md for the model, heatbeat_ranking/AUDIT.md for the review of the Excel.
"""
from .climate import diurnal_from_daily, excel_example_t_amb, hourly_from_site
from .engine import CORRECTED, MODES, evaluate
from .inputs import INPUT_SPEC, excel_example_inputs, site_inputs
from .options import OPTIONS

__all__ = ["CORRECTED", "INPUT_SPEC", "MODES", "OPTIONS", "diurnal_from_daily", "evaluate",
           "excel_example_inputs", "excel_example_t_amb", "hourly_from_site", "site_inputs"]
from .sensitivity import input_influence, tornado  # noqa: E402
from .site import rank_site  # noqa: E402

__all__ += ["input_influence", "rank_site", "tornado"]
