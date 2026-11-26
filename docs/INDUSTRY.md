# Site industry layers: power plants, CO2, biomass, cold chain

`data_pipeline/site_industry.csv` holds, for each of the 40 US sites in `data_pipeline/sites.csv`,
the neighbour inputs of the team Excel model (sheet `1_Site_Inputs_Schema`). The first columns use the
Excel JSON keys unchanged:

| Key | Excel input | Meaning here | KO threshold in Excel |
|---|---|---|---|
| `d_pp_m` | 16 | Routing distance to the nearest steam cycle power / CHP plant whose estimated sink `q_fw_mw` is at least 2 MW | <= 1,500 m (Boiler Feedwater Preheat) |
| `q_fw_mw` | 17 | Estimated low temperature feedwater heat sink of that plant (condensate 30 C to 60 C), MW_th, average over the year | >= 2.0 MW |
| `d_co2_m` | 15 | Routing distance to CO2 geologic storage, CO2 injection (EOR) or a CO2 supplier / capture hub | <= 50,000 m (Carbon Capture / DAC) |
| `d_bio_m` | 14 | Routing distance to biomass or organic waste supply | <= 25,000 m (Biogas, Biomass Processing) |
| `d_market_m` | 27 | Routing distance to cold storage, seafood processing or a produce / wholesale food hub | none (used in economics) |

Use it from Python:

```python
import heatbeat_data as hd
hd.excel_industry_inputs("us-tn-memphis-xai")  # {'d_pp_m': ..., 'q_fw_mw': ..., ...}
hd.site_industry("us-tn-memphis-xai")    # full row incl. names, sources, confidence
hd.site_industry()                       # DataFrame for all US sites
```

Non-US sites are not covered yet (`KeyError`).

## Method

* **Distances.** Great circle distance from the site coordinate to the nearest point of a layer,
  multiplied by a circuity factor of 1.2 to approximate road or pipe routing (US average road circuity
  about 1.2: Ballou, Rahardja and Sakai 2002, *Transportation Research Part A* 36(9):843-848; using it
  for pipes is an assumption). The straight line value is kept in `d_*_straight_m`.
* **Site coordinates are approximate.** 47 of 59 sites are `city_approx` (see `docs/DATA.md`). For short
  distances this matters a lot: a 1.5 km gate cannot be judged from a city centroid. The confidence is
  therefore lowered one step when a `city_approx` site is less than 10 km from the feature (or a
  `campus_approx` site less than 2 km). Treat `d_pp_m` below about 10 km as "worth a closer look", not as
  a verified pipe length.
* **Confidence columns** (`pp_confidence`, `co2_confidence`, `bio_confidence`, `market_confidence`):
  `medium` = real registry point, distance computed by us; `low` = fallback layer, nothing found, or short
  distance from an approximate site coordinate. Nothing is `high` because no distance was checked by hand.

### Power plants and `q_fw_mw` (engineering estimate, flagged)

