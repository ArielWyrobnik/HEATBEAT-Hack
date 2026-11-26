# Current setup per data center (what sites already do)

Question this answers: is an option an improvement over what the site does today, or does the site already
do it (or better)? The engineering baseline used to assume the heat rejection from the cooling profile.
Now it uses the documented setup where a public source exists, and flags options the site already has.

Status: researched 2026-11-26 from operator reports, utility records, permits and press. 28 of the
40 US sites have at least one sourced fact, 15 have a documented heat rejection.

## Files

| File | Content |
|---|---|
| `data_pipeline/site_current_setup.csv` | Long format, one row per site and field: `site_id, field, value, unit, scope, confidence, evidence, source_id, note` |
| `data_pipeline/site_current_setup_sources.csv` | `source_id, title, url, published` |
| `data_pipeline/site_current_setup_<x>.csv` (+ `_<x>_sources.csv`) | More rows from other threads, same columns, read automatically |
| `data_pipeline/current_setup_check.csv` | Model baseline against reported water, WUE, PUE (`python -m heatbeat_engineering.validate_setup <out.csv>`) |
| `heatbeat_data/current_setup.py` | `hd.current_setup(site_id)`, `hd.verified_rejection(site_id)`, `hd.already_implemented(site_id)`, `hd.verification_status()` |

Fields: `status`, `cooling_profile_id`, `heat_rejection` (dry / adiabatic / tower; `mixed` is context only),
`water_source`, `water_use_m3_yr` (consumption), `water_withdrawal_m3_yr`, `water_use_peak_m3_day`, `wue_l_kwh`, `pue`,
`chip_family`, `onsite_generation`, `heat_reuse`, `already_implemented` (semicolon list: `dry`, `reclaimed_water`,
`free_cooling`, `heat_reuse_office`, engineering use ids such as `dh_5km`, `biogas_meso`, families `dh`, `biogas`, `desal`).

Rules:
- `scope` says what the value describes. Only `site`, `campus`, `campus_legacy`, `cluster` and `operator_region`
  describe the site; `area` (e.g. Loudoun County) and `operator_fleet` (e.g. Equinix global PUE) are context.
- `confidence`: high = the operator states it for this site; medium = press, or inferred from strong evidence
  (e.g. about 1 billion gallons a year only fits evaporative cooling); low = operator typical design or weak inference.
- `evidence = inferred` marks every team inference. Do not present those as facts.
- Model mapping: air-cooled chillers with free cooling coils and closed-loop dry fin coolers = `dry` (dry cooler
  plus trim chiller); direct evaporative outside air (Microsoft, Meta) = `adiabatic`; cooling towers or
  water-cooled chillers = `tower`.

## How the model uses it

- `load_site()` sets `baseline_rejection` from `verified_rejection()` (high or medium confidence, site scope),
  flagged `data` with the source; otherwise the profile default, flagged `assumption`, and the API adds a warning.
- A site level PUE (high or medium) replaces `pue_assumed` as the reported PUE.
- `site_profiles.csv` carries the verified cooling profile and PUE (Boydton, San Antonio, Cheyenne, Prineville,
  Meta fleet PUE for Altoona, Sarpy, Eagle Mountain); `evidence = verified_setup` on rows with a documented setup.
- API: `Baseline.heat_rejection`, `heat_rejection_flag`, `heat_rejection_source`, `setup_status`, `current_setup`
  (list of facts with source URL); `OptionResult.already_in_place`; the "no change" option is labelled
  "(today's setup, no change)". `SiteSummary.setup_status` for the map.
- Overrides (UI "Current setup" box, `POST /api/evaluate`): `{"cooling_profile": "<id>", "baseline_rejection": "dry|adiabatic|tower"}`.

## What we found (2026-11-26)

| Site | Today | Source |
|---|---|---|
| Stargate Abilene | Closed-loop non-evaporative liquid cooling, air-cooled chillers, no cooling water; GB200; GE Vernova gas turbines as backup | Crusoe 2025-08-05, Epoch |
| Microsoft Fairwater | Closed-loop chip cooling (GB200 NVL72), heat-exchanger fins with 172 fans plus chillers; water only on hottest days | Microsoft 2024-12-09, DCF 2025-10-09, WPR |
| xAI Colossus | Cold plates plus rear door HX, chillers outside; up to 3.7 million gal/day potable water requested; reuse plant stopped Apr 2026; Megapacks, gas turbines | ServeTheHome, E&E News 2026-05-04 |
| Meta Hyperion | Under construction; Meta typical design is DLC with dry coolers (not stated for the site); Entergy gas plants | Meta 2025-12-17, Fortune 2026-03-27 |
| Google (Council Bluffs, Pryor, The Dalles, Berkeley, Douglas, Lenoir, Midlothian) | Evaporative cooling; water 0.5 to 4.2 million m3/yr (2023); Douglas on recycled wastewater, Berkeley partly groundwater, Pryor cooling towers on Neosho River water | Google 2024 Environmental Report (via DIW), The Frontier, Live 5 |
| Microsoft Boydton, West Des Moines, Cheyenne, Quincy | Outside air with direct evaporative cooling, water under 10 to 15 % of the year; Quincy on reused water | Microsoft state fact sheets 2023 and 2025 |
| Microsoft San Antonio | Legacy halls water-cooled chillers on reused water, newer halls air-cooled; WUE 1.82, PUE 1.307 (CY2022) | Microsoft Texas fact sheets |
| Meta Prineville | 100 % outside air, direct evaporative, no chillers; WUE 0.22, PUE 1.07; server heat warms offices | Meta 2011, OCP 2013 |
| QTS Atlanta | Chillers, cooling towers, water-side economizer, rainwater | QTS data sheet |
| Switch Reno | Effluent (reclaimed) water, PUE 1.18 one sector | Switch |
| Loudoun (Equinix, Digital Realty, Manassas) | Area only: mixed closed loop and evaporative, mostly potable, reclaimed loop for about 40 customers | Loudoun County, Loudoun Water, Broadband Breakfast |
| Equinix | Fleet PUE 1.39, WUE 0.95; heat export in Canada, Finland, France, none operating in the US | Equinix 2024 data |

No US site in the list exports heat to a district heating network. Not found: Chicago, Elk Grove, Santa Clara,
One Wilshire, Hillsboro, Las Vegas, Apple Maiden, NYC, Boston, Dallas, Chandler, Mesa (cooling not published).

## Model against reported values

`current_setup_check.csv`. WUE and PUE match where sites publish them: San Antonio WUE 1.83 modelled vs
1.82 reported; Boydton PUE 1.137 vs 1.144; Cheyenne 1.114 vs 1.125; Boydton, Cheyenne, Prineville WUE
0.23 to 0.32 modelled vs 0.17 to 0.23 reported (direct evaporative uses a bit less water than the adiabatic model).

Water volume at Google sites: the model gives more water than reported. With the tower model confirmed
by San Antonio, the likely cause is our IT load guesses (team estimates): reported water implies about
80 MW at The Dalles (we assume 250), 33 MW at Midlothian (250), 86 MW at Douglas (200), 190 to 250 MW at
Berkeley, Council Bluffs and Pryor (200 to 300). `implied_it_mw` in the check table gives these numbers; they are
derived, not reported, and assume all halls are evaporative.
