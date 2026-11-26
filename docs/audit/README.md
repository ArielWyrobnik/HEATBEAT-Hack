# Audit: recommendations against the documented current setup, and where every input comes from

Date: 2026-11-26. Reproduce with `python -m heatbeat_engineering.audit` (offline weather, about 40 s).

Three questions:

1. Does the engineering model compare each option with what the site really does today?
2. Did the recommendation change for sites where research showed a different cooling than we assumed?
3. Which inputs are sourced, which are derived, estimated or synthetic, and what public data could replace estimates?

## 1. Baseline: yes, the documented setup is used (since PR #41)

`heatbeat_engineering.site.load_site()` takes today's heat rejection from `hd.verified_rejection()` when a public
source states it for the site with high or medium confidence (15 of 40 US sites). Otherwise it uses the typical
heat rejection of the site's cooling profile and flags it `assumption`; the API then shows a warning. A site level
reported PUE replaces the profile PUE as the comparison value (5 sites).

What PR #41 changed against the model before it (`results_before_pr41.csv`, commit 0566f4b):

| Site | Assumed before | Documented now | Recommendation before | Now |
|---|---|---|---|---|
| Stargate Abilene | adiabatic | dry (closed loop, air-cooled chillers, Crusoe) | no change | no change |
| Microsoft Fairwater, Mount Pleasant | adiabatic | dry (closed loop, fin coolers, Microsoft) | no change | no change |
| Microsoft San Antonio | adiabatic | tower (water-cooled chillers on reused water, WUE 1.82) | no change | dry cooler, NPV 29.5 M USD |

So for Abilene and Fairwater the answer was already "nothing to improve", but for the wrong reason (we thought
they used evaporative cooling). The Microsoft and Meta outside air sites (Boydton, West Des Moines, Cheyenne,
Quincy, Prineville, Sarpy, Altoona, Eagle Mountain) were modelled as adiabatic before and after, which matches
what the operators report, so their answers did not change. San Antonio is the only site where the answer flipped,
and there the documented setup has more improvement potential than we assumed. Caveat: San Antonio has newer
air-cooled halls too; the model treats the whole campus as towers (the reported WUE 1.82 supports a large tower share).

New in this PR: every result now carries a plain verdict (`heatbeat_engineering/verdict.py`, API fields
`verdict` and `verdict_level`, a banner in the site panel):

