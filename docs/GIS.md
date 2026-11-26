# HEATBEAT site GIS inputs

Distances, terrain and land figures for every site in `data_pipeline/sites.csv`, computed from open
datasets. They fill the Geography, Infrastructure, Land Use and Civil inputs of the team Excel model
(sheet `1_Site_Inputs_Schema`), with the same JSON keys and SI units.

| Path | What |
|---|---|
| `data_pipeline/site_gis.csv` | One row per `site_id`: the 11 Excel keys, a `<key>_source` and `<key>_confidence` column for each, plus helper columns |
| `data_pipeline/site_ranking_inputs_gis.csv` | Same values for US sites in long format (`site_id,key,value,status,source,note`) for `heatbeat_ranking` |
| `data_pipeline/district_heating_systems.csv` | Curated list of known district heating (DH) networks near the sites, with approximate service areas |
| `data_pipeline/fetch_gis.py` | The build script |
| `heatbeat_data/site_gis.py` | Accessor |

```python
import heatbeat_data as hd
hd.site_gis()                                  # DataFrame, all sites
hd.gis_inputs("us-va-ashburn-equinix")         # dict with only the 11 Excel keys
hd.get_site("us-va-ashburn-equinix").gis()     # full row incl. sources and helper columns
```

Rebuild (about 30 s per site on first run, downloads are cached in `data/cache/gis/`):

```bash
pip install -r requirements-gis.txt
python -m data_pipeline.fetch_gis                 # all sites
python -m data_pipeline.fetch_gis --sites il-haifa,us-az-mesa
```

No API keys are needed. All inputs are read from public cloud buckets.

## Data sources

| Dataset | Used for | Link |
|---|---|---|
| AWS Terrain Tiles (Terrarium, zoom 13, about 15 to 19 m pixels; USGS 3DEP inside the US, SRTM and others elsewhere) | elevation, slope, `dz_m` | https://registry.opendata.aws/terrain-tiles/ |
| ESA WorldCover 10 m 2021 v200 | open land, cropland, land cover shares | https://registry.opendata.aws/esa-worldcover-vito/ |
| Overture Maps, release 2026-11-18.0 (water, land use, buildings, infrastructure; mostly OpenStreetMap) | water bodies, ocean, industrial land use, building floor area, heat pipelines | https://docs.overturemaps.org/ |
| Natural Earth 10 m coastline | coast fallback when no OSM ocean polygon is within 60 km | https://www.naturalearthdata.com/ |
| NOAA GHCN-Daily (nearest station with TMAX and TMIN, 2015 to 2024) | heating degree days for heat demand | https://registry.opendata.aws/noaa-ghcn/ |
| Persson, U. and Werner, S. (2011): Heat distribution and the future competitiveness of district heating. Applied Energy 88(3), 568 to 576 | linear heat density formula | https://doi.org/10.1016/j.apenergy.2010.09.020 |
| Ballou, R. H., Rahardja, H., Sakai, N. (2002): Selected country circuity factors for road travel distance estimation. Transportation Research Part A 36(9), 843 to 848 | routing factor 1.2 (US roads) | https://doi.org/10.1016/S0965-8564(01)00044-1 |
| Operator web pages, listed per row in `district_heating_systems.csv` | known DH networks | see CSV |

## Method per field

All distances are measured from the site point in `sites.csv` in a local azimuthal equidistant
projection. Pipe routes are longer than straight lines, so the Excel distance fields are
`straight line x 1.2` (Ballou et al. 2002, US road circuity). The straight-line values are kept in
`*_line_m` columns.

