# Who can build it: companies per solution

Every option in the site panel and in "Plan a new data center" lists up to 3 companies that can build its
parts (name, link, one line, where they are, NVIDIA badge). The planner also lists who supplies the chosen IT
cooling, plus the NVIDIA backed plant controls.

- Data: `data_pipeline/solution_vendors.csv` (23 companies, hand researched 2026-11-26)
- Code: `heatbeat_data/vendors.py` (`hd.vendors()`, `hd.vendors_for(components, lat, lon)`,
  `hd.vendors_for_cooling(profile, lat, lon)`)
- API: `OptionResult.vendors`, `ModelResult.cooling_vendors` (planned sites), filled in `heatbeat_api/app.py`
  for `/ranking`, `/evaluate` and `/plan`
- UI: `Vendors` in `frontend/src/components/Results.tsx`
- Tests: `tests/test_vendors.py`

## Columns

| column | meaning |
|---|---|
| roles | heat chain parts the company covers; `~` marks a side business (ranked after core businesses) |
| hq, hq_lat, hq_lon | US base used for the distance (US office or HQ). Only a base, not a full office list |
| coverage | `us` (US projects or office), `north_america`, `outside_us` (no US office found) |
| nvidia_link | `investment` (NVIDIA or NVentures invested), `dsx_partner` (named on NVIDIA's DSX pages), `partner_network`, `inception`, `product` (product built for an NVIDIA platform, no formal link found), `none` |
| nvidia_source | page that states the NVIDIA link (required when not `none`) |
| verified | `verified`: role and NVIDIA link read on the cited page. `partly`: one claim (often the HQ or the exact product) taken from the company profile or a page title only. `unverified`: not checked |
| in_excel | named in the team file `NVIDIA_Ecosystem_Presets_Delta_v3_1.xlsx` |

## Pick rule (team choice)

One company per part, heat use first (district heating, digester, desalination, feedwater, ORC, adsorption),
then heat pump and storage, then heat rejection; at most 3 and no company twice. Per part: US coverage first,
then core over side business, then checked over unchecked, then NVIDIA tier, then distance to the base. A
company with no US office only shows when nobody else covers the part (today: adsorption chillers).

"Near the site" means distance to the company's base. Big firms (Vertiv, Trane, Johnson Controls, GE Vernova)
work through national sales and service networks, so the UI says "works across the US" for them when the base
is more than 400 km away. Local installers and contractors are not in the list yet.

## Audit of the team Excel (sheet 3_NVIDIA_Partner_Lookup and 1_DSX_Hardware_Presets)

The Excel mixes three different things: NVIDIA investments in AI cloud operators, NVIDIA DSX partners, and
cooling hardware it calls "certified DSX vendors". Operators (Nebius, Nscale, Crusoe, Firmus, CoreWeave) do
not build heat reuse for others, so they are not in the vendor list.

| Excel claim | Finding | Source |
|---|---|---|
| Nebius Group "$2B NVIDIA stake" | Wrong amount: NVIDIA was one of three named investors in a 700 M USD round (2024-12-02), its share is not public | [TechCrunch](https://techcrunch.com/2024/12/02/european-ai-infrastructure-company-nebius-nabs-700m-from-nvidia-accel-others) |
| Nebius Mantsala feeds district heating | True (already in our validation set) | [Nebius](https://nebius.com/sustainability/turning-heat-into-a-resource) |
| Brookfield AI Infrastructure Fund "($2B)" | Amount not found: NVIDIA is investor and founding partner, 5 B USD committed by the whole group, NVIDIA's share not stated (2025-11-19) | [Brookfield release](https://bam.brookfield.com/press-releases/brookfield-launches-100-billion-ai-infrastructure-program) |
| Nscale "NVentures / Series C" | NVIDIA invested in the 1.1 B USD Series B (2025-09-25); "Series C" not confirmed. Heat export to aquaculture in Narvik not found | [tech.eu](https://tech.eu/2025/09/26/nscale-raises-11bn-in-nvidia-backed-series-b/) |
| Crusoe "Direct NVIDIA equity", biogas / agri methane | NVIDIA equity not confirmed in this pass (Series E 2025-10-24 investor list not read). Crusoe uses stranded flare gas, not biogas | [Crusoe Series E](https://www.crusoe.ai/resources/newsroom/crusoe-announces-series-e-funding), [Crusoe flaring](https://www.crusoe.ai/resources/newsroom/bitcoin-cuts-oil-and-gas-flaring) |
| Firmus "NVentures" | NVIDIA invested (327 M USD round, 2025-11-14). Fund arm not named | [SiliconANGLE](https://siliconangle.com/2025/11/14/ai-infrastructure-startup-firmus-raises-327m-build-data-centers-australia/) |
| Orbital Materials "NVentures" + Civo DAC pilot | True: NVentures investment (2024-10-22), Civo pilot announced (2025-04-09) | [GlobeNewswire](https://www.globenewswire.com/news-release/2024/10/22/2966994/0/en/Orbital-Materials-to-Advance-Materials-and-Climate-Technologies-with-AI-Using-Investment-from-NVentures.html), [DCD](https://datacenterdynamics.com/en/news/civo-partners-with-orbital-to-pilot-carbon-removal-technology-at-uk-data-center) |
| TerraPower "NVentures" | True: NVentures in the 650 M USD round (2025-06-18). Not a heat reuse vendor | [TerraPower](https://www.terrapower.com/terrapower-announces-650-million-fundraise) |
| Commonwealth Fusion Systems | True: NVIDIA in the 863 M USD Series B2 (2025-08-28). Not a heat reuse vendor | [TechCrunch](https://techcrunch.com/2025/08/28/nvidia-google-and-bill-gates-help-commonwealth-fusion-systems-raise-863m) |
| Applied Digital greenhouse (North Dakota) | No source found | none |
| Corintis as NVIDIA backed | Not found: 24 M USD round with Microsoft and Intel's CEO, no NVIDIA | [tech.eu](https://tech.eu/2025/09/25/corintis-lands-24m-and-microsoft-endorsement-for-chip-cooling-tech/) |
| "Certified DSX vendors": CoolIT, LiquidStack, Submer, Iceotope, ZutaCore | None of them is named on NVIDIA's DSX pages (2025-09-09 and 2026-03-16). CoolIT is in the NVIDIA Partner Network; ZutaCore has a GB200 product; LiquidStack is being bought by Trane | [NVIDIA DSX release](https://nvidianews.nvidia.com/news/nvidia-releases-vera-rubin-dsx-ai-factory-reference-design-and-omniverse-dsx-digital-twin-blueprint-with-broad-industry-support), [CoolIT](https://www.coolitsystems.com/capabilities/co-innovation/nvidia/) |
| DSX partners Trane, Schneider, Siemens, Siemens Energy, GE Vernova, Vertiv | True | NVIDIA DSX release (above) |
| ABB as DSX hardware | Not on NVIDIA's DSX pages | NVIDIA DSX release |
| Coolant outlet 60 / 65 / 70 C per hardware type | Not confirmed; NVIDIA states 45 C facility supply for Blackwell and Rubin (see `docs/HEAT_PROFILES.md`). Our cooling profiles stay as they are | |
| ZutaCore 70 C removes the heat pump | Not found in any source read | |

## NVIDIA backed companies found in addition

| company | link | why it matters |
|---|---|---|
| Phaidra (Seattle) | NVIDIA in the 50 M USD Series B (2025-10-01), DSX contributor | AI control of the cooling plant |
| Accelsius (Austin) | NVIDIA Inception member (2025-10-23) | two-phase direct-to-chip cooling |
| Jacobs (Dallas) | design integrator of the NVIDIA AI factory reference design | engineering of heat networks and storage |
| Emerald AI | NVIDIA joined its seed round (Axios, 2025-07-01) | stranded power and grid flexibility; not in the list because no heat chain part needs it |

## Open gaps

- No NVIDIA backed company found for district heating, digesters, desalination, ORC or adsorption: these
  parts are filled by specialists without an NVIDIA link (Ever-Green Energy, Danfoss, Vanguard Renewables,
  DVO, Trevi Systems, Ormat, Fahrenheit).
- ORC on 45 to 65 C data center heat is not a proven product (Ormat and Turboden are listed as the closest fit).
- No US adsorption chiller maker found; Fahrenheit (Munich) has no US office in the sources read.
- Aquifer and borehole storage: only Jacobs (design, side business). A US drilling or ATES specialist is missing.
- HQ coordinates of rows marked `partly` come from company profiles and were not re-checked.

## Reference projects per solution

`data_pipeline/solution_references.csv` lists real data centers that already run each kind of heat use (fish farm,
greenhouse, district heating, heat pump, biogas, aquifer storage, desalination, ORC), each with status
(operating, pilot, prototype, announced) and a source URL. `hd.references_for(components)` picks up to 2, operating
first; the API adds them to every option (`references`) and to each heat waste cascade stage together with one
company (`vendors`). Biogas (Echelon + Biocore) and desalination (Endeavour + Trevi) are announced only, ORC is a
lab prototype; the panel shows that status. Greenhouse supplier Blockheating has no US office found.
