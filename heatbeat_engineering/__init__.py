"""HEATBEAT engineering model: physically explicit heat chains per data center.

    from heatbeat_engineering import load_site, evaluate_site
    site = load_site("us-ia-council-bluffs-google")
    table, baseline, results = evaluate_site(site)

See docs/ENGINEERING.md for the physics, parameters and sources.
"""
from .chains import baseline, best_per_use, build_plans, evaluate_site, simulate  # noqa: F401
from .params import PARAMS, defaults  # noqa: F401
from .site import load_location, load_site, synthetic_site  # noqa: F401


def evaluate(lat=None, lon=None, it_mw=None, cooling="dlc_warm", greenfield=True, site_id=None, weather=None,
             overrides=None, params=None, live=True):
    """One call for both cases: a database site (site_id) or a planned data center (lat, lon, it_mw).

    Returns (ranked chains table, baseline result, all chain results, site case).
    """
    if site_id:
        case = load_site(site_id, live=live, weather=weather, is_greenfield=None if greenfield is None else int(greenfield),
                         overrides=overrides)
    else:
        case = load_location(lat, lon, it_mw, cooling, greenfield, weather=weather, live=live, overrides=overrides)
    df, base, res = evaluate_site(case, params)
    return df, base, res, case
