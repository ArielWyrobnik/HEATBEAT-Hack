# Ecology and geology scores per data center

Three inputs of the team Excel model (`Hack_data.xlsx`, sheet `1_Site_Inputs_Schema`) cannot be read off a
weather or price feed. This module derives them per site from public map services with a fixed, documented
rule, so the ranking can be reproduced and argued about:

| Excel input | Column | Range | Used in the Excel model |
|---|---|---|---|
| 21 `geo_storage_score` | `geo_storage_score` | int 1 to 5 | KO gate of BTES/ATES storage (needs >= 3) and the climate/geo pillar |
| 30 `eco_sens_index` | `eco_sens_index` | int 1 to 5 | `Eco_Local` = base(mit_tier) minus 0.45 per point of sensitivity above 1 |
| 31 `mit_tier` | `mit_tier` | low / med / high | `Eco_Local` base: high 5, med 3.5, low 2 |

All three are **screening scores, not a permitting or geotechnical assessment**. They tell the ranking where
an option is likely to face ecological or subsurface constraints. Every threshold below is a team choice and
is flagged as such.

## Files

| Path | What |
|---|---|
| `data_pipeline/site_ecology.csv` | One row per `site_id`: the three scores, the reason for each (`*_basis`), sources, confidence, and the raw features behind them |
| `data_pipeline/ecology/raw_site_features.csv` | Raw features as fetched (counts, areas, lithology strings, aquifer codes) |
| `data_pipeline/ecology/fetch_features.py` | Fetches the raw features. Runs in GitHub Actions |
| `data_pipeline/ecology/score.py` | Turns raw features into scores. Pure Python, runs anywhere |
| `heatbeat_data/site_ecology_data.py` | Accessor |
| `.github/workflows/build-ecology.yml` | Runs fetch and score, commits both CSVs |

## Quick start

```python
import heatbeat_data as hd

hd.site_ecology()                                  # DataFrame, one row per site_id
hd.ecology("us-va-ashburn-equinix")                # one row as a dict, with reasons and raw features
hd.excel_ecology_inputs("us-va-ashburn-equinix")   # {"eco_sens_index": .., "geo_storage_score": .., "mit_tier": ..}
hd.get_site("us-va-ashburn-equinix").ecology()     # same as hd.ecology, from a Site object
```

To refresh: run the workflow **Build site ecology and geology** (Actions tab, Run workflow), or push a change
to `data_pipeline/ecology/*.py`. To change only a rule, edit `score.py` and run
`python -m data_pipeline.ecology.score` locally: no network needed.

## Sources

| id | Dataset | Access | Coverage | Licence |
|---|---|---|---|---|
| `padus` | USGS GAP, Protected Areas Database of the US (PAD-US 4), layer "Protection Status by GAP Status Code" | ArcGIS feature service `services.arcgis.com/v01gqwM5QqNysAAi/.../PADUS_Protection_Status_by_GAP_Status_Code` | US | Public domain |
| `nwi` | USFWS National Wetlands Inventory, wetland polygons (Cowardin classes) | `fwspublicservices.wim.usgs.gov/wetlandsmapservice/rest/services/Wetlands/MapServer/0` | US | Public domain |
| `usfws_critical_habitat` | USFWS Final Critical Habitat for ESA listed species | `services.arcgis.com/QVENGdaPbd4LUkLV/.../USFWS_Critical_Habitat/FeatureServer/0` | US | Public domain |
| `usgs_principal_aquifers` | USGS Principal Aquifers of the 48 conterminous US (2003), via Esri Living Atlas "USA Aquifers" | `services.arcgis.com/P3ePLMYs2RVChkJx/.../USA_Aquifers_Feature_Layer_view` | US | Public domain |
| `macrostrat` | Macrostrat geologic map, surface map unit at the point (most detailed scale available) | `macrostrat.org/api/v2/geologic_units/map` | Global, detail varies | CC-BY 4.0 |
| `natural_earth_coast` | Natural Earth 1:10m coastline, distance to nearest vertex | GitHub mirror `nvkelso/natural-earth-vector` | Global (sea only, Great Lakes not included) | Public domain |
| `osm_overpass` | OpenStreetMap protected areas (`protect_class` 1 to 4), nature reserves, national parks, `natural=wetland` | Overpass API | Non-US sites | ODbL |

The cloud sandbox cannot reach these hosts, so `fetch_features.py` runs in GitHub Actions like the rest of the
pipeline. Natural Earth is the exception and can be fetched anywhere.

## Rule 1: `eco_sens_index` (1 to 5)

Excel definition: 1 = industrialized port or urban zone, 5 = protected coral reef, low-salinity estuary or
wetland. We count sensitive receptors around the site point and add points:

| Component | Points | Test |
|---|---|---|
| P, protected land | 2 | PAD-US GAP status 1 or 2 area within 1 km (non-US: OSM protected area class 1 to 4, nature reserve or national park) |
| | 1 | same, within 5 km |
| H, critical habitat (US only) | 2 | ESA final critical habitat polygon within 1 km |
| | 1 | within 5 km |
| W, wetlands | 1 | vegetated NWI wetland (freshwater emergent, forested/shrub, estuarine and marine wetland) of at least 5 ha within 1 km. Each polygon counts with its full area, capped at the 314 ha of the 1 km circle |
| A, estuarine or marine water | 1 | NWI estuarine polygon within 5 km, or sea coast within 5 km |