| Key | Method |
|---|---|
| `d_coast_m` | Nearest Overture `ocean` polygon (from the OSM coastline). If none within 60 km: Natural Earth 10 m coastline. Brackish groundwater wellfields (also allowed by the Excel definition) are **not** covered; a USGS brackish aquifer layer could be added later. |
| `d_water_m` | Nearest clean water intake from Overture water: mapped river lines (`class=river`, streams and ditches excluded), lakes, reservoirs and river polygons of at least 5 ha, not intermittent, plus sea water. `d_water_kind` says whether the nearest one is fresh or marine, `d_freshwater_line_m` gives fresh water only. |
| `dz_m` | Site ground elevation above sea level, that is the pumping head from a seawater intake at 0 m (the Excel desalination gate uses `dz_m` with `d_coast_m`). `dz_water_m` is the head from the `d_water_m` intake instead. |
| `slope_deg` | Mean slope within 1 km, from the DEM (central differences). |
| `flat_land_m2` | Largest contiguous patch within 2 km of open land (WorldCover shrub, grassland, cropland, bare) with slope up to 5 degrees. `flat_land_total_m2` is the sum of all such land in the 2 km disk. Says nothing about ownership or price. |
| `agri_land_m2` | Same, cropland only. Pasture is classed as grassland by WorldCover and is not counted, so the US value is conservative. |
| `campus_area_m2` | **Synthetic.** `it_load_mw` from `site_profiles.csv` x 2,500 m2 per MW (team assumption for building, yard and road area). No national data center footprint dataset was available. |
| `has_existing_dh` | 1 if the edge of a curated DH network (centre plus approximate service radius) or an OSM pipeline with `substance=heat/hot_water/steam` is within 3,000 m (the Excel greenfield DH gate). |
| `d_dh_m` | Minimum of (a) the distance to an existing DH network as above and (b) the distance to the nearest 250 m cell whose modelled linear heat density reaches 1.5 MWh/(m yr) (Excel greenfield threshold). `d_dh_m_is_lower_bound = 1` when neither exists within 6 km (or 50 km for networks), then the value is 6,000 m x 1.2. |
| `rho_heat_mwh_m` | Persson and Werner (2011): `Q/L = e * q * w`, effective width `w = 61.8 * e^-0.15` m, plot ratio `e` = floor area / land area. Floor area from Overture building footprints x floors (from `num_floors`, else `height / 3.5 m`, else 1), in 250 m cells smoothed over 750 m. Sheds, garages, industrial buildings, warehouses and unclassified footprints above 5,000 m2 (data halls) are left out because they have little space heating demand. Value is the mean over dense cells within 1 km of the `d_dh_m` target, or the maximum within 6 km if none is dense. |
| `ind_zoning` | Proxy: 1 if an OSM `landuse=industrial`, `construction` or `brownfield` area lies within 1 km (300 m for building-precise sites). There is no national zoning dataset; this is not a legal zoning check. |

### Heat demand per floor area (assumption)

`q = 0.024 kWh/(m2 K d) x HDD18 + 10 kWh/m2` (space heating plus hot water, useful heat per m2 of
floor area and year). HDD18 is the mean 2015 to 2024 heating degree days (base 18 C) at the nearest
GHCN station (`hdd18_station`, distance in `hdd18_station_km`). The coefficient is a **team
assumption** of the right order for the existing US building stock (about 55 to 75 kWh/m2 at 2,300 to
2,800 HDD) and was not calibrated against CBECS or RECS. It makes linear heat density scale with
climate, so warm sites (Arizona, Texas, Israel) get a low `rho_heat_mwh_m`, which matches the low
heating demand there.

## Confidence

* `high`: only used where the site coordinates are building-precise and the method is direct.
* `medium`: direct measurement from a good dataset, coordinates at campus level.
* `low`: coordinates only at city level (`coord_precision = city_approx`, most sites), or the
  method is a proxy (zoning, flat land availability, DH, heat density).
* `synthetic`: not measured at all (`campus_area_m2`).

Most sites have city-level coordinates, so local land figures (slope, flat land, cropland, zoning)
describe the area around the town centre, not the actual parcel. Updating `lat`/`lon` in `sites.csv`
and re-running the script fixes that.

## Known caveats

* OSM completeness varies: missing ponds, rivers or industrial areas lower the quality of
  `d_water_m` and `ind_zoning`.
* Curated DH networks use an approximate centre and radius per network (team estimates), not real
  pipe maps. Campus systems (universities, hospitals) are mostly missing.
* `has_existing_dh = 0` with a short `d_dh_m` means "dense area, but no network known": the greenfield
  DH option, not the retrofit one.
* Estuaries such as the Hudson are tagged as rivers in OSM, so they count as fresh water although
  they are brackish.
