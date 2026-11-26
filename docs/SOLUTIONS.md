# HEATBEAT solution catalogue

Shared list of candidate solutions for data center waste streams (waste heat, stranded power, water),
with the parameters a site needs for each one to make sense. Solution models are built by the team;
this catalogue is what the ranking screens against before a full model is run.

- Data: `heatbeat_solutions/catalogue.yaml` (21 entries, all values as ranges, every entry with sources and a confidence flag)
- Schema and validation: `heatbeat_solutions/schema.py`
- First pass screening: `heatbeat_solutions/screening.py`
- Tests: `tests/test_solutions.py` (`python -m pytest tests/test_solutions.py`)

## How it connects to the database

The screening reads only fields that already exist or are being added:

| Input | From | Fields used |
|---|---|---|
| Heat source | `hd.site_heat_profiles()` (PR #4, schema in `docs/HEAT_PROFILES.md`) | `facility_return_temp_c`, `liquid_heat_share`, `exhaust_air_temp_c`, `it_load_mw`, `is_assumed` (NaN temperatures are treated as air side heat) |
| Climate | `hd.get_site(id).summary()` (PR #1) | `heating_degree_hours_18c`, `cooling_degree_hours_18c`, `t_db_mean_c`, `price_mean_usd_mwh`, `price_p10_usd_mwh`, `price_p90_usd_mwh` |
| Hourly weather (optional) | `hd.get_site(id).weather` (PR #1) | `t_db_c` |
| Site context | passed by the caller | `coastal`, `evaporative_cooling`, `water_stress`, `country_iso2` |

```python
import heatbeat_data as hd
import heatbeat_solutions as hs

site = hd.get_site("il-...")
hp = site.heat_profile()               # from the cooling profiles work
ranking = hs.screen(hp, site.summary(), weather=site.weather, context={"coastal": True, "country_iso2": "IL"})
ranking[0]                             # dict with score, sub scores, reasons, heat pump need
```

## Scoring

Each sub score is 0 to 1:

- **temperature**: coolant return temperature vs. `heat.source_t_min_c` and `heat.source_t_ideal_c`. Below the minimum, solutions with `heat_pump_boost_ok` get a reduced score based on the heat pump COP (Carnot fraction 0.5). Air cooled sites (`liquid_heat_share` 0) are treated as 35 C exhaust air with a 0.7 capture penalty.
- **demand**: from `demand_driver`. Heating degree hours (full score at 80,000, about Stockholm), cooling degree hours (full at 30,000), water stress, price spread, or a neutral 0.6 for demand that is not climate driven.
- **ambient**: share of hours with `t_db_c` inside the ideal range, half credit inside the tolerable range.
- **maturity**: upper TRL / 9.
- **total** = temperature x (0.45 demand + 0.30 ambient + 0.25 maturity), and 0 if a hard requirement (`requires`, for example `coastal`) is not met.

All reference scales and weights are HEATBEAT screening assumptions, not literature values. They are constants at the top of `screening.py` so the team can tune them. Compare solutions within a category; stranded power solutions do not depend on heat and naturally score high.

The screening ranks potential. It does not know whether an offtaker (fish farm, greenhouse, desalination plant) exists next to the site. That check, and market prices, come in the solution models for the shortlist.

## Catalogue overview

| id | Category | Source min C | Source ideal C | Demand driver | Main output | TRL | Israel fit | Confidence |
|---|---|---|---|---|---|---|---|---|
| `aquaculture_ras` | waste_heat | 28 to 30 | 32 to 45 | heating_degree | fish (live weight) | 9 | medium | estimate |
| `pool_heating` | waste_heat | 30 to 32 | 35 to 50 | heating_degree | pool heat delivered | 9 | low | unverified |
| `swro_feed_preheat` | water | 25 to 30 | 30 to 45 | constant | SWRO electricity saved | 5 to 7 | high | unverified |
| `greenhouse_heating` | waste_heat | 30 to 35 | 40 to 60 | heating_degree | vegetables (tomato equivalent) | 9 | medium | estimate |
| `anaerobic_digestion` | waste_heat | 40 to 45 | 45 to 65 | heating_degree | biogas | 9 | medium | estimate |
| `microalgae` | waste_heat | 35 to 38 | 40 to 55 | heating_degree | algae biomass (dry) | 7 to 9 | medium | unverified |
| `low_temp_drying` | waste_heat | 40 to 45 | 50 to 70 | constant | water removed | 9 | medium | estimate |
| `district_heating_5gdh` | waste_heat | 20 to 25 | 25 to 40 | heating_degree | heat delivered to buildings | 8 to 9 | low | estimate |
| `district_heating_4gdh` | waste_heat | 55 to 60 | 65 to 80 | heating_degree | heat delivered to network | 9 | low | literature |
| `domestic_hot_water` | waste_heat | 58 to 62 | 60 to 70 | constant | hot water heat delivered | 9 | medium | unverified |
| `adsorption_chiller` | waste_heat | 50 to 55 | 60 to 75 | cooling_degree | chilled water | 8 to 9 | high | literature |
| `absorption_chiller` | waste_heat | 65 to 70 | 80 to 95 | cooling_degree | chilled water | 9 | medium | estimate |
| `med_desalination` | water | 55 to 60 | 65 to 75 | water_stress | fresh water | 7 to 9 | high | literature |
| `membrane_distillation` | water | 45 to 50 | 60 to 80 | water_stress | fresh water | 5 to 7 | medium | literature |
| `dac_solid_sorbent` | waste_heat | 75 to 80 | 85 to 110 | constant | CO2 captured | 6 to 7 | low | estimate |
| `orc_power` | waste_heat | 70 to 80 | 90 to 120 | constant | electricity | 6 to 8 | low | estimate |
| `heat_pump_booster` | enabler | 15 to 20 | 30 to 60 | constant | lifted heat | 7 to 9 | medium | literature |
| `flexible_compute` | stranded_power | n/a | n/a | price_volatility | electricity cost and CO2 avoided | 7 to 9 | medium | estimate |
| `battery_arbitrage` | stranded_power | n/a | n/a | price_volatility | arbitrage revenue | 9 | medium | unverified |
| `dry_cooling_free_cooling` | water | n/a | n/a | constant | water and chiller electricity saved | 9 | high | estimate |
| `reclaimed_water_cooling` | water | n/a | n/a | water_stress | potable water saved | 9 | high | unverified |

Full parameters per entry (heat demand per unit of output, ambient ranges, water need, seasonality, capex, opex, Israel note, sources) are in the YAML.

## Example screening (synthetic site summaries)

The climate numbers below are rough synthetic values for illustration, not database output.

**Tel Aviv-like climate, Vera Rubin (return 55 C), coastal**

| Rank | Solution | Score | Temperature | Demand | Heat pump |
|---|---|---|---|---|---|
| 1 | `flexible_compute` | 1.00 | 1.00 | 1.00 | no |
| 2 | `battery_arbitrage` | 1.00 | 1.00 | 1.00 | no |
| 3 | `low_temp_drying` | 0.82 | 1.00 | 0.60 | no |
| 4 | `dry_cooling_free_cooling` | 0.82 | 1.00 | 0.60 | no |
| 5 | `swro_feed_preheat` | 0.76 | 1.00 | 0.60 | no |
| 6 | `adsorption_chiller` | 0.75 | 0.75 | 1.00 | no |

**Tel Aviv-like climate, air cooled, coastal**

| Rank | Solution | Score | Temperature | Demand | Heat pump |
|---|---|---|---|---|---|
| 1 | `flexible_compute` | 1.00 | 1.00 | 1.00 | no |
| 2 | `battery_arbitrage` | 1.00 | 1.00 | 1.00 | no |
| 3 | `dry_cooling_free_cooling` | 0.82 | 1.00 | 0.60 | no |
| 4 | `swro_feed_preheat` | 0.54 | 0.70 | 0.60 | no |
| 5 | `aquaculture_ras` | 0.31 | 0.70 | 0.10 | no |
| 6 | `pool_heating` | 0.31 | 0.70 | 0.10 | no |

**Stockholm-like climate, Vera Rubin (return 55 C)**

| Rank | Solution | Score | Temperature | Demand | Heat pump |
|---|---|---|---|---|---|
| 1 | `aquaculture_ras` | 1.00 | 1.00 | 1.00 | no |
| 2 | `pool_heating` | 1.00 | 1.00 | 1.00 | no |
| 3 | `greenhouse_heating` | 1.00 | 1.00 | 1.00 | no |
| 4 | `anaerobic_digestion` | 1.00 | 1.00 | 1.00 | no |
| 5 | `district_heating_5gdh` | 1.00 | 1.00 | 1.00 | no |
| 6 | `flexible_compute` | 1.00 | 1.00 | 1.00 | no |

## Key finding on chip generations

The assumption that Blackwell needs much colder water than Vera Rubin does not hold for the NVIDIA reference designs. At CES 2026 Jensen Huang said Vera Rubin uses the same 45 C facility water as Grace Blackwell ([Facilities Dive, 2026-01-09](https://www.facilitiesdive.com/news/no-chillers-needed-for-vera-rubin-server-racks-nvidia-ceo/809216/)). The difference is the liquid share: Vera Rubin is 100 percent liquid cooled, while Blackwell racks still have air cooled parts. NVIDIA states coolant entering at 45 C leaves the chip at roughly 55 C ([NVIDIA blog](https://blogs.nvidia.com/blog/liquid-cooling-ai-factories/)). For heat reuse this means about 55 C is the realistic best case for current AI racks, which is enough for aquaculture, greenhouses, biogas, drying and adsorption chillers, but needs a heat pump for absorption chillers, classic district heating and DAC. Real sites may run colder loops than the reference design, so per site values stay flagged as assumed.

## Confidence and open points

- `confidence: literature` entries rely on the cited review or vendor source. Most source links were not opened in this session (`checked_in_session: false` in the YAML); only the two NVIDIA cooling sources were read.
- `confidence: unverified` entries (pool heating, SWRO feed preheating, microalgae, domestic hot water, battery arbitrage, reclaimed water) and every field in `unverified_fields` must be checked before they appear in a result.
- `WATER_STRESS_DEFAULT` in `screening.py` is a placeholder; replace with WRI Aqueduct values.
- Market prices (fish, vegetables, water, carbon credits) are deliberately not included. They are added later only for shortlisted solutions.
