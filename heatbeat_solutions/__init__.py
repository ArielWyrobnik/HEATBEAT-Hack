"""HEATBEAT solution catalogue: candidate waste stream solutions and a first pre-screening.

    import heatbeat_solutions as hs

    cat = hs.load_catalogue()                 # dict id -> Solution (validated)
    cat["med_desalination"].heat.source_t_min_c

    # Pre-screen one site. heat_profile uses the field names of hd.site_heat_profiles(),
    # site_summary is hd.get_site(id).summary(), weather is optional hd.get_site(id).weather.
    ranking = hs.screen(heat_profile, site_summary, weather=None, context={"coastal": True})

The screening is a transparent feasibility filter, NOT a solution model. It tells the team
which models are worth running at a site. All numbers come from catalogue.yaml.
"""
from .schema import Solution, load_catalogue, CATALOGUE_PATH
from .screening import screen, heat_pump_cop

__all__ = ["Solution", "load_catalogue", "CATALOGUE_PATH", "screen", "heat_pump_cop"]
