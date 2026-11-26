"""DSX heat reuse evaluator (v3.3) as a Heat Beat model.

13 heat reuse pathways, knock-out gates that say which site value misses which limit, a viability
score 0 to 5 (thermodynamics, climate fit, economics, utilisation) and a separate eco grade A to F.
`engine.py` is the physics and scoring (a port of the DSX evaluator, same constants), run on the
real hourly weather of the site. `api_model.py` plugs it into heatbeat_api with the site inputs of
heatbeat_ranking (database values with their sources). See docs/DSX.md.
"""
from .engine import C, OPTIONS, VERSION, evaluate

__all__ = ["C", "OPTIONS", "VERSION", "evaluate"]
