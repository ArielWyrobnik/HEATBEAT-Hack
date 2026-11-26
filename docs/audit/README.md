# Audit: recommendations against the documented current setup, and where every input comes from

Date: 2026-11-26, updated the same day with public IT load and cooling data (section 4). Reproduce with `python -m heatbeat_engineering.audit` (offline weather, about 40 s).

Three questions:

1. Does the engineering model compare each option with what the site really does today?
2. Did the recommendation change for sites where research showed a different cooling than we assumed?
3. Which inputs are sourced, which are derived, estimated or synthetic, and what public data could replace estimates?

Sections 1 and 2 describe the state of PR #43 (before the IT load update); section 4 has the current numbers.

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

## Per site table (current)

Before = model at 0566f4b (heat rejection assumed from the cooling profile). Now = current data. "no change" = today's setup is best.

| Site | Baseline before PR #41 | Baseline now (basis) | IT MW | Before PR #41 | Now | Verdict | NPV now (M USD) | Best if today were dry / adiabatic / tower (NPV M USD) |
|---|---|---|---|---|---|---|---|---|
| Chandler data center cluster | tower | tower (assumed) | 60 | no change | no change | no_gain | 0.0 | no change (0.0) / no change (0.0) / no change (0.0) |
| Mesa data center cluster | tower | tower (assumed) | 60 | no change | no change | no_gain | 0.0 | no change (0.0) / no change (0.0) / no change (0.0) |
| One Wilshire | tower | tower (documented) | 10 | Adiabatic cooler | Adiabatic cooler | gain | 3.6 | no change (0.0) / no change (0.0) / Adiabatic cooler (3.6) |
| Santa Clara data center cluster | tower | tower (assumed) | 20 | Adiabatic cooler | Adiabatic cooler | gain | 2.7 | Adiabatic cooler (7.4) / no change (0.0) / Adiabatic cooler (2.7) |
| Equinix MI1 (NAP of the Americas) | tower | tower (assumed) | 17 | Dry cooler + heat pump + digester heating | Dry cooler + heat pump + digester heating | gain | 8.4 | Dry cooler + heat pump + digester heating (0.3) / Adiabatic cooler + heat pump + digester heating (0.3) / Dry cooler + heat pump + digester heating (8.4) |
| QTS Atlanta Metro campus | tower | tower (documented) | 200 | Dry cooler | Dry cooler | gain | 93.8 | no change (0.0) / no change (0.0) / Dry cooler (93.8) |
| Google Douglas County campus | tower | tower (documented) | 86 | Dry cooler | Dry cooler | gain | 32.3 | no change (0.0) / no change (0.0) / Dry cooler (32.3) |
| Meta Altoona campus | adiabatic | adiabatic (assumed) | 168 | no change | no change | no_gain | 0.0 | no change (0.0) / no change (0.0) / Adiabatic cooler (34.4) |
| Google Council Bluffs campus | tower | tower (documented) | 237 | Adiabatic cooler | Adiabatic cooler | small_gain | 0.2 | no change (0.0) / no change (0.0) / Adiabatic cooler (0.2) |
| Microsoft West Des Moines campus | adiabatic | adiabatic (documented) | 300 | no change | no change | no_gain | 0.0 | no change (0.0) / no change (0.0) / Adiabatic cooler (65.5) |
| 350 East Cermak (Lakeside Technology Center) | tower | tower (assumed) | 70 | Adiabatic cooler | Adiabatic cooler | gain | 15.1 | no change (0.0) / no change (0.0) / Adiabatic cooler (15.1) |
| Elk Grove Village cluster | tower | tower (assumed) | 40 | Adiabatic cooler | Adiabatic cooler | gain | 12.1 | no change (0.0) / no change (0.0) / Adiabatic cooler (12.1) |
| Meta Hyperion campus | dry | dry (documented) | 1,632 | no change | no change | no_gain | 0.0 | no change (0.0) / no change (0.0) / Dry cooler (509.6) |
| One Summer Street | tower | tower (documented) | 15 | Adiabatic cooler | Adiabatic cooler | gain | 6.0 | Adiabatic cooler (0.7) / no change (0.0) / Adiabatic cooler (6.0) |
| Google Lenoir campus | tower | tower (assumed) | 84 | Dry cooler | Dry cooler | gain | 34.1 | no change (0.0) / no change (0.0) / Dry cooler (34.1) |
| Apple Maiden campus | tower | tower (assumed) | 100 | Dry cooler | Dry cooler | gain | 41.7 | no change (0.0) / no change (0.0) / Dry cooler (41.7) |
| Meta Sarpy County campus | adiabatic | adiabatic (documented) | 133 | no change | no change | no_gain | 0.0 | no change (0.0) / no change (0.0) / Adiabatic cooler (1.3) |
| Equinix Secaucus campus (NY1-NY6) | tower | tower (documented) | 60 | Adiabatic cooler | Adiabatic cooler | gain | 19.1 | no change (0.0) / no change (0.0) / Adiabatic cooler (19.1) |
| Switch Core campus | tower | tower (assumed) | 200 | no change | no change | no_gain | 0.0 | Cooling tower (67.2) / Cooling tower (9.3) / no change (0.0) |
| Switch Citadel campus | adiabatic | adiabatic (assumed) | 300 | no change | no change | no_gain | 0.0 | Adiabatic cooler (5.8) / no change (0.0) / Adiabatic cooler (27.2) |
| 60 Hudson Street | tower | tower (documented) | 20 | Adiabatic cooler | Adiabatic cooler | gain | 1.7 | no change (0.0) / no change (0.0) / Adiabatic cooler (1.7) |
| New Albany data center cluster | tower | tower (assumed) | 804 | Dry cooler | Dry cooler | gain | 246.5 | no change (0.0) / no change (0.0) / Dry cooler (246.5) |
| Google Mayes County campus | tower | tower (documented) | 368 | Cooling tower + heat pump + digester heating | Cooling tower + heat pump + digester heating | small_gain | 1.9 | Dry cooler + heat pump + digester heating (1.8) / Adiabatic cooler + heat pump + digester heating (1.8) / Cooling tower + heat pump + digester heating (1.9) |
| Hillsboro data center cluster | tower | tower (assumed) | 60 | Adiabatic cooler + heat pump + digester heating | Adiabatic cooler + heat pump + digester heating | gain | 7.9 | Dry cooler + heat pump + digester heating (0.4) / Adiabatic cooler + heat pump + digester heating (0.4) / Adiabatic cooler + heat pump + digester heating (7.9) |
| Meta Prineville campus | adiabatic | adiabatic (documented) | 183 | no change | no change | no_gain | 0.0 | no change (0.0) / no change (0.0) / Adiabatic cooler (39.4) |
| Google The Dalles campus | tower | tower (documented) | 154 | Adiabatic cooler | Adiabatic cooler | gain | 11.6 | no change (0.0) / no change (0.0) / Adiabatic cooler (11.6) |
| Google Berkeley County campus | tower | tower (documented) | 188 | Dry cooler | Dry cooler | gain | 65.5 | no change (0.0) / no change (0.0) / Dry cooler (65.5) |
| xAI Colossus | tower | tower (documented) | 340 | Cooling tower + heat pump + digester heating | Cooling tower + heat pump + digester heating | small_gain | 3.1 | Dry cooler + heat pump + digester heating (3.1) / Adiabatic cooler + heat pump + digester heating (3.1) / Cooling tower + heat pump + digester heating (3.1) |
| Stargate Abilene campus (Crusoe / OpenAI) | adiabatic | dry (documented) | 824 | no change | no change | no_gain | 0.0 | no change (0.0) / no change (0.0) / Dry cooler (208.4) |
| Equinix Dallas Infomart (DA1-DA3) | tower | dry (documented) | 40 | Dry cooler | no change | no_gain | 0.0 | no change (0.0) / no change (0.0) / Dry cooler (5.1) |
| Google Midlothian campus | tower | tower (documented) | 103 | Adiabatic cooler | Adiabatic cooler | gain | 7.9 | no change (0.0) / no change (0.0) / Adiabatic cooler (7.9) |
| Microsoft San Antonio campus | adiabatic | tower (documented) | 200 | no change | Dry cooler | gain | 29.5 | no change (0.0) / no change (0.0) / Dry cooler (29.5) |
| Meta Eagle Mountain campus | adiabatic | dry (documented) | 118 | no change | no change | no_gain | 0.0 | no change (0.0) / no change (0.0) / Adiabatic cooler (10.6) |
| Equinix Ashburn campus (DC1-DC21) | tower | tower (assumed) | 200 | Adiabatic cooler | Adiabatic cooler | gain | 4.3 | no change (0.0) / no change (0.0) / Adiabatic cooler (4.3) |
| Microsoft Boydton campus | adiabatic | adiabatic (documented) | 400 | no change | no change | no_gain | 0.0 | no change (0.0) / no change (0.0) / Adiabatic cooler (128.9) |
| Manassas data center cluster | tower | tower (assumed) | 60 | Adiabatic cooler | Adiabatic cooler | gain | 17.2 | no change (0.0) / no change (0.0) / Adiabatic cooler (17.2) |
| Digital Realty Ashburn/Sterling campus | tower | tower (assumed) | 200 | Adiabatic cooler | Adiabatic cooler | gain | 4.3 | no change (0.0) / no change (0.0) / Adiabatic cooler (4.3) |
| Quincy data center cluster | adiabatic | adiabatic (documented) | 80 | Adiabatic cooler + heat pump + digester heating | Adiabatic cooler + heat pump + digester heating | gain | 5.6 | Dry cooler + heat pump + digester heating (5.6) / Adiabatic cooler + heat pump + digester heating (5.6) / Adiabatic cooler + heat pump + digester heating (27.3) |
| Microsoft Mount Pleasant (Fairwater) campus | adiabatic | dry (documented) | 369 | no change | no change | no_gain | 0.0 | no change (0.0) / no change (0.0) / Dry cooler (99.8) |
| Microsoft Cheyenne campus | adiabatic | adiabatic (documented) | 150 | no change | no change | no_gain | 0.0 | no change (0.0) / no change (0.0) / Dry cooler (59.5) |

