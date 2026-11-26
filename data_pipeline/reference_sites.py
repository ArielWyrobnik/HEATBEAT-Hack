"""Real heat reuse reference projects used to validate the HEATBEAT models (docs/VALIDATION.md).

One entry per reference site that was not in sites.csv yet. Running this module appends (or refreshes)
the rows of these sites in every per site table, so the normal pipeline (build_db, heatbeat_data,
heatbeat_engineering) treats them like any other site:

    python -m data_pipeline.reference_sites

Tables written: sites.csv, grid_regions.csv (new regions only), site_profiles.csv, heat_sources.csv,
site_gis.csv, site_ecology.csv, and for US sites also site_water.csv, aqueduct_sites.csv,
site_industry.csv and the site_ranking_inputs_*.csv files. It also writes the "already implemented"
facts of all reference projects (new and existing sites) to site_current_setup_refs.csv (long format
shared with the current setup thread, loader heatbeat_data.current_setup).

Where the numbers come from:
- Coordinates, operator, capacity, what is implemented: the cited press and operator pages (SOURCES).
- Weather, hourly prices, retail price, grid CO2: the normal pipeline (build_db) after this runs.
- GIS, ecology, water, industry: the cloud container that built this file could not reach the GIS APIs
  (Overture, DEM, Aqueduct, EIA-860), so these are HAND ESTIMATES from the project descriptions and map
  reading, flagged confidence "low" and source "reference_hand_estimate". Rerun fetch_gis.py,
  ecology/fetch_features.py, fetch_aqueduct.py and fetch_industry.py with internet to replace them.

Sites that already existed and are reused (no new row): nl-amsterdam (Equinix AM3/AM4 Science Park),
fr-paris (Equinix PA10 Saint-Denis), us-va-ashburn-equinix (Vertiv ORC design climate Ashburn),
gb-slough (Civo pilot site undisclosed, representative UK site), us-ia-council-bluffs-google
(representative Midwest grain belt site for grain drying).
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

DP = Path(__file__).resolve().parent
EST = "reference_hand_estimate"
EST_TXT = ("Hand estimate for the reference validation (map reading and project description, not fetched); "
           "rerun the fetch script with internet to replace")

# ---------------------------------------------------------------------------------------------------
# Sources (source_id, title, url, published). Every number below cites one of these.
# ---------------------------------------------------------------------------------------------------
SOURCES = [
    ("nebius_heat", "Nebius: Turning heat into a resource", "https://nebius.com/sustainability/turning-heat-into-a-resource", ""),
    ("nebius_greenfield_fi", "Nebius: Our greenfield data center in Finland", "https://nebius.com/sustainability/our-greenfield-data-center-in-finland", ""),
    ("nebius_75mw_2024", "Nebius to triple capacity at Finland data center to 75 MW", "https://nebius.com/newsroom/nebius-to-triple-capacity-at-finland-data-center-to-75-mw", "2024-10-08"),
    ("gm_hima_2021", "Green Mountain: land based trout farm will use data center waste heat", "https://greenmountain.no/land-based-trout-farm-will-use-data-center-waste-heat/", "2021-06-28"),
    ("waa_hima_2026", "WeAreAquaculture: Green Mountain's data center heat reuse by Hima Seafood is up and running", "https://weareaquaculture.com/news/sustainability/green-mountains-data-center-heat-reuse-by-hima-seafood-is-up-and-running", "2026-02-04"),
    ("gm_heat_value_2026", "Green Mountain: Turning waste heat into value", "https://greenmountain.no/turning-waste-heat-into-value/", "2026-02-04"),
    ("dcd_falun_nordic", "DCD: Sharing warmth the Nordic way (EcoDataCenter Falun)", "https://www.datacenterdynamics.com/en/analysis/sharing-warmth-nordic-way/", "2020"),
    ("ecodc_falun", "EcoDataCenter 1 Falun site page", "https://ecodatacenter.tech/data-center/sweden-falun", ""),
    ("idea_ecodc_2025", "IDEA blog: ULI award winners, EcoDataCenter 1", "https://www.districtenergy.org/blogs/district-energy/2025/10/22/uli-award-winners-ecodatacenter-1-powers-its-serve", "2025-10-22"),
    ("nyserda_su_gdc", "NYSERDA CHP case study: Syracuse University Green Data Center", "https://www.nyserda.ny.gov/-/media/Project/Nyserda/Files/Publications/Case-Studies/On-Site-Power-Application/CHP-sugreendatacenter-cs.pdf", "2015-04"),
    ("amazon_doppler_2017", "Amazon: The super efficient heat source hidden below Amazon's Seattle headquarters", "https://www.aboutamazon.com/news/sustainability/the-super-efficient-heat-source-hidden-below-amazons-seattle-headquarters", "2017-11-16"),
    ("phc_amazon_2018", "PHC Pros: Amazon warms campus with waste heat", "https://www.phcppros.com/articles/7757-amazon-warms-campus-with-waste-heat", "2018-07-01"),
    ("bdc_amazon_2015", "BD+C: Amazon will heat its new Seattle campus with waste heat from next door data centers", "https://www.bdcnetwork.com/amazon-will-heat-its-new-seattle-campus-waste-heat-next-door-data-centers", "2015-11-16"),
    ("dck_pa10_2024", "Data Center Knowledge: Paris 2024, excess data center heat used to warm Olympic swimming pools", "https://www.datacenterknowledge.com/sustainability/paris-2024-excess-data-center-heat-used-to-warm-olympic-swimming-pools", "2024-07-26"),
    ("dcd_pa10_farm", "DCD: Equinix opens urban farm on its PA10 Paris data center", "https://datacenterdynamics.com/en/news/equinix-opens-urban-farm-on-its-pa10-paris-data-center-in-paris", ""),
    ("techzine_pa10_2024", "Techzine: Inside Equinix PA10", "https://www.techzine.eu/blogs/infrastructure/122398/inside-equinix-pa10-paris-datacenter-sets-green-example/", "2024-07-17"),
    ("vertiv_orc_wp", "Vertiv white paper: Experimental lessons of an Organic Rankine Cycle (Tipton, Kremer, Ali; Portuguese edition)", "https://www.vertiv.com/4a6e32/globalassets/documents/white-papers/vertiv-experimental-lessons-of-organic-rankine-wp-pt-latam-web.pdf", ""),
    ("nsf_orc_prototype", "ITHERM paper: ORC as a waste heat recovery system for data center, prototype (NSF PAR 10065782)", "https://par.nsf.gov/biblio/10065782", "2018"),
    ("dcd_civo_orbital_2025", "DCD: Civo partners with Orbital to pilot carbon removal technology at UK data center", "https://datacenterdynamics.com/en/news/civo-partners-with-orbital-to-pilot-carbon-removal-technology-at-uk-data-center", "2025-04"),
    ("semafor_orbital_2025", "Semafor: Data center in UK becomes proving ground for carbon capture technology from Orbital", "https://www.semafor.com/article/04/09/2025/data-center-in-uk-becomes-proving-ground-for-new-carbon-capture-technology-from-startup-orbital", "2025-04-09"),
    ("ioplus_am3_2026", "IO+: Inside the building that powers the internet (Equinix Amsterdam Science Park)", "https://ioplus.nl/en/posts/inside-the-building-that-powers-the-internet-", "2026-05-04"),
    ("baxtel_am_sp", "Baxtel: Equinix Amsterdam Science Park campus", "https://baxtel.com/campus/equinix-amsterdam-science-park-campus", ""),
    ("equinix_diemen_2025", "Equinix newsroom: Equinix and the Municipality of Diemen sign collaboration agreement", "https://newsroom.equinix.com/2025-01-27-Exploring-Sustainable-Heating-Solutions-for-Residents,-Equinix-and-the-Municipality-of-Diemen-Sign-Collaboration-Agreement", "2025-01-27"),
    ("northc_ehv1_factsheet", "NorthC Eindhoven 1 data center factsheet", "https://www.northcdatacenters.com/en/wp-content/uploads/sites/2/2024/02/Eindhoven_1_Data_Center_Factsheet_NorthC_EN.pdf", "2024-02"),
    ("grundfos_northc", "Grundfos case study: NorthC data centers", "https://www.grundfos.com/content/dam/global/page-assets/about-us/cases/documents/cbs-cases-northc-data-centers-gnl.pdf", "2023"),
    ("dcd_northc_ehv2", "DCD: NorthC begins construction of 4.5 MW Eindhoven data center", "https://www.datacenterdynamics.com/en/news/northc-begins-construction-of-45mw-eindhoven-data-center", "2023"),
    ("crusoe_kraken_2020", "Business Wire: Kraken Oil & Gas partners with Crusoe to deploy Digital Flare Mitigation in Montana and North Dakota", "https://www.businesswire.com/news/home/20201007006041/en/", "2020-10-07"),
    ("crusoe_argus_2021", "Crusoe newsroom (Argus Media): Bitcoin cuts oil and gas flaring", "https://www.crusoe.ai/resources/newsroom/bitcoin-cuts-oil-and-gas-flaring", "2021-10-08"),
    ("bioenergy_echelon_2021", "Bioenergy Insight: Echelon Data Centres, Biocore to build biogas plant in Ireland", "https://www.bioenergy-news.com/news/echelon-data-centres-biocore-to-build-biogas-plant-in-ireland", "2021-04-15"),
    ("rte_echelon_2021", "RTE: Biogas facility to be located beside Arklow data centre", "https://www.rte.ie/news/business/2021/0413/1209732-biogas-facility-to-be-located-beside-arklow-data-centre", "2021-04-13"),
    ("dcd_endeavour_trevi", "DCD: Endeavour partners with US desalination firm Trevi", "https://datacenterdynamics.com/en/news/endeavour-partners-with-us-desalination-firm-trevi-to-turn-data-center-waste-heat-into-clean-water", "2026"),
    ("doe_trevi_2022", "DOE EERE success story: Hawaii tests the waters of carbon free desalination", "https://www.energy.gov/cmei/articles/eere-success-story-hawaii-tests-waters-carbon-free-desalination", "2022-09-21"),
]

# ---------------------------------------------------------------------------------------------------
# New grid regions (fallbacks are rough and flagged by the pipeline as estimate_unverified)
# ---------------------------------------------------------------------------------------------------
GRID_REGIONS = [
    dict(grid_region_id="NO", name="Norway", country_iso2="NO", country_iso3="NOR", fallback_retail_usd_mwh=60,
         fallback_co2_kg_mwh=30, notes="fallback values are rough unverified estimates"),
    dict(grid_region_id="US-SPP-ND", name="SPP North (western North Dakota, Basin Electric)", country_iso2="US",
         country_iso3="USA", us_state="ND", iso_rto="SPP", lmp_location="SPPNORTH_HUB", egrid_subregion="MROW",
         notes="SPP North hub as proxy for the Williston Basin; MISO/SPP seam, member utility not verified"),
    dict(grid_region_id="US-NYISO-CENTRL", name="NYISO Zone C (Central, Syracuse)", country_iso2="US",
         country_iso3="USA", us_state="NY", iso_rto="NYISO", lmp_location="CENTRL", egrid_subregion="NYUP"),
    dict(grid_region_id="US-HI", name="Hawaii Island non-market (HELCO)", country_iso2="US", country_iso3="USA",
         us_state="HI", egrid_subregion="HIMS", notes="no organized wholesale market"),
]

# ---------------------------------------------------------------------------------------------------
# New reference sites. gis/eco/water/ind are hand estimates (see module docstring).
# ---------------------------------------------------------------------------------------------------
REFS = [
    dict(site_id="no-rjukan-greenmountain", name="Green Mountain DC2-Telemark (TEL-Rjukan)", operator="Green Mountain",
         city="Rjukan", region="Telemark", country_iso2="NO", lat=59.8770, lon=8.6200, coord_precision="city_approx",
         capacity_mw=None, capacity_note="not published; heat reuse system 1.75 MW phase 1, 8 MW phase 2 (waa_hima_2026)",
         grid_region_id="NO", is_hypothetical=0,
         notes="Reference: fish farm (Hima Seafood RAS trout farm 800 m away, operating since fall 2025). Earlier DC1-Stavanger lobster pilot not found in sources.",
         prof=dict(it_load_mw_low=5, it_load_mw=10, it_load_mw_high=30, pue_assumed=1.2, chip_family="mixed",
                   cooling_profile_id="air_chilled_elevated", confidence="low", is_assumed=1,
                   source_ids="waa_hima_2026;gm_heat_value_2026;team_assumption",
                   notes="IT load not published; 10 MW assumed so that the 1.75 MW (phase 1) to 8 MW (phase 2) heat export fits"),
         gis=dict(d_coast_m=90000, d_water_m=500, dz_m=300, slope_deg=8.0, flat_land_m2=50000, agri_land_m2=0,
                  d_dh_m=3000, has_existing_dh=0, rho_heat_mwh_m=0.5, ind_zoning=1, hdd18=4500),
         eco=dict(eco_sens_index=3, geo_storage_score=5, geo_basis="crystalline bedrock (Telemark gneiss), hand estimate", mit_tier="med")),
    dict(site_id="fi-mantsala-nebius", name="Nebius Mantsala data center", operator="Nebius", city="Mantsala",
         region="Uusimaa", country_iso2="FI", lat=60.6330, lon=25.3170, coord_precision="city_approx",
         capacity_mw=75, capacity_note="75 MW after the announced tripling (nebius_75mw_2024); about 25 MW before (inferred)",
         grid_region_id="FI", is_hypothetical=0,
         notes="Reference: district heating with Nivos since 2015-2016; about 20,000 MWh/yr, up to 72% of town heat demand.",
         prof=dict(it_load_mw_low=20, it_load_mw=25, it_load_mw_high=75, pue_assumed=1.13, chip_family="mixed",
                   cooling_profile_id="air_economizer", confidence="medium", is_assumed=1,
                   source_ids="nebius_75mw_2024;nebius_greenfield_fi;nebius_heat",
                   notes="Free air cooling without chillers or water loops (nebius_greenfield_fi). 25 MW = one third of the announced 75 MW (inferred). Air to water heat exchangers give 35 to 40 C water (nebius_heat)."),
         gis=dict(d_coast_m=50000, d_water_m=1000, dz_m=60, slope_deg=1.0, flat_land_m2=500000, agri_land_m2=300000,
                  d_dh_m=0, has_existing_dh=1, rho_heat_mwh_m=1.5, ind_zoning=1, hdd18=4700),
         eco=dict(eco_sens_index=2, geo_storage_score=5, geo_basis="crystalline bedrock (Finnish shield), hand estimate", mit_tier="med")),
    dict(site_id="us-nd-williston-crusoe", name="Crusoe Digital Flare Mitigation, Williston Basin (representative)",
         operator="Crusoe", city="Williston", region="ND", country_iso2="US", lat=48.1470, lon=-103.6180,
         coord_precision="city_approx", capacity_mw=None,
         capacity_note="fleet of containerized modules at oil well pads; module MW not published", grid_region_id="US-SPP-ND",
         is_hypothetical=0,
         notes="Representative location: Crusoe runs many mobile modules at well pads in ND, MT, WY, CO (crusoe_argus_2021); Williston chosen as the basin centre. Gas to power, no heat reuse.",
         prof=dict(it_load_mw_low=0.5, it_load_mw=1.5, it_load_mw_high=5, pue_assumed=1.1, chip_family="other_accelerator",
                   cooling_profile_id="air_economizer", confidence="low", is_assumed=1,
                   source_ids="crusoe_kraken_2020;crusoe_argus_2021;team_assumption",
                   notes="Module size not published; 1.5 MW per pad assumed (team assumption)"),
         gis=dict(d_coast_m=1500000, d_water_m=3000, dz_m=570, slope_deg=1.0, flat_land_m2=3000000, agri_land_m2=3000000,
                  d_dh_m=10000, has_existing_dh=0, rho_heat_mwh_m=0.3, ind_zoning=1, hdd18=5000),
         eco=dict(eco_sens_index=2, geo_storage_score=3, geo_basis="sedimentary basin (Williston Basin), hand estimate", mit_tier="med"),
         water=dict(p_water=1.2, p_sewer=1.5, wsi=1.0),
         ind=dict(d_pp_m=75000, q_fw_mw=10.0, d_co2_m=150000, d_bio_m=50000, d_market_m=2000,
                  pp_name="Lewis & Clark Station, Sidney MT (hand estimate)", bio_name="not looked up (flare gas is not digester feedstock)",
                  bio_kind="unknown")),
    dict(site_id="ie-arklow-echelon", name="Echelon DUB20 Arklow campus", operator="Echelon Data Centres", city="Arklow",
         region="Wicklow", country_iso2="IE", lat=52.7930, lon=-6.1600, coord_precision="city_approx", capacity_mw=100,
         capacity_note="100 MW facility (rte_echelon_2021)", grid_region_id="IE", is_hypothetical=1,
         notes="Reference: Biocore biogas plant co-located, data center heat to keep the digester warm (agreed 2021, not yet operating per sources).",
         prof=dict(it_load_mw_low=50, it_load_mw=80, it_load_mw_high=100, pue_assumed=1.3, chip_family="mixed",
                   cooling_profile_id="air_chilled_elevated", confidence="low", is_assumed=1,
                   source_ids="rte_echelon_2021;bioenergy_echelon_2021;team_assumption",
                   notes="100 MW facility; IT share and cooling type not published"),
         gis=dict(d_coast_m=2000, d_water_m=500, dz_m=30, slope_deg=2.0, flat_land_m2=300000, agri_land_m2=300000,
                  d_dh_m=10000, has_existing_dh=0, rho_heat_mwh_m=0.8, ind_zoning=1, hdd18=2900),
         eco=dict(eco_sens_index=3, geo_storage_score=4, geo_basis="Ordovician bedrock, hand estimate", mit_tier="med")),
    dict(site_id="us-ny-syracuse-university", name="Syracuse University Green Data Center", operator="Syracuse University",
         city="Syracuse", region="NY", country_iso2="US", lat=43.0030, lon=-76.1220, coord_precision="campus_approx",
         capacity_mw=0.78, capacity_note="780 kW microturbine CHCP plant (nyserda_su_gdc); IT load not published",
         grid_region_id="US-NYISO-CENTRL", is_hypothetical=0,
         notes="Reference: absorption chillers driven by microturbine exhaust (gas CHP), not by data center heat; also heats and cools 621 Skytop Rd. Opened 2009 to 2011.",
         prof=dict(it_load_mw_low=0.2, it_load_mw=0.5, it_load_mw_high=0.78, pue_assumed=1.4, chip_family="cpu_legacy",
                   cooling_profile_id="air_chilled_legacy", confidence="low", is_assumed=1,
                   source_ids="nyserda_su_gdc;team_assumption",
                   notes="IT load not published; below the 780 kW on site generation"),
         gis=dict(d_coast_m=400000, d_water_m=3000, dz_m=150, slope_deg=3.0, flat_land_m2=20000, agri_land_m2=0,
                  d_dh_m=0, has_existing_dh=1, rho_heat_mwh_m=1.0, ind_zoning=0, hdd18=3800),
         eco=dict(eco_sens_index=2, geo_storage_score=3, geo_basis="sedimentary (Onondaga limestone, shale), hand estimate", mit_tier="med"),
         water=dict(p_water=2.0, p_sewer=2.5, wsi=0.5),
         ind=dict(d_pp_m=40000, q_fw_mw=2.0, d_co2_m=200000, d_bio_m=15000, d_market_m=5000,
                  pp_name="nearest thermal power plant not looked up (hand estimate)", bio_name="not looked up", bio_kind="unknown")),
    dict(site_id="nl-eindhoven-northc", name="NorthC Eindhoven 1 (High Tech Campus 53)", operator="NorthC", city="Eindhoven",
         region="North Brabant", country_iso2="NL", lat=51.4110, lon=5.4590, coord_precision="campus_approx", capacity_mw=2.4,
         capacity_note="installed electrical power 2.4 MW (northc_ehv1_factsheet); second 4.5 MW building next door (dcd_northc_ehv2)",
         grid_region_id="NL", is_hypothetical=0,
         notes="Reference: ATES (WKO) free cooling, waste heat to the High Tech Campus heat ring.",
         prof=dict(it_load_mw_low=1.0, it_load_mw=1.8, it_load_mw_high=2.4, pue_assumed=1.25, chip_family="mixed",
                   cooling_profile_id="air_chilled_elevated", confidence="medium", is_assumed=1,
                   source_ids="northc_ehv1_factsheet;grundfos_northc",
                   notes="IT = 2.4 MW installed power / PUE 1.25 (inferred; Grundfos: under 20% for cooling and security)"),
         gis=dict(d_coast_m=120000, d_water_m=1500, dz_m=20, slope_deg=0.5, flat_land_m2=100000, agri_land_m2=50000,
                  d_dh_m=0, has_existing_dh=1, rho_heat_mwh_m=1.5, ind_zoning=1, hdd18=2700),
         eco=dict(eco_sens_index=2, geo_storage_score=4, geo_basis="unconsolidated sand aquifers with active ATES use, hand estimate", mit_tier="med")),
    dict(site_id="se-falun-ecodatacenter", name="EcoDataCenter 1 Falun", operator="EcoDataCenter", city="Falun", region="Dalarna",
         country_iso2="SE", lat=60.6000, lon=15.6000, coord_precision="city_approx", capacity_mw=80,
         capacity_note="80 MW total available power (ecodc_falun); B1 sends up to 10 MW heat (dcd_falun_nordic)",
         grid_region_id="SE", is_hypothetical=0,
         notes="Reference: hot water to the Falu Energi & Vatten CHP plant next door, used to dry sawdust for pellets (pellet drying, district heating).",
         prof=dict(it_load_mw_low=2, it_load_mw=10, it_load_mw_high=80, pue_assumed=1.2, chip_family="mixed",
                   cooling_profile_id="air_chilled_elevated", confidence="low", is_assumed=1,
                   source_ids="ecodc_falun;dcd_falun_nordic;team_assumption",
                   notes="PUE 1.2 (ecodc_falun). IT load set to the 10 MW heat delivery of B1 (dcd_falun_nordic)"),
         gis=dict(d_coast_m=140000, d_water_m=1500, dz_m=120, slope_deg=2.0, flat_land_m2=200000, agri_land_m2=50000,
                  d_dh_m=0, has_existing_dh=1, rho_heat_mwh_m=1.5, ind_zoning=1, hdd18=4600),
         eco=dict(eco_sens_index=2, geo_storage_score=5, geo_basis="crystalline bedrock (Bergslagen), hand estimate", mit_tier="med")),
    dict(site_id="us-hi-kona-nelha", name="NELHA Kona test site (Trevi desalination, not a data center)",
         operator="NELHA / Trevi Systems", city="Kailua-Kona", region="HI", country_iso2="US", lat=19.7280, lon=-156.0570,
         coord_precision="campus_approx", capacity_mw=None, capacity_note="test site, no data center", grid_region_id="US-HI",
         is_hypothetical=1,
         notes="Representative location for Endeavour + Trevi: Trevi ran its forward osmosis process on seawater at NELHA (doe_trevi_2022); Endeavour US campuses not named. Modelled as a 1 MW warm liquid cooled module.",
         prof=dict(it_load_mw_low=1, it_load_mw=1, it_load_mw_high=1, pue_assumed=1.15, chip_family="nvidia_blackwell",
                   cooling_profile_id="dlc_warm", confidence="low", is_assumed=1, source_ids="dcd_endeavour_trevi;team_assumption",
                   notes="1 MW per module so the result reads per MW like the Endeavour claim"),
         gis=dict(d_coast_m=300, d_water_m=20000, dz_m=5, slope_deg=2.0, flat_land_m2=500000, agri_land_m2=0,
                  d_dh_m=20000, has_existing_dh=0, rho_heat_mwh_m=0.1, ind_zoning=1, hdd18=0),
         eco=dict(eco_sens_index=4, geo_storage_score=1, geo_basis="young basalt with fast groundwater flow, hand estimate", mit_tier="high"),
         water=dict(p_water=3.5, p_sewer=3.0, wsi=1.5),
         ind=dict(d_pp_m=2000, q_fw_mw=5.0, d_co2_m=400000, d_bio_m=30000, d_market_m=10000,
                  pp_name="Keahole Generating Station (HELCO), hand estimate", bio_name="not looked up", bio_kind="unknown")),
    dict(site_id="us-wa-seattle-westin", name="Westin Building Exchange", operator="Westin Building Exchange", city="Seattle",
         region="WA", country_iso2="US", lat=47.6142, lon=-122.3387, coord_precision="building", capacity_mw=None,
         capacity_note="34 storey carrier hotel; exports up to 5 MW heat (bdc_amazon_2015)", grid_region_id="US-NW-WA",
         is_hypothetical=0,
         notes="Reference: condenser water at about 65 F to the Amazon Doppler campus eco district (McKinstry, Clise), five heat recovery chillers lift it to about 130 F for radiant floors (amazon_doppler_2017). No snow melt found in sources.",
         prof=dict(it_load_mw_low=5, it_load_mw=10, it_load_mw_high=20, pue_assumed=1.5, chip_family="cpu_legacy",
                   cooling_profile_id="air_chilled_legacy", confidence="low", is_assumed=1,
                   source_ids="amazon_doppler_2017;bdc_amazon_2015;team_assumption",
                   notes="IT load not published; 10 MW assumed so that up to 5 MW of exported heat fits. Coordinates of 2001 Sixth Ave (address not in the cited pages)"),
         gis=dict(d_coast_m=1000, d_water_m=1000, dz_m=40, slope_deg=4.0, flat_land_m2=0, agri_land_m2=0,
                  d_dh_m=100, has_existing_dh=1, rho_heat_mwh_m=4.0, ind_zoning=0, hdd18=2600),
         eco=dict(eco_sens_index=3, geo_storage_score=2, geo_basis="glacial till, hand estimate", mit_tier="med"),
         water=dict(p_water=3.0, p_sewer=5.0, wsi=1.0),
         ind=dict(d_pp_m=50000, q_fw_mw=20.0, d_co2_m=300000, d_bio_m=10000, d_market_m=2000,
                  pp_name="Frederickson area gas plants (hand estimate)", bio_name="not looked up", bio_kind="unknown")),
]

# ---------------------------------------------------------------------------------------------------
# What is actually implemented (long format of site_current_setup*.csv)
# (site_id, field, value, unit, scope, confidence, evidence, source_id, note)
# ---------------------------------------------------------------------------------------------------
SETUP = [
    ("no-rjukan-greenmountain", "already_implemented", "fish_farm", "", "site", "high", "operator", "waa_hima_2026", "Excel option key; not an engineering chain"),
    ("no-rjukan-greenmountain", "status", "operating", "", "site", "high", "press", "waa_hima_2026", "heat reuse operational fall 2025"),
    ("no-rjukan-greenmountain", "reuse_mw_th", "1.75", "MW_th", "site", "medium", "press", "waa_hima_2026", "phase 1 capacity; phase 2 aims at 8 MW"),
    ("no-rjukan-greenmountain", "reuse_since_year", "2025", "year", "site", "high", "press", "waa_hima_2026", ""),
    ("no-rjukan-greenmountain", "heat_reuse", "warm water loop to the Hima Seafood RAS trout farm 800 m away, target 8,000 t trout/yr", "", "site", "high", "operator", "gm_heat_value_2026", "2021 plan said 9,000 t (gm_hima_2021)"),
    ("fi-mantsala-nebius", "already_implemented", "dh;free_cooling", "", "site", "high", "operator", "nebius_heat", ""),
    ("fi-mantsala-nebius", "heat_rejection", "dry", "", "site", "high", "operator", "nebius_greenfield_fi", "free air cooling, no chillers, no water loops"),
    ("fi-mantsala-nebius", "cooling_profile_id", "air_economizer", "", "site", "high", "operator", "nebius_greenfield_fi", ""),
    ("fi-mantsala-nebius", "pue", "1.13", "", "site", "medium", "operator", "nebius_greenfield_fi", "at full capacity"),
    ("fi-mantsala-nebius", "status", "operating", "", "site", "high", "operator", "nebius_heat", ""),
    ("fi-mantsala-nebius", "reuse_mwh_yr", "20000", "MWh/yr", "site", "medium", "operator", "nebius_75mw_2024", "approximately 20,000 MWh/yr (2024 press release); 30 GWh over two years (nebius_heat)"),
    ("fi-mantsala-nebius", "reuse_since_year", "2015", "year", "site", "high", "operator", "nebius_heat", "phased in 2015-2016"),
    ("fi-mantsala-nebius", "heat_reuse", "air to water heat exchangers give 35 to 40 C, utility (Nivos) boosts to 55 to 60 C; up to 72% of town heat demand; 3,220 tCO2e avoided in 2024", "", "site", "high", "operator", "nebius_heat", ""),
    ("us-nd-williston-crusoe", "already_implemented", "stranded_gas_power", "", "operator_region", "high", "press", "crusoe_argus_2021", "flare gas to power for modular compute; no heat reuse"),
    ("us-nd-williston-crusoe", "status", "operating", "", "operator_region", "medium", "press", "crusoe_argus_2021", "44 modules in MT, ND, WY, CO in 2021"),
    ("ie-arklow-echelon", "already_implemented", "biogas", "", "site", "medium", "press", "bioenergy_echelon_2021", "data center heat keeps the Biocore digester warm"),
    ("ie-arklow-echelon", "status", "planned", "", "site", "medium", "press", "rte_echelon_2021", "co-location agreed 2021; no commissioning date in sources"),
    ("us-ny-syracuse-university", "already_implemented", "chp_absorption;heat_reuse_office", "", "site", "high", "third_party", "nyserda_su_gdc", "absorption chillers run on microturbine exhaust, not on data center heat"),
    ("us-ny-syracuse-university", "status", "operating", "", "site", "medium", "third_party", "nyserda_su_gdc", "operating experience beginning 2011; current status not verified"),
    ("us-ny-syracuse-university", "heat_reuse", "12 x 65 kW Capstone C65 gas microturbines (780 kW); exhaust to 2 Thermax absorption chillers and hot water; also heats and cools 621 Skytop Rd", "", "site", "high", "third_party", "nyserda_su_gdc", ""),
    ("nl-amsterdam", "already_implemented", "ates;heat_reuse_office", "", "site", "medium", "third_party", "baxtel_am_sp", "Equinix AM3/AM4 Science Park: ATES wells, waste heat to neighbouring Science Park buildings"),
    ("nl-amsterdam", "status", "operating", "", "site", "medium", "third_party", "baxtel_am_sp", "AM4 heat export to Diemen DH only at feasibility stage in 2025 (equinix_diemen_2025)"),
    ("nl-amsterdam", "pue", "1.2", "", "site", "medium", "press", "ioplus_am3_2026", "Equinix Science Park"),
    ("nl-amsterdam", "heat_reuse", "groundwater at 10 C from 150 m wells for cooling; heat network to nearby Amsterdam University of Applied Sciences buildings", "", "site", "medium", "press", "ioplus_am3_2026", "row describes the Equinix campus inside the cluster site"),
    ("nl-eindhoven-northc", "already_implemented", "ates;heat_reuse_office", "", "site", "high", "operator", "northc_ehv1_factsheet", "ATES free cooling; heat to the High Tech Campus heat ring (grundfos_northc)"),
    ("nl-eindhoven-northc", "status", "operating", "", "site", "high", "operator", "northc_ehv1_factsheet", ""),
    ("se-falun-ecodatacenter", "already_implemented", "dh;pellet_drying", "", "site", "medium", "press", "dcd_falun_nordic", "hot water pipes to the Falu Energi & Vatten CHP plant, sawdust drying for pellets"),
    ("se-falun-ecodatacenter", "pue", "1.2", "", "site", "medium", "operator", "ecodc_falun", ""),
    ("se-falun-ecodatacenter", "reuse_mw_th", "10", "MW_th", "site", "medium", "press", "dcd_falun_nordic", "up to 10 MW from B1 to dry pellets"),
    ("se-falun-ecodatacenter", "status", "operating", "", "site", "medium", "press", "idea_ecodc_2025", ""),
    ("us-hi-kona-nelha", "already_implemented", "desal_fo", "", "site", "medium", "press", "doe_trevi_2022", "Trevi forward osmosis on seawater with solar thermal regeneration, no data center"),
    ("us-hi-kona-nelha", "status", "pilot", "", "site", "medium", "press", "dcd_endeavour_trevi", "not yet deployed at a data center"),
    ("us-wa-seattle-westin", "already_implemented", "dh;heat_pump", "", "site", "high", "operator", "amazon_doppler_2017", "eco district to the Amazon Doppler campus"),
    ("us-wa-seattle-westin", "status", "operating", "", "site", "high", "operator", "amazon_doppler_2017", ""),
    ("us-wa-seattle-westin", "reuse_mw_th", "5", "MW_th", "site", "medium", "press", "phc_amazon_2018", "designed to export up to 5 MW"),
    ("us-wa-seattle-westin", "heat_reuse", "condenser water at about 65 F lifted to about 130 F by five heat recovery chillers, radiant floors in about 4 to 5 million sq ft; about 80 million kWh saved over 25 years", "", "site", "high", "operator", "amazon_doppler_2017", ""),
    ("fr-paris", "already_implemented", "dh;heat_pump;greenhouse", "", "site", "high", "press", "dck_pa10_2024", "Equinix PA10 Saint-Denis: heat to Plaine Saulnier and the Olympic Aquatics Centre, 430 m2 rooftop greenhouse"),
    ("fr-paris", "status", "operating", "", "site", "high", "press", "dck_pa10_2024", "PA10 opened 2023"),
    ("fr-paris", "reuse_mwh_yr", "10000", "MWh/yr", "site", "medium", "press", "dck_pa10_2024", "will produce 10,000 MWh of heat per year"),
    ("fr-paris", "reuse_mw_th", "6.6", "MW_th", "site", "medium", "press", "techzine_pa10_2024", "network can capture 6.6 MW from PA10"),
    ("fr-paris", "heat_reuse", "heat recovered at 28 C all year, three heat pumps raise it to 65 C; free of charge for 15 years", "", "site", "high", "press", "dck_pa10_2024", "row describes Equinix PA10 inside the cluster site"),
]

SITE_COLS = ["site_id", "name", "operator", "city", "region", "country_iso2", "lat", "lon", "coord_precision",
             "capacity_mw", "capacity_note", "grid_region_id", "is_hypothetical", "notes"]
GIS_KEYS = ["d_coast_m", "d_water_m", "dz_m", "slope_deg", "flat_land_m2", "agri_land_m2", "campus_area_m2", "d_dh_m",
            "has_existing_dh", "rho_heat_mwh_m", "ind_zoning"]
IND_KEYS = ["d_pp_m", "q_fw_mw", "d_co2_m", "d_bio_m", "d_market_m"]
REF_IDS = [r["site_id"] for r in REFS]
REUSED_NON_US = ("nl-amsterdam", "fr-paris", "gb-slough")  # existing sites used by the validation


def _replace(path: Path, rows: list[dict], key: str = "site_id", ids: list[str] | None = None) -> None:
    """Drop the lines of `ids` (default: the reference sites) and append `rows`. Other lines stay byte for
    byte as they are (no requoting), so the diff only shows the reference rows."""
    import csv
    import io
    ids = set(REF_IDS if ids is None else ids)
    lines = path.read_text(encoding="utf-8").splitlines()
    header = next(csv.reader([lines[0]]))
    ki = header.index(key)
    keep = [ln for ln in lines[1:] if ln.strip() and next(csv.reader([ln]))[ki] not in ids]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=header, extrasaction="ignore", lineterminator="\n")
    for r in rows:
        w.writerow({k: ("" if v is None else v) for k, v in r.items()})
    path.write_text("\n".join([lines[0], *keep]) + "\n" + buf.getvalue(), encoding="utf-8")


def _num(v):
    return "" if v is None else (f"{v:g}" if isinstance(v, float) else str(v))


def write_tables() -> None:
    # grid regions
    _replace(DP / "grid_regions.csv", GRID_REGIONS, key="grid_region_id", ids=[g["grid_region_id"] for g in GRID_REGIONS])
    # sites
    _replace(DP / "sites.csv", [{k: _num(r.get(k)) for k in SITE_COLS} for r in REFS])
    # heat profiles
    _replace(DP / "site_profiles.csv", [dict(site_id=r["site_id"], scope="site", data_year=2026, evidence="estimated",
                                             **{k: _num(v) for k, v in r["prof"].items()}) for r in REFS])
    # sources for the heat profile citations
    _replace(DP / "heat_sources.csv", [dict(source_id=i, name=t, url=u, published=p, notes="reference validation source")
                                       for i, t, u, p in SOURCES], key="source_id", ids=[s[0] for s in SOURCES])
    # GIS
    gis_rows, gis_long = [], []
    for r in REFS:
        g = dict(r["gis"])
        g["campus_area_m2"] = r["prof"]["it_load_mw"] * 2500
        row = dict(site_id=r["site_id"], lat=r["lat"], lon=r["lon"], coord_precision=r["coord_precision"],
                   hdd18=g.pop("hdd18"))
        for k in GIS_KEYS:
            row[k] = g[k]
            row[f"{k}_source"] = EST_TXT if k != "campus_area_m2" else \
                f"Synthetic: IT load {r['prof']['it_load_mw']} MW (site_profiles.csv) x 2500 m2/MW campus land (team assumption)"
            row[f"{k}_confidence"] = "synthetic" if k == "campus_area_m2" else "low"
        row["elev_m"] = g["dz_m"]
        gis_rows.append({k: _num(v) for k, v in row.items()})
        if r["country_iso2"] == "US":
            for k in GIS_KEYS:
                gis_long.append(dict(site_id=r["site_id"], key=k, value=_num(float(g[k])),
                                     status="assumption" if k == "campus_area_m2" else "data", source=EST,
                                     note=f"confidence=low; {EST_TXT}"))
    _replace(DP / "site_gis.csv", gis_rows)
    _replace(DP / "site_ranking_inputs_gis.csv", gis_long)
    # ecology
    _replace(DP / "site_ecology.csv", [dict(
        site_id=r["site_id"], country_iso2=r["country_iso2"], eco_sens_index=r["eco"]["eco_sens_index"],
        eco_basis=EST_TXT, eco_source_ids=EST, eco_confidence="low", geo_storage_score=r["eco"]["geo_storage_score"],
        geo_basis=r["eco"]["geo_basis"], geo_source_ids=EST, geo_confidence="low", mit_tier=r["eco"]["mit_tier"],
        mit_tier_basis="hand estimate", mit_tier_is_assumed=1, coord_precision=r["coord_precision"],
        coast_km=r["gis"]["d_coast_m"] / 1000) for r in REFS])
    # US only tables: water, aqueduct, industry
    us = [r for r in REFS if r["country_iso2"] == "US"]
    _replace(DP / "site_water.csv", [dict(
        site_id=r["site_id"], water_utility="not looked up", p_water_usd_m3=r["water"]["p_water"],
        p_water_usd_m3_low=round(r["water"]["p_water"] * 0.6, 2), p_water_usd_m3_high=round(r["water"]["p_water"] * 1.5, 2),
        p_sewer_usd_m3=r["water"]["p_sewer"], p_sewer_usd_m3_low=round(r["water"]["p_sewer"] * 0.6, 2),
        p_sewer_usd_m3_high=round(r["water"]["p_sewer"] * 1.5, 2), tariff_basis="estimate", rate_year=2026,
        confidence="low", water_is_estimated=1, sewer_is_estimated=1, source_ids="team_assumption",
        notes="reference validation site: tariff not looked up (hand estimate)") for r in us])
    _replace(DP / "aqueduct_sites.csv", [dict(
        site_id=r["site_id"], aqueduct_version="hand_estimate", bws_score=r["water"]["wsi"],
        bau30_ws_x_s=r["water"]["wsi"], bau50_ws_x_s=r["water"]["wsi"], bws_label="hand estimate, not looked up",
        bws_raw_capped=0, bau30_ws_x_r_capped=0, bau50_ws_x_r_capped=0,
        bws_note="reference validation site: hand estimate, rerun fetch_aqueduct.py") for r in us])
    ind_rows, ind_long = [], []
    for r in us:
        i = r["ind"]
        row = {k: i[k] for k in IND_KEYS}
        row.update(site_coord_precision=r["coord_precision"], pp_name=i["pp_name"], pp_source=EST_TXT, pp_confidence="low",
                   co2_source=EST_TXT, co2_confidence="low", bio_name=i["bio_name"], bio_kind=i["bio_kind"],
                   bio_source=EST_TXT, bio_confidence="low", market_source=EST_TXT, market_confidence="low",
                   pp_any_name=i["pp_name"], d_pp_any_m=i["d_pp_m"], pp_any_q_fw_mw=i["q_fw_mw"])
        ind_rows.append(dict(site_id=r["site_id"], **{k: _num(v) for k, v in row.items()}))
        for k in IND_KEYS:
            ind_long.append(dict(site_id=r["site_id"], key=k, value=_num(float(i[k])),
                                 status="assumption", source=EST, note=EST_TXT))
    _replace(DP / "site_industry.csv", ind_rows)
    _replace(DP / "site_ranking_inputs_industry.csv", ind_long)
    _replace(DP / "site_ranking_inputs_water.csv", [
        *[dict(site_id=r["site_id"], key="p_water_usd_m3", value=_num(r["water"]["p_water"]), status="assumption",
               source="team_assumption", note=EST_TXT) for r in us],
        *[dict(site_id=r["site_id"], key="wsi_index", value=_num(r["water"]["wsi"]), status="assumption",
               source=EST, note=EST_TXT) for r in us]])
    # Excel ranking reads GIS keys only from site_ranking_inputs*.csv, which the GIS thread wrote for US
    # sites. For the non-US validation sites (new and reused) export their site_gis.csv values here.
    gis = pd.read_csv(DP / "site_gis.csv").set_index("site_id")
    eu_ids = [r["site_id"] for r in REFS if r["country_iso2"] != "US"] + list(REUSED_NON_US)
    refs_long = []
    for sid in eu_ids:
        for k in GIS_KEYS:
            v = gis.at[sid, k]
            if pd.isna(v):
                continue
            src = gis.at[sid, f"{k}_source"]
            conf = gis.at[sid, f"{k}_confidence"]
            refs_long.append(dict(site_id=sid, key=k, value=_num(float(v)),
                                  status="assumption" if conf == "synthetic" else "data",
                                  source="site_gis.csv", note=f"confidence={conf}; {src}"))
    pd.DataFrame(refs_long, columns=["site_id", "key", "value", "status", "source", "note"]).to_csv(
        DP / "site_ranking_inputs_refs.csv", index=False)
    # already implemented facts (shared long format with the current setup thread)
    pd.DataFrame(SETUP, columns=["site_id", "field", "value", "unit", "scope", "confidence", "evidence", "source_id",
                                 "note"]).to_csv(DP / "site_current_setup_refs.csv", index=False)
    pd.DataFrame(SOURCES, columns=["source_id", "title", "url", "published"]).to_csv(
        DP / "site_current_setup_refs_sources.csv", index=False)


if __name__ == "__main__":
    write_tables()
    print(f"wrote {len(REFS)} reference sites and {len(SETUP)} current setup rows")
