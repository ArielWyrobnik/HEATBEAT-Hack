# Wind radiator: passive, fan free heat rejection for a hot closed loop

Status: first feasibility screen (2026-11-26). Not wired into the API or the ranking yet.
Code: `heatbeat_engineering/wind_radiator.py`. Run: `python -m heatbeat_engineering.wind_radiator`.

## Idea

A Vera Rubin class closed loop returns at about 55 C and has to be cooled back to 45 C
(source `nvidia_45c_2026`, vendor marketing). With a 55 C loop, even 30 C air is 25 K colder than the
water. A flat, wide, shallow finned radiator that turns face-on (90 degrees) to the wind uses the wind
as its "fan". Question: how much of the heat can it reject with zero fan power, hour by hour, using
real wind and temperature data?

## Case site: Microsoft Fairwater, Mount Pleasant (WI)

Why this site:

- Documented closed loop liquid cooling with air side heat rejection: "172 twenty-foot fans to chill large
  heat-exchanger fins along the building exterior" plus chillers (`dcf_fairwater_2025`). Those are
  exactly the fans the wind radiator would replace.
- Cold (mean 10.7 C, max 33.8 C) and windy (mean 4.06 m/s at 10 m, wind below 2 m/s only 12 % of hours).
- IT load 369 MW with 90 % liquid heat share (Epoch AI estimate, `site_it_load_evidence.csv`), so about
  332 MW of loop heat. Today the site runs GB200 (Blackwell). **The 55 / 45 C Rubin loop is a
  hypothetical upgrade.**

Weather: hourly 2024, Open-Meteo `wind_speed_10m` and `temperature_2m` from `data/parquet/weather_hourly.parquet`.
Wind direction is not used: the panel is assumed to track the wind; tracking and array losses are lumped
into `yaw_array_factor`.

## Model (per hour, per m2 of radiator face)

| Step | Formula | Source / status |
|---|---|---|
| Wind at panel | U = wind_10m x height_factor x yaw_array_factor | assumption |
| Flow through the coil | v = U / (1 + K/4) | porous screen in a free stream (Taylor 1944 screen theory) |
| Air capacity rate | C_air = rho v cp | physics |
| Conductance | UA = UA_ref (v / 2 m/s)^0.6 | Kays & London style finned coil, UA_ref UNVERIFIED |
| Effectiveness | cross flow, both unmixed (Incropera eq. 11.33) | physics |
| Passive heat | q = eps C_min (55 C - T_db), capped at the load | physics |

The panel sits in series ahead of the existing fan dry cooler, which stays as backup. Whatever the panel
cannot do in an hour (calm, warm) goes to the fan cooler; its fan power uses the same affinity law as
`heat_rejection.reject`.

Ignored, conservative for the panel: natural draft at zero wind, gusts above the hourly mean.
Ignored, optimistic: array wake and blockage beyond the lumped factor, fouling, yaw lag.

## Results, Mount Pleasant, per MW of loop heat (40 m2 face per MW)

| Face area (m2/MW) | Heat rejected passively | Hours fully passive (of 8784) |
|---|---|---|
| 5 | 29 % | 0 |
| 10 | 56 % | 505 |
| 20 | 85 % | 4321 |
| **40** | **98 %** | **7956** |
| 80 | 99.7 % | 8693 |

- Shortfall hours come with calm air (mean 0.6 m/s), not with heat. The longest run of not fully passive
  hours is 26 h. Covering that with a hot water tank would need about 2,000 m3 per MW, so the fans must stay
  as backup. The panel saves energy but does not remove the fan cooler.
- Tornado on passive share (base 98 %): face area 85 to 99.7 %, coil K 92 to 99 %, UA_ref 95 to 99 %,
  yaw / array factor 95 to 99 %. Even with pessimistic values more than 90 % of the heat goes out passively.

### Fan energy saved: the honest part

The panel removes almost all fan energy, but at a 55 / 45 C loop the fan energy was small to begin with:

| Baseline fan energy | MWh per MW per year | Share of heat | Saved with panel |
|---|---|---|---|
| Model (affinity law, design at the hottest hour) | 39.8 | 0.45 % | 39.6 MWh |
| Upper bound (fans always at design SFP 0.03) | 263.5 | 3.0 % | 258 MWh |

The real value sits in this range; it depends on how Fairwater controls its 172 fans (not public).
The affinity law model is sensitive to its design hour (Abilene comes out lower than Mount Pleasant only
because its 44 C design hour inflates the design flow), so read the lower row as a floor.

Scaled to 332 MW of loop heat (electricity: MISO Wisconsin, EIA 2024 retail industrial 85.4 USD/MWh,
eGRID 2023 MROE 634 kg CO2/MWh):

| | Floor | Upper bound |
|---|---|---|
| Electricity saved | 13 GWh/yr | 86 GWh/yr |
| Cost saved (retail industrial) | 1.1 M USD/yr | 7.3 M USD/yr |
| CO2 avoided | 8,300 t/yr | 54,000 t/yr |
| PUE reduction | about 0.005 | about 0.026 |
| Radiator face area | 13,300 m2, e.g. 10 m high x 1.3 km | same |

For scale: 172 twenty-foot (6.1 m) fans are about 5,000 m2 of fan swept area, so the panel area is the
same order as the existing exterior heat exchanger wall.

Payback cannot be given: there is no cost figure for a wind tracking radiator. Break-even: at the floor
saving the panel may cost about 3.4 k USD per MW per year of life (85 USD/m2 over 10 years); at the upper
bound about 22 k USD per MW per year. A dry cooler is about 90 k USD/MW installed (`capex_dry_usd_kw`, UNVERIFIED).

### Comparison with other sites (same panel, per MW)

| Site | Passive share | Longest gap | Note |
|---|---|---|---|
| Cheyenne (Microsoft) | 98 % | 11 h | windiest, but today evaporative air economizer, no closed loop |
| Mount Pleasant (Microsoft) | 98 % | 26 h | closed loop and fan wall documented |
| Abilene (Stargate) | 94 % | 61 h | closed loop documented, hot summers |
| Chandler AZ | 71 % | | worst mainland case |

All 40 US sites with weather reach 70 % or more. The full screen prints with the run command above.

## Takeaway

1. Physically it works: with a 55 C loop and real 2024 wind, a tracking flat radiator of about 40 m2 per MW
   rejects about 98 % of the heat at Mount Pleasant without fans.
2. The energy edge is modest: 0.5 to 3 % of IT heat in fan power, PUE down by 0.005 to 0.026. The hot
   loop itself (Rubin 45 C instead of Blackwell 25 / 35 C) saves more: the model gives 121 MWh/MW/yr of
   fan plus chiller power for a 25 / 35 C loop at Mount Pleasant vs 40 for 55 / 45 C.
3. The fans cannot go away (calm spells up to 26 h), so the panel is extra CAPEX next to the fan cooler,
   unless the fan cooler can be downsized because it only runs on calm days.

## Open points

- `coil_k`, `ua_ref_kw_km2` and `yaw_array_factor` are UNVERIFIED team assumptions. They need a coil
  selection from a manufacturer and an array study (CFD or wind tunnel data).
- Real fan control at Fairwater is unknown, which sets the baseline.
- Wind data is reanalysis (Open-Meteo), smoother than a met mast at the site.
