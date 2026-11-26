# Review of the team Excel model "Hack data.xlsx" (v3.0-SI-Diurnal-DualGrade)

Reviewed 2026-11-26 against the hackathon brief: baseline vs counterfactual, steady state energy
balance, conservative assumptions, outputs in MWh, tCO2, m3, USD and payback, PUE/WUE/ERE.

`mode="excel"` in `heatbeat_ranking.evaluate` keeps every finding below unchanged, so the Excel
can still be reproduced (tests/test_ranking_excel.py). `mode="corrected"` fixes the ones marked
**fixed**. Everything the corrected mode adds is in `engine.CORRECTED` with a status flag.

Severity: **high** changes the ranking, **medium** changes numbers a jury will check, **low** cosmetic.

| # | Finding | Severity | Corrected mode |
|---|---|---|---|
| 1 | Heat pump electricity violates the energy balance | high | fixed |
| 2 | Heat pump COP is unbounded at small lifts | high | fixed |
| 3 | Capacity factor is counted three times | high | fixed (partly) |
| 4 | Every option is credited as displacing heating fuel | high | fixed |
| 5 | The heat sink is never sized | high | open, needs team input |
| 6 | ORC at 10 % efficiency is above what physics allows at these temperatures | medium | fixed |
| 7 | No baseline for the cooling plant (water and fan power saved by reuse) | medium | fixed |
| 8 | No CAPEX, payback, tCO2, m3, PUE/WUE/ERE outputs | medium | added, CAPEX unverified |
| 9 | Banded scores tie a lot (three options at 4.60 in the example) | medium | tie break by net value |
| 10 | Eco water and habitat scores do not depend on the option | medium | open |
| 11 | Example inputs are European, not US | medium | US defaults in inputs.py |
| 12 | Daily min/max cosine instead of real hourly weather | low | real hourly weather |
| 13 | Unsourced coefficients | medium | flagged |

## Details

**1. Heat pump energy balance.** Sheet 3 computes `W = Q_rec / COP` with `Q_rec` = heat taken
from the data center. But a heat pump COP is delivered heat over electricity:
`Q_delivered = Q_source + W` and `COP = Q_delivered / W`, so `W = Q_source / (COP - 1)`. The Excel
underestimates the electricity and values only the source heat, so the delivered heat is missing
the electricity that became heat. Corrected mode uses `W = Q_source / (COP - 1)` and pays the
product on `Q_delivered`. The test checks `Q_delivered = Q_source + W` for every option.

**2. Unbounded COP.** `COP = 0.5 * T_sink_K / (T_sink - T_dc)` gives 33.8 for 60 C to 65 C
(District Heating, Biomass) because there is no temperature approach in the heat exchangers.
Real industrial heat pumps stay below about 8 at small lifts. Corrected mode adds 2.5 K approach on
each side and caps the COP at 8 (assumption, see `CORRECTED`). With 33.8 the thermo score P1 = 5
was earned almost for free, which is why Biomass Processing ranked first in the Excel.

**3. Capacity factor counted three times.** `G = annual recovered / (q_dc x 8760)` enters
P2 (`2.5 + 2G ...`), P4 (bands on G) and indirectly P3 (net value per MWh of DC heat scales with G).
P2 is called "climate/geo" but is driven mostly by G. Corrected mode removes G from P2 (constant
intercept 3.5, same mean level) and keeps it in P4. P3 keeps it because value per MWh of DC heat
is a legitimate economic measure.

**4. Wrong counterfactual for non heating options.** Eco GHG is
`(E x ci_fuel - W x ci_grid) / E` for all 13 options, so absorption cooling, DAC, ORC and
desalination are all credited as if they replaced a gas boiler. Corrected mode uses one
counterfactual per option:
absorption cooling replaces an electric chiller (COP 4.5) on the grid; ORC replaces grid power;
DAC counts the CO2 captured minus its electricity; desalination replaces seawater RO at 3.5 kWh/m3
(Al-Karaghouli and Kazmerski 2013). Heat options keep "natural gas boiler" (US default 200 g/kWh heat,
EPA factor 53.06 kg/MMBtu at 90 % boiler efficiency). The carbon price is applied to avoided CO2
in corrected mode, but not on top of the DAC 45Q credit (that would count the same ton twice).