## 3. Input inventory

`input_inventory.csv`: one row per US site and input, with value, class, confidence and source.
`model_parameters.csv`: the 104 global engineering and cost parameters (same for every site).

Key site inputs now (40 sites):

| Input | Sourced for the site | Third party estimate | Derived from reported data | Team estimate |
|---|---|---|---|---|
| IT load | 2 (upper bounds: Cermak UPS, MI1 built-out power) | 8 (Epoch AI) | 7 (Meta reported electricity, Google reported water) | 23 |
| Today's heat rejection | 24 | | | 16 |
| PUE for comparison | 13 (incl. Google per campus) | | | 27 |

Other per site inputs: retail power price, grid CO2, gas price, RIN, LCFS, water tariff (18) come from regional
public datasets; weather (ERA5) and water stress (WRI Aqueduct) are datasets at the coordinates; GIS distances are
derived from public map data; loop temperatures are literature typical values per cooling profile; feedwater heat,
geology score and carbon price are team estimates; hourly wholesale prices are synthetic for PJM, SPP and
non-market regions (27 sites, only used for feedwater and ORC); the Washington clean fuel credit is missing (1).

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

## 4. Update: IT load and cooling from public sources (2026-11-26)

New files: `data_pipeline/site_it_load_evidence.csv` (every IT load figure found, with kind, confidence, source,
and whether the model uses it), `data_pipeline/site_current_setup_research.csv` (+ `_sources.csv`): heat rejection
for 9 more sites, Google PUE per campus, and notes. `site_profiles.csv` now carries the adopted IT loads.