Source: EIA-860 and EIA-923, report year 2025 (final), read from the Catalyst Cooperative PUDL stable
release (`out_eia__yearly_generators.parquet`, https://s3.us-west-2.amazonaws.com/pudl.catalyst.coop/stable/),
which republishes EIA data with plant coordinates and per generator capacity factors.
Layer: `data_pipeline/industry/eia_steam_plants.csv` (existing generators with prime mover ST, CA or CS).

`q_fw_mw` is not reported by anyone. It is estimated per plant:

```
q_fw_mw = sum over steam generators of  capacity_mw * steam_share * k * capacity_factor
k = 0.106 MW_th per MWe (fossil, biomass, CCGT steam part), 0.20 (nuclear)
steam_share = 1/3 for single shaft combined cycle (CS), else 1
```

`k` comes from a condensate flow of about 0.85 kg/s per MWe for fossil steam cycles (about 3 t/h per MWe,
textbook rule of thumb) and about 1.6 kg/s per MWe for light water nuclear (saturated steam at about 33%
efficiency), times 4.18 kJ/kgK * 30 K = 125 kJ/kg for heating condensate from 30 C to 60 C. These are
unverified rules of thumb, accurate to maybe +-30%. `q_fw_full_load_mw` gives the value at full load.
If EIA-923 has no capacity factor for a generator, 0.5 is used (`cf_missing` in the layer).

`d_pp_any_m` / `pp_any_name` give the nearest steam plant of any size, which can be closer but too small.

Caveat: real plants already preheat condensate with LP extraction steam; data center heat at 45 to 55 C can
only replace the first LP heater stage. The Excel model, not this table, decides how much of `q_fw_mw` is
usable.

### CO2 (`d_co2_m`)

Sources, merged:

1. EPA Greenhouse Gas Reporting Program, latest data summary spreadsheets
   (https://www.epa.gov/ghgreporting/data-sets): facilities reporting subpart RR (geologic sequestration),
   subpart UU (CO2 injection, mostly enhanced oil recovery) and subpart PP (CO2 suppliers: capture,
   production, import). Layer `ghgrp_co2.csv`, fetched by GitHub Actions.
2. EIA-860 2025 generators with carbon capture equipment (5 plants). Layer `eia_ccs_plants.csv`.

Not included: CO2 pipeline routes (PHMSA NPMS geometry is restricted to operators and officials) and
DOE/NETL NATCARB saline storage polygons (no reachable API). A site far from any point may still sit over a
storage formation, so a large `d_co2_m` is conservative.

### Biomass and organic waste (`d_bio_m`)

Nearest of:

1. EIA-860 2025 plants burning wood solids or liquids, pulp mill black liquor, agricultural byproducts,
   other biomass solids, liquids or gas (digesters). These sit where forestry or crop residue is collected.
2. EPA AgSTAR Livestock Anaerobic Digester Database (manure): code is in place (`--stage agstar`) but not
   used yet, because the published workbook (2020 edition) has no coordinates, only city and county.
3. EPA GHGRP facilities with primary NAICS 311 (large food manufacturing plants: meat, dairy, sugar, corn
   milling). Layer `ghgrp_food.csv`.

`bio_kind` names the type found. Landfills (landfill gas plants) are kept apart in `d_landfill_m` because
the Excel definition lists manure, food processing, crop and forestry residue, not municipal waste.
Crop residue spread over farmland (for example in Iowa) is not a point source and is under-represented;
NREL county level biomass data would fill this but was not reachable.

### Cold chain and food offtake (`d_market_m`)

1. OpenStreetMap via the Overpass API (ODbL), 60 km around each site: cold storage and refrigerated
   warehouses (tags and names such as Lineage, Americold), seafood or fish processing, produce terminal
   markets and food wholesale. Layer `osm_market.csv`, fetched by GitHub Actions.
2. EPA GHGRP NAICS 3117 (seafood processing).

If none of these is within 60 km, OSM food processing sites are used (`low`). If there is nothing at all,
`d_market_m` is set to 72,000 m (60 km times circuity) as a lower bound and flagged `low`. OSM coverage of
warehouses is uneven, so a large value can also mean "not mapped".

### Industrial zoning proxy (`ind_zoning`, extra)

The Excel input 18 `ind_zoning` needs a municipal zoning map, which has no national API. As a proxy,
`ind_zoning = 1` if OpenStreetMap has any `landuse=industrial` area within 3 km of the site coordinate
(`n_industrial_landuse_3km` gives the count). Always `low` confidence and `assumption` status: land use
is not zoning, and most site coordinates are city level.

## Hand over to the ranking engine

`data_pipeline/site_ranking_inputs_industry.csv` repeats the Excel keys in long format
(`site_id,key,value,status,source,note`), which `heatbeat_ranking` reads automatically.
`status` is `data` for distances computed from registries and `assumption` for `q_fw_mw`, `ind_zoning`
and market lower bounds.

## Rebuilding

```
python -m data_pipeline.fetch_industry --stage eia        # works anywhere with access to AWS S3
python -m data_pipeline.fetch_industry --stage assemble   # offline, from the committed layers
```

The GHGRP, AgSTAR and OSM stages need epa.gov and overpass-api.de, which the cloud sandbox cannot reach.
Workflow `.github/workflows/build-industry.yml` runs all stages on a GitHub runner and commits the layers
and `site_industry.csv`. Run it from the Actions tab ("Build site industry layers", Run workflow).
