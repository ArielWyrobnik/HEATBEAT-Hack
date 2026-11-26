# Heat source data per data center

Adds what each site's waste heat looks like: how much (IT load in MW), at what temperature (coolant
supply and return), and in which medium (liquid loop or exhaust air). This decides which reuse
options can work at all: a 55 C warm-water loop can feed a fish farm or a district heating network
almost directly, a 13 C chilled water return needs a heat pump for nearly everything.

Extends the location database (see `docs/DATA.md`). New files only, the existing schema is untouched.

## Files

| Path | What |
|---|---|
| `data_pipeline/cooling_profiles.csv` | Lookup: cooling type and chip generation to facility water temperatures, liquid heat share, exhaust air temperature, rack kW |
| `data_pipeline/site_profiles.csv` | One row per `site_id` from `sites.csv`: IT load range, PUE, chip family, cooling profile, evidence, confidence |
| `data_pipeline/heat_sources.csv` | Citations for both files |
| `heatbeat_data/heat_profiles.py` | Joins the three and derives the heat streams |

## Quick start

```python
import heatbeat_data as hd

hp = hd.site_heat_profiles()                  # DataFrame, one row per site_id
hd.get_site("us-tn-memphis-xai").heat_profile()   # one row as a dict (needs the built DB for get_site)
hd.heat_profile("us-tn-memphis-xai")          # same, without the DB
hd.cooling_profiles()                         # the lookup table
hd.heat_sources()                             # citations
```

## Columns of `site_heat_profiles()`

| Column | Meaning |
|---|---|
| `scope` | `campus`, `building`, `cluster_representative` (one typical large facility in that cluster, not the whole market), `hypothetical` |
| `chip_family` | `cpu_legacy`, `nvidia_hopper`, `nvidia_blackwell`, `nvidia_blackwell_ultra`, `nvidia_vera_rubin`, `google_tpu`, `other_accelerator`, `mixed` |
| `cooling_type` | `air_chilled`, `air_economizer`, `rear_door`, `dlc_cold`, `dlc_warm`, `dlc_hot`, `immersion` |
| `it_load_mw_low`, `it_load_mw`, `it_load_mw_high` | IT power range, MW. Use the range in sensitivity runs |
| `facility_power_mw` | Reported where available, else `it_load_mw * pue_assumed` |
| `facility_supply_temp_c` (`_min`, `_max`) | Water going to the IT side (CDU or CRAH). Empty for outside-air rooms |
| `facility_return_temp_c` (`_min`, `_max`) | Warm water coming back: the temperature reusable liquid heat comes at |
| `liquid_heat_share` | Share (0..1) of IT heat captured into liquid at rack level. Site value overrides the profile default |
| `exhaust_air_temp_c` | Hot aisle / exhaust air temperature for the air-side heat |
| `recoverable_heat_mw_liquid` | `it_load_mw * liquid_heat_share` |
| `recoverable_heat_mw_air` | `it_load_mw * (1 - liquid_heat_share)` |
| `evidence` | `reported`, `derived` (from reported figures), `estimated` (team assumption) |
| `confidence` | `high`, `medium`, `low`: the weaker of site and profile confidence |
| `is_assumed` | True if any figure in the row is an estimate (currently every row) |

## Cooling profiles (typical values, ranges in the CSV)

| Profile | Typical chips | Supply C | Return C | Liquid share | Key source |
|---|---|---|---|---|---|
| `air_chilled_legacy` | CPU, older colo | 7 (6 to 10) | 13 (11 to 16) | 0 | DCD, Schneider, SemiAnalysis |
| `air_chilled_elevated` | mixed, modern colo | 18 (15 to 20) | 26 (22 to 30) | 0 | Schneider, DCD |
| `air_economizer` | hyperscale CPU | none | none, exhaust air about 32 | 0 | DOE, Meta Odense |
| `rear_door` | air-cooled Hopper | 18 (15 to 24) | 27 (22 to 32) | 0.9 | SemiAnalysis (kW only), temps assumed |
| `dlc_cold` | Hopper H100/H200 | 30 (25 to 32) | 38 (33 to 42) | 0.75 | DCD, Lockwood (Colossus) |
| `dlc_warm` | Blackwell GB200/GB300, B200/B300 | 32 (25 to 40) | 42 (35 to 50) | 0.9 | Lenovo, LiquidStack via Compass, DCD, QCT via GPUSmith |
| `dlc_hot` | Vera Rubin | 45 (40 to 45) | 55 (50 to 60) | 0.95 | NVIDIA blog June 2026, Compass, CoolIT |
| `tpu_dlc` | Google TPU | as `dlc_warm` | as `dlc_warm` | 0.9 | Google (liquid confirmed, temps not public) |
| `immersion_1p` | other | 35 | 45 | 1.0 | none yet, pure assumption |

What the sources actually say (quotes in `heat_sources.csv`):

- NVIDIA (June 2026): Rubin coolant "up to 45 degrees Celsius", entering at 45 C it "exits at roughly 55 degrees", and Rubin is the first generation with "100% liquid cooling".
- LiquidStack (via Compass, Feb 2026): "Blackwell was using lead-in water temperatures of up to 40 degrees Celsius". DCX: some GB200 deployments were "built with 44°C in mind".
- Lenovo (GB200 NVL72): "about 10% to air and 90% to liquid", 135 kW TDP per rack.
- DCD: facility water for DLC "converging around 32°C"; 700 W chips may need water "as low as 80°F (27°C)".
- ASHRAE TC 9.9 classes W17, W27, W32, W40, W45, W+ give the upper limit of facility supply water (Upsite).

So Ariel's rule of thumb holds: Vera Rubin runs at 45 C in and about 55 C out; Blackwell is specified up to
40 to 45 C but typically runs nearer 32 C in and about 42 C out; Hopper is colder again, and air-cooled
rooms only offer 13 to 26 C water or about 32 C air.

## Caveats (read before presenting numbers)

1. **Almost all site figures are estimates.** Only four sites have a medium-confidence basis:
   Stargate Abilene (Epoch AI IT estimate 824 MW, chips B200/B300), Microsoft Fairwater (GB200 and closed-loop
   liquid confirmed by Microsoft; 450 MW is an outside inference), xAI Colossus (H100/H200, cold plates plus rear
   doors confirmed; 150 MW grid supply reported) and Meta Odense (existing heat recovery, about 45 MW heat). Everything
   else is a team assumption by site type and region.
2. **Return temperatures are mostly derived**, from supply plus a typical delta T (5 to 6 C for legacy chilled
   water, about 10 C for elevated chilled water and DLC). Only Rubin has a vendor outlet figure (about 55 C at the chip).
3. **Vendor figures are maximums**, not what operators run. Real Blackwell sites may run colder than the spec allows.
4. **Hyperscale campuses are mixed.** Google sites are modelled as 30 to 40 % TPU liquid and the rest air; Meta and
   Microsoft cloud campuses as air. The real split is not public.
5. `cluster_representative` rows describe one typical facility, not the whole market. Northern Virginia alone
   is about 4,900 MW (JLL, Q1 2025), which is far more than any single row.
6. PUE values are assumptions by cooling type and climate, not reported figures.

## Next steps

- Replace estimates with operator disclosures (sustainability reports, permit filings, utility interconnection
  requests) for the sites the team presents.
- Add NVIDIA reference design return temperatures for GB200/GB300 once a primary source is found.