How IT load figures are ranked (best first):

1. Derived from operator reported energy: Meta reports electricity per data center (2024, MWh). IT load =
   MWh / 8760 h / Meta fleet PUE 1.08. This is the average load, which is what the annual model needs.
2. Third party estimate with a published method: Epoch AI counts cooling equipment on satellite images and converts
   it to IT power; Epoch says the result is within 1.4x in 80 % of cases.
3. Derived from operator reported water (Google 2023, tower model validated against San Antonio): only where nothing
   better exists (Douglas, Lenoir, Berkeley). Low confidence, assumes all halls evaporative.
4. Hard upper bounds (UPS or built-out capacity): used only where the team estimate was above them (Cermak, MI1).
5. Team estimate: everything else (23 sites), flagged as before.

What changed:

| Site | IT MW before | IT MW now | IT basis | Heat rejection before | Now | Recommendation before (NPV M USD) | Now | Verdict |
|---|---|---|---|---|---|---|---|---|
| One Wilshire | 10 | 10 |  | tower (assumed) | tower (documented) | Adiabatic cooler (3.6) | Adiabatic cooler (3.6) | gain |
| Equinix MI1 (NAP of the Americas) | 20 | 17 | upper bound facility | tower (assumed) | tower (assumed) | Dry cooler + heat pump + digester heating (9.9) | Dry cooler + heat pump + digester heating (8.4) | gain |
| Google Douglas County campus | 200 | 86 | derived from reported water | tower (documented) | tower (documented) | Dry cooler (75.1) | Dry cooler (32.3) | gain |
| Meta Altoona campus | 200 | 168 | derived from reported energy | adiabatic (assumed) | adiabatic (assumed) | no change (0.0) | no change (0.0) | no_gain |
| Google Council Bluffs campus | 300 | 237 | third party it estimate | tower (documented) | tower (documented) | Adiabatic cooler (0.2) | Adiabatic cooler (0.2) | small_gain |
| 350 East Cermak (Lakeside Technology Center) | 100 | 70 | upper bound ups | tower (assumed) | tower (assumed) | Adiabatic cooler (21.6) | Adiabatic cooler (15.1) | gain |
| Meta Hyperion campus | 1,500 | 1,632 | third party planned it | dry (assumed) | dry (documented) | no change (0.0) | no change (0.0) | no_gain |
| One Summer Street | 15 | 15 |  | tower (assumed) | tower (documented) | Adiabatic cooler (6.0) | Adiabatic cooler (6.0) | gain |
| Google Lenoir campus | 150 | 84 | derived from reported water | tower (assumed) | tower (assumed) | Dry cooler (61.0) | Dry cooler (34.1) | gain |
| Meta Sarpy County campus | 200 | 133 | derived from reported energy | adiabatic (documented) | adiabatic (documented) | no change (0.0) | no change (0.0) | no_gain |
| Equinix Secaucus campus (NY1-NY6) | 60 | 60 |  | tower (assumed) | tower (documented) | Adiabatic cooler (19.1) | Adiabatic cooler (19.1) | gain |
| 60 Hudson Street | 20 | 20 |  | tower (assumed) | tower (documented) | Adiabatic cooler (1.7) | Adiabatic cooler (1.7) | gain |
| New Albany data center cluster | 100 | 804 | third party it estimate | tower (assumed) | tower (assumed) | Dry cooler (30.7) | Dry cooler (246.5) | gain |
| Google Mayes County campus | 300 | 368 | third party it estimate | tower (documented) | tower (documented) | Cooling tower + heat pump + digester heating (1.9) | Cooling tower + heat pump + digester heating (1.9) | small_gain |
| Meta Prineville campus | 300 | 183 | derived from reported energy | adiabatic (documented) | adiabatic (documented) | no change (0.0) | no change (0.0) | no_gain |
| Google The Dalles campus | 250 | 154 | third party it estimate | tower (documented) | tower (documented) | Adiabatic cooler (18.9) | Adiabatic cooler (11.6) | gain |
| Google Berkeley County campus | 200 | 188 | derived from reported water | tower (documented) | tower (documented) | Dry cooler (69.7) | Dry cooler (65.5) | gain |
| xAI Colossus | 150 | 340 | third party it estimate | tower (assumed) | tower (documented) | Cooling tower + heat pump + digester heating (3.1) | Cooling tower + heat pump + digester heating (3.1) | small_gain |
| Equinix Dallas Infomart (DA1-DA3) | 40 | 40 |  | tower (assumed) | dry (documented) | Dry cooler (5.1) | no change (0.0) | no_gain |
| Google Midlothian campus | 250 | 103 | third party it estimate | tower (assumed) | tower (documented) | Adiabatic cooler (19.1) | Adiabatic cooler (7.9) | gain |
| Meta Eagle Mountain campus | 200 | 118 | derived from reported energy | adiabatic (assumed) | dry (documented) | no change (0.0) | no change (0.0) | no_gain |
| Microsoft Mount Pleasant (Fairwater) campus | 450 | 369 | third party it estimate | dry (documented) | dry (documented) | no change (0.0) | no change (0.0) | no_gain |