**5. Sink size.** The recovered heat is always a share of `q_dc_mw`, so a fish farm, a biogas
digester or a greenhouse takes the full 25 MW (Excel) or 180 MW (Ashburn). A large anaerobic
digester needs well under 2 MW of heat, and 25 MW of greenhouse heat is about 50 to 100 ha of
glasshouse. `flat_land_m2`, `agri_land_m2` and `rho_heat_mwh_m` are only used as gates, never to size
the sink. This inflates MWh, tCO2 and USD for every option and favours options with a flat demand.
Proposal (not built, needs the team): a sink capacity per option from land area or demand, for
example greenhouse MW = agri_land_m2 x peak W/m2, district heating MWh = rho_heat x network length.

**6. ORC.** Net electric efficiency 10 % from a 60 to 100 C source. Carnot between 60 C and
a 25 C condenser is 10.5 %, real ORC reach about 40 % of that. The KO gate (min T_dc >= 80 C) removes
ORC anyway, but if a hotter site passes the gate the value would be about 2.5 times too high.
Corrected mode uses 40 % of Carnot hour by hour against ambient + 10 K.

**7. Baseline cooling plant.** Without reuse the data center rejects the same heat in its cooling
towers or dry coolers. Reuse avoids that: about 1.6 m3 of evaporated water per MWh (physics:
3600 MJ / 2.26 MJ/kg) if the baseline is evaporative, plus fan and pump power (0.03 MWh_e/MWh_th,
assumption). The Excel ignores this, so the water benefit (WUE) of reuse is missing, which matters for
a water scarce site. Absorption cooling is the exception: its absorber rejects drive heat plus cooling
load, so it adds water use; corrected mode accounts for that.

**8. Missing outputs.** The brief asks for MWh, tCO2, m3, USD, payback, PUE, WUE, ERE.
Corrected mode returns `heat_delivered_mwh`, `co2_avoided_t`, `water_saved_m3`, `net_value_usd_yr`,
`capex_usd`, `payback_yr`, `pue_baseline`, `pue_with`, `ere`, `wue_baseline_l_kwh`, `wue_with_l_kwh`.
CAPEX per kW_th in `engine.CAPEX_USD_PER_KW_TH` is a rough screening value derived from the solution
catalogue where a conversion exists, otherwise a team guess. **Unverified. Do not quote payback
times from it.** OPEX other than electricity is not included yet.

**9. Ties.** The four sub scores are bands from 1 to 5, so scores cluster. In the Excel example
Biogas, Fish Farm and Boiler Feedwater all reach 4.60 in corrected mode. Corrected mode ranks ties
by net annual value. Longer term the team could score on continuous values (for example payback).

**10. Eco water and habitat.** Both depend only on `mit_tier`, `wsi_index` and `eco_sens_index`,
the same for every option except a larger water penalty for absorption cooling. The eco grade
therefore only separates options through GHG. The water balance from finding 7 and desalination
output (m3) could feed the water score. Left open for the team.

**11. Example inputs are European.** 0.075 USD/kWh heating fuel and 95 USD/t CO2 are EU levels.
US industrial and commercial gas is much cheaper and there is no federal carbon price. US defaults
are in `inputs.INPUT_SPEC`; carbon price 0 for heat options and the 45Q credit (180 USD/t for DAC
with geologic storage, IRA 2022) for DAC. Gas price default is UNVERIFIED until the market thread
delivers state prices.

**12. Weather.** The cosine expansion puts the daily minimum at 04:00 and maximum at 16:00 every
day. Real hourly data (Open-Meteo ERA5, `heatbeat_data`) is used for real sites. Hour counts in the
gates ("at least 2000 h below 15 C") are sensitive to this, so the two methods can flip gates near
the thresholds. `rank_site(..., weather="daily_cosine")` compares both.

**13. Unsourced coefficients.** Product price factors (650, 900, 950 x fuel price), the Q_rec
temperature ramps (for example fish farm `(26 - T) / 18`), all gate thresholds, the DAC 0.556 t/MWh,
the MED 15.38 m3/MWh and the 0.25 MWh_e/t DAC electricity have no source in the Excel. They are
kept, but marked as team assumptions in `options.py`. The MED and DAC values are in a plausible
range compared with the solution catalogue.

## Not errors, but worth knowing

- `q_dc_mw` is defined as IT load x 0.9. For air cooled sites the recoverable share at a useful
  temperature is much lower than 0.9 unless air to water coils are installed.
- Air cooled `T_dc = max(t_dc_base, T_amb + 12)` means hotter weather gives hotter waste heat,
  which can make absorption cooling pass the 65 C gate in a heat wave. Plausible for exhaust air,
  not for a chilled water loop.
- `rank` uses Excel RANK, so ties share a rank and the next rank is skipped.