- `no_gain`: today's setup is the top row, every alternative loses money. 14 of 40 sites.
- `small_gain`: best NPV below 2 % of one year's electricity bill (team threshold, inside the CAPEX uncertainty). 2 sites (Council Bluffs, Pryor).
- `gain`: 24 sites, but 18 of those have an assumed baseline (no public source for today's cooling).

## 2. How much each answer depends on the baseline and on the IT load

`recommendations.csv` reruns every site with today's heat rejection set to dry, adiabatic and tower. Result: the
cooling gains (switch to dry or adiabatic) exist almost only if the site runs cooling towers today. Exceptions: Las
Vegas, Reno, Santa Clara and Boston would gain from a change if they ran dry coolers today. The digester heating
gains (Miami, Hillsboro, Pryor, Memphis, Quincy) hold whatever the baseline, but shrink to under 0.5 M USD at
Miami and Hillsboro if those sites are not on towers. Where the baseline is assumed
(25 sites), the recommendation is therefore a conditional statement: "if this site uses towers, switching saves X".
Checking the 12 unsourced sites (section 3) would turn these into facts or remove them.

IT load: reported water at Google and Meta sites implies much smaller IT loads than our team estimates
(`current_setup_check.csv`, `implied_it_mw`, derived, assumes all halls evaporative). At the implied load the
recommendation stays the same but the NPV shrinks: Douglas 75.1 to 32.3 M USD, Lenoir 61.0 to 34.2, The Dalles
18.9 to 5.8, Midlothian 19.1 to 2.5, New Albany 30.7 to 11.3; Berkeley barely moves (69.7 to 65.5).
The NPVs in the panel still use the team IT estimates.

## Per site table

Before = model at 0566f4b (baseline from cooling profile). Now = this branch. "no change" = today's setup is best.
| Site | Baseline before | Baseline now (basis) | Before | Now | Verdict | NPV now (M USD) | Best if today were dry / adiabatic / tower (NPV M USD) | NPV at water-implied IT MW |
|---|---|---|---|---|---|---|---|---|
| Chandler data center cluster | tower | tower (assumed) | no change | no change | no_gain | 0.0 | no change (0.0) / no change (0.0) / no change (0.0) |  |
| Mesa data center cluster | tower | tower (assumed) | no change | no change | no_gain | 0.0 | no change (0.0) / no change (0.0) / no change (0.0) |  |
| One Wilshire | tower | tower (assumed) | Adiabatic cooler | Adiabatic cooler | gain | 3.6 | no change (0.0) / no change (0.0) / Adiabatic cooler (3.6) |  |
| Santa Clara data center cluster | tower | tower (assumed) | Adiabatic cooler | Adiabatic cooler | gain | 2.7 | Adiabatic cooler (7.4) / no change (0.0) / Adiabatic cooler (2.7) |  |
| Equinix MI1 (NAP of the Americas) | tower | tower (assumed) | Dry cooler + heat pump + digester heating | Dry cooler + heat pump + digester heating | gain | 9.9 | Dry cooler + heat pump + digester heating (0.3) / Adiabatic cooler + heat pump + digester heating (0.3) / Dry cooler + heat pump + digester heating (9.9) |  |
| QTS Atlanta Metro campus | tower | tower (documented) | Dry cooler | Dry cooler | gain | 93.8 | no change (0.0) / no change (0.0) / Dry cooler (93.8) |  |
| Google Douglas County campus | tower | tower (documented) | Dry cooler | Dry cooler | gain | 75.1 | no change (0.0) / no change (0.0) / Dry cooler (75.1) | 32.3 at 86 MW (we assume 200) |
| Meta Altoona campus | adiabatic | adiabatic (assumed) | no change | no change | no_gain | 0.0 | no change (0.0) / no change (0.0) / Adiabatic cooler (41.0) | 0.0 at 132 MW (we assume 200) |
| Google Council Bluffs campus | tower | tower (documented) | Adiabatic cooler | Adiabatic cooler | small_gain | 0.2 | no change (0.0) / no change (0.0) / Adiabatic cooler (0.2) | 0.2 at 246 MW (we assume 300) |
| Microsoft West Des Moines campus | adiabatic | adiabatic (documented) | no change | no change | no_gain | 0.0 | no change (0.0) / no change (0.0) / Adiabatic cooler (65.5) |  |
| 350 East Cermak (Lakeside Technology Center) | tower | tower (assumed) | Adiabatic cooler | Adiabatic cooler | gain | 21.6 | no change (0.0) / no change (0.0) / Adiabatic cooler (21.6) |  |
| Elk Grove Village cluster | tower | tower (assumed) | Adiabatic cooler | Adiabatic cooler | gain | 12.1 | no change (0.0) / no change (0.0) / Adiabatic cooler (12.1) |  |
| Meta Hyperion campus | dry | dry (assumed) | no change | no change | no_gain | 0.0 | no change (0.0) / no change (0.0) / Dry cooler (468.4) |  |
| One Summer Street | tower | tower (assumed) | Adiabatic cooler | Adiabatic cooler | gain | 6.0 | Adiabatic cooler (0.7) / no change (0.0) / Adiabatic cooler (6.0) |  |
| Google Lenoir campus | tower | tower (assumed) | Dry cooler | Dry cooler | gain | 61.0 | no change (0.0) / no change (0.0) / Dry cooler (61.0) | 34.1 at 84 MW (we assume 150) |
| Apple Maiden campus | tower | tower (assumed) | Dry cooler | Dry cooler | gain | 41.7 | no change (0.0) / no change (0.0) / Dry cooler (41.7) |  |
| Meta Sarpy County campus | adiabatic | adiabatic (documented) | no change | no change | no_gain | 0.0 | no change (0.0) / no change (0.0) / Adiabatic cooler (1.9) | 0.0 at 61 MW (we assume 200) |
| Equinix Secaucus campus (NY1-NY6) | tower | tower (assumed) | Adiabatic cooler | Adiabatic cooler | gain | 19.1 | no change (0.0) / no change (0.0) / Adiabatic cooler (19.1) |  |
| Switch Core campus | tower | tower (assumed) | no change | no change | no_gain | 0.0 | Cooling tower (67.2) / Cooling tower (9.3) / no change (0.0) |  |
| Switch Citadel campus | adiabatic | adiabatic (assumed) | no change | no change | no_gain | 0.0 | Adiabatic cooler (5.8) / no change (0.0) / Adiabatic cooler (27.2) |  |
| 60 Hudson Street | tower | tower (assumed) | Adiabatic cooler | Adiabatic cooler | gain | 1.7 | no change (0.0) / no change (0.0) / Adiabatic cooler (1.7) |  |
| New Albany data center cluster | tower | tower (assumed) | Dry cooler | Dry cooler | gain | 30.7 | no change (0.0) / no change (0.0) / Dry cooler (30.7) | 11.3 at 37 MW (we assume 100) |
| Google Mayes County campus | tower | tower (documented) | Cooling tower + heat pump + digester heating | Cooling tower + heat pump + digester heating | small_gain | 1.9 | Dry cooler + heat pump + digester heating (1.8) / Adiabatic cooler + heat pump + digester heating (1.8) / Cooling tower + heat pump + digester heating (1.9) | 1.9 at 202 MW (we assume 300) |
| Hillsboro data center cluster | tower | tower (assumed) | Adiabatic cooler + heat pump + digester heating | Adiabatic cooler + heat pump + digester heating | gain | 7.9 | Dry cooler + heat pump + digester heating (0.4) / Adiabatic cooler + heat pump + digester heating (0.4) / Adiabatic cooler + heat pump + digester heating (7.9) |  |
| Meta Prineville campus | adiabatic | adiabatic (documented) | no change | no change | no_gain | 0.0 | no change (0.0) / no change (0.0) / Adiabatic cooler (64.6) | 0.0 at 127 MW (we assume 300) |
| Google The Dalles campus | tower | tower (documented) | Adiabatic cooler | Adiabatic cooler | gain | 18.9 | no change (0.0) / no change (0.0) / Adiabatic cooler (18.9) | 5.8 at 77 MW (we assume 250) |
| Google Berkeley County campus | tower | tower (documented) | Dry cooler | Dry cooler | gain | 69.7 | no change (0.0) / no change (0.0) / Dry cooler (69.7) | 65.5 at 188 MW (we assume 200) |
| xAI Colossus | tower | tower (assumed) | Cooling tower + heat pump + digester heating | Cooling tower + heat pump + digester heating | gain | 3.1 | Dry cooler + heat pump + digester heating (3.1) / Adiabatic cooler + heat pump + digester heating (3.1) / Cooling tower + heat pump + digester heating (3.1) |  |
| Stargate Abilene campus (Crusoe / OpenAI) | adiabatic | dry (documented) | no change | no change | no_gain | 0.0 | no change (0.0) / no change (0.0) / Dry cooler (208.4) |  |
| Equinix Dallas Infomart (DA1-DA3) | tower | tower (assumed) | Dry cooler | Dry cooler | gain | 5.1 | no change (0.0) / no change (0.0) / Dry cooler (5.1) |  |
| Google Midlothian campus | tower | tower (assumed) | Adiabatic cooler | Adiabatic cooler | gain | 19.1 | no change (0.0) / no change (0.0) / Adiabatic cooler (19.1) | 2.5 at 33 MW (we assume 250) |
| Microsoft San Antonio campus | adiabatic | tower (documented) | no change | Dry cooler | gain | 29.5 | no change (0.0) / no change (0.0) / Dry cooler (29.5) |  |
| Meta Eagle Mountain campus | adiabatic | adiabatic (assumed) | no change | no change | no_gain | 0.0 | no change (0.0) / no change (0.0) / Adiabatic cooler (17.9) | 0.0 at 31 MW (we assume 200) |
| Equinix Ashburn campus (DC1-DC21) | tower | tower (assumed) | Adiabatic cooler | Adiabatic cooler | gain | 4.3 | no change (0.0) / no change (0.0) / Adiabatic cooler (4.3) |  |
| Microsoft Boydton campus | adiabatic | adiabatic (documented) | no change | no change | no_gain | 0.0 | no change (0.0) / no change (0.0) / Adiabatic cooler (128.9) |  |
| Manassas data center cluster | tower | tower (assumed) | Adiabatic cooler | Adiabatic cooler | gain | 17.2 | no change (0.0) / no change (0.0) / Adiabatic cooler (17.2) |  |
| Digital Realty Ashburn/Sterling campus | tower | tower (assumed) | Adiabatic cooler | Adiabatic cooler | gain | 4.3 | no change (0.0) / no change (0.0) / Adiabatic cooler (4.3) |  |
| Quincy data center cluster | adiabatic | adiabatic (documented) | Adiabatic cooler + heat pump + digester heating | Adiabatic cooler + heat pump + digester heating | gain | 5.6 | Dry cooler + heat pump + digester heating (5.6) / Adiabatic cooler + heat pump + digester heating (5.6) / Adiabatic cooler + heat pump + digester heating (27.3) |  |
| Microsoft Mount Pleasant (Fairwater) campus | adiabatic | dry (documented) | no change | no change | no_gain | 0.0 | no change (0.0) / no change (0.0) / Dry cooler (121.7) |  |
| Microsoft Cheyenne campus | adiabatic | adiabatic (documented) | no change | no change | no_gain | 0.0 | no change (0.0) / no change (0.0) / Dry cooler (59.5) |  |

## 3. Input inventory

`input_inventory.csv`: 971 rows, one per US site and input, with value, class, confidence and source.
`model_parameters.csv`: the 104 global engineering and cost parameters (same for every site).

Per site inputs (40 sites):

| Class | Rows | Inputs |
|---|---|---|
| sourced_site (public source for this site) | 30 | heat rejection (15), cooling profile (10), PUE (5) |
| sourced_region (EIA, eGRID, ISO, utility tariff) | 230 | retail power price, grid CO2, gas price, RIN, LCFS, hourly prices (13), water tariff (18) |
| measured_location (dataset at the coordinates) | 80 | hourly weather (ERA5), water stress (WRI Aqueduct) |
| derived (computed from public data) | 280 | coordinates, GIS distances (coast, heat demand, power plant, digester), heat density, heat price from gas price |
| literature_typical (not site specific) | 51 | loop temperatures per cooling profile |
| team_estimate | 272 | IT load (40), heat rejection (25), cooling profile (30), PUE (35), feedwater heat (40), geology score (40), carbon price (40), water tariff (22) |
| synthetic | 27 | hourly wholesale price shape (PJM, SPP and non-market regions; only used for feedwater and ORC) |
| default (missing) | 1 | Washington clean fuel credit (Quincy) |

Global parameters: 4 physics, 38 literature (check edition), 62 team assumptions, among them most CAPEX values.

Why some values are calculated instead of looked up: nobody publishes the heat a data center rejects, its loop
temperatures or its distance to the next heat consumer, so these must be derived. But the IT load is a different
case: we estimated it although public proxies exist, and the reported water shows our estimates are too high at
several Google sites. That is a real gap, not a modelling necessity.

## Public data we could have but do not use yet

Not checked in detail; each line needs verification before use.

| Gap | Affects | Possible public source |
|---|---|---|
| IT load per site (40 team estimates) | every NPV, water, CO2 | State air permits for backup generators (installed MW, upper bound), utility large load filings, Epoch AI data center database (AI campuses), water-implied MW (already derived, not used as input) |
| Today's cooling at 25 sites without a sourced heat rejection | sign of the recommendation | Aerial and satellite imagery (cooling towers are visible), operator facility data sheets (Equinix, Digital Realty, Switch, CoreSite), county mechanical permits |
| Site PUE (35 profile values) | baseline check | Google publishes PUE per data center campus; Meta and Microsoft report some per site values (to check) |
| Hourly prices PJM (8 sites) and SPP (2) | feedwater and ORC only | PJM Data Miner (free API key, secret `PJM_API_KEY`), SPP marketplace portal files (public, to verify) |
| Hourly grid carbon (annual eGRID now) | CO2 timing, heat pump hours | EIA-930 hourly generation by fuel per balancing authority |
| Large load electricity tariff (state average now) | electricity savings | OpenEI Utility Rate Database, utility tariff books |
| Heat demand for district heating (heat density low confidence) | district heating | NREL ResStock and ComStock, building footprints |
| Water tariff at 22 sites flagged estimate | water value | utility rate schedules (site_water.csv lists the utility) |
| Washington Clean Fuel Standard credit price | Quincy digester value | Washington Department of Ecology credit reports |
| CAPEX (62 team assumptions) | every NPV | Danish Energy Agency technology catalogues (heat pumps, pipes, storage; European costs), DOE and NREL reports |