Takeaways:

- Dallas Infomart flips to "nothing to improve": Equinix DA1 runs air-cooled chillers, so there is no tower to replace.
- Eagle Mountain is now documented as dry (Epoch counts 68 dry coolers on the AI halls); the answer stays "no change".
- Google NPVs fall with the lower IT loads (The Dalles 18.9 to 11.6, Midlothian 19.1 to 7.9, Douglas 75.1 to 32.3,
  Lenoir 61.0 to 34.1 M USD). Memphis becomes a small gain because its bill more than doubles with 340 MW.
- New Albany is a cluster: the 804 MW are only Google (333) plus Meta Prometheus (471) and the Meta halls' cooling is
  unknown, so the 246.5 M USD rest on an assumed tower baseline for the whole cluster. Do not present it as a fact.
- Still team estimates: Microsoft Boydton, West Des Moines, Cheyenne, San Antonio; Switch Reno and Las Vegas; QTS
  Atlanta; Apple Maiden; Equinix Ashburn and Secaucus; Digital Realty Sterling; One Wilshire, One Summer, 60 Hudson,
  Infomart (bounds noted in the evidence file); the clusters Chandler, Mesa, Santa Clara, Hillsboro, Quincy, Elk Grove,
  Manassas. Still no documented heat rejection: Chandler, Mesa, Santa Clara, Miami, Chicago, Elk Grove, Maiden,
  Las Vegas, Reno, New Albany, Hillsboro, Altoona, Lenoir, Ashburn, Manassas, Sterling.
- Checked and not usable: Cleanview (MW behind a paywall), Google environmental report PDF (blocks automated reading),
  Microsoft state fact sheets (cooling type but no MW).