`eco_sens_index = 1 + min(4, P + H + W + A)`.

Why these: GAP 1 and 2 are the PAD-US classes "managed for biodiversity" (USGS GAP definitions); critical
habitat triggers ESA section 7 consultation for any federal permit; wetlands and estuaries are the receptors
of warm or saline discharge (Clean Water Act section 404 and the thermal limits of section 316(a)). The 1 km
and 5 km radii and the 5 ha threshold are **team choices** (not from a standard).

Known limits:
- Site coordinates are often campus or city approximations (`coord_precision` in `sites.csv`). A 1 km test on
  a city point can miss or wrongly hit a feature.
- PAD-US GAP 3 lands (multiple use, for example most BLM land) are not counted. The count of all PAD-US
  features is kept in `raw_site_features.csv` as `padus_any_n_*`.
- Outside the US, OSM coverage of protected areas and wetlands is uneven, and OSM gives no wetland area in
  this query, so any mapped wetland within 1 km counts as W. Hence `eco_confidence` is at most `medium` there.

## Rule 2: `geo_storage_score` (1 to 5)

Excel definition: 1 = fast-flowing groundwater or unstable soil, 5 = high thermal conductivity granite or
bedrock, or a confined low-flow aquifer. It gates borehole (BTES) and aquifer (ATES) thermal storage.

Step 1, surface lithology class from Macrostrat (keyword match on the map unit's `lith` and name; the
keyword that appears first wins, since Macrostrat lists the dominant lithology first):

| Class | Base score | Keywords (examples) | Reasoning |
|---|---|---|---|
| crystalline | 5 | granite, gneiss, schist, quartzite, metamorphic | High thermal conductivity, low permeability: ideal BTES |
| clastic_rock | 4 | sandstone, siltstone, shale, mudstone | Moderate conductivity, slow flow: good BTES, sandstone layers can host ATES |
| volcanic | 3 | basalt, tuff, volcanic | Often fractured, flow can be fast |
| unconsolidated | 3 | alluvium, sand, gravel, clay, till, loess | Workable for ATES or BTES, depends on flow |
| carbonate | 2 | limestone, dolomite, chalk, marl | Karst risk: fast and unpredictable groundwater flow |
| organic, evaporite | 1 | peat, marsh, salt, gypsum | Unstable or soluble ground |

If the most detailed unit is too generic (for example just "sedimentary"), coarser map scales are tried.

Step 2, adjustments from the USGS principal aquifer under the site (US only, `ROCK_TYPE` codes of the dataset):

| Condition | Effect |
|---|---|
| Carbonate (500) or sandstone and carbonate (400) aquifer | cap at 2 (karst) |
| Unconsolidated sand and gravel aquifer (100) under unconsolidated surface | set to 2 (high flow would carry stored heat away) |
| Semiconsolidated sand aquifer (200), typical confined coastal plain aquifer | at least 4 (ATES) |
| Igneous and metamorphic aquifer (600) under a non-crystalline surface | at least 4 (bedrock below thin cover) |

Step 3: unconsolidated or organic surface within 1 km of the sea: minus 1 (saline intrusion, soft fill).

If no lithology is returned the score is 3 (neutral), `geo_confidence` = `low`, and the basis says ASSUMED.

Known limits: surface geology is not the geology at 50 to 200 m borehole depth, depth to bedrock is not
known, and groundwater velocity is inferred from aquifer type, not measured. Treat it as a first screen;
a real project needs a thermal response test. `geo_confidence` is `medium` for US sites with an aquifer
record, `low` otherwise.

## Rule 3: `mit_tier` default

`mit_tier` describes the design of the solution (zero liquid discharge, closed recirculating systems and dry
coolers = `high`; standard treatment = `med`; open outfall = `low`), so it is not a property of the site.
The CSV gives the tier a permitting agency would most likely expect, as a default the solution models can
override:

| Condition | Default |
|---|---|
| `eco_sens_index >= 4` | `high`: sensitive receptors nearby, closed loop or ZLD expected |
| otherwise | `med`: standard treated discharge under an NPDES-type permit. `low` is never a default, since new hyperscale sites rarely get an open outfall |

`mit_tier_is_assumed` is 1 for every row. **This is a team assumption, not data.**

## Confidence column

| Column | high | medium | low |
|---|---|---|---|
| `eco_confidence` | US site, all four sources answered | US site with one source failed, or non-US site with OSM | non-US site where OSM failed |

Then `eco_confidence` drops one step (high to medium, medium to low) when the site coordinate is only a city
approximation (`coord_precision = city_approx` in `sites.csv`, 47 of 59 sites), because a 1 km test around a
city centroid says little about the actual plot.
| `geo_confidence` | (not used) | US site with an aquifer record | everything else |

`sources_failed` lists any source that did not answer in the last run.
