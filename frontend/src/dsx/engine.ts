// @ts-nocheck
/**
 * DSX Waste-Heat Recovery Evaluator v3.2.0, the same engine as evaluator.py (verified to give identical
 * results). 8,760-h diurnal physics, 13 knock-out gates, viability 0-5 and a standalone eco grade A-F.
 * Typed facade: ./types.ts. Used by ./adapter.ts to plug the evaluator into Heat Beat as a model.
 */
export const ENGINE = (() => {
  const VERSION = "3.3.0";
  const HOURS = 8760;
  const C = {
    carnot_eta: 0.50, approach_k: 5.0, cop_cap: 8.0, air_offset_c: 12.0,
    orc_eta_frac: 0.45, orc_cond_offset_c: 10.0, hp_capex_usd_kw: 600.0, opex_frac: 0.02,
    payback_best_yr: 3.0, payback_worst_yr: 15.0, boiler_eff: 0.90, availability: 0.998, absorption_cop: 0.70,
    chiller_cop: 5.0, med_kwh_th_m3: 60.0, ro_kwh_e_m3: 3.5, dac_mwh_th_t: 1.8, btes_round_trip: 0.75,
    market_ref_m: 100000.0, mit_mult: { low: 1.0, med: 0.70, high: 0.35 },
  };
  const GRADE_BANDS = [[4.20, "A"], [3.40, "B"], [2.60, "C"], [1.80, "D"], [-Infinity, "F"]];
  const DSX_PRESETS = {
    legacy_air:       { label: "Legacy Air-Cooled (28 C)",         cooling_type: "air",    t_dc_base_c: 28.0 },
    dlc_coldplate:    { label: "Direct-to-Chip Cold Plate (60 C)", cooling_type: "liquid", t_dc_base_c: 60.0 },
    immersion_single: { label: "Single-Phase Immersion (65 C)",    cooling_type: "liquid", t_dc_base_c: 65.0 },
    two_phase_dlc:    { label: "Two-Phase Waterless DLC (70 C)",   cooling_type: "liquid", t_dc_base_c: 70.0 },
  };
  const WHAT_IF_PRESET = "two_phase_dlc";
  const INPUT_SPEC = {
    is_greenfield: ["bin", 0, 1], cooling_type: ["enum", ["liquid", "air"]], t_dc_base_c: ["num", 25, 95],
    q_dc_mw: ["num", 0.1, 500], slope_deg: ["num", 0, 45], flat_land_m2: ["num", 0, null], d_water_m: ["num", 0, null],
    wsi_index: ["num", 0, 5], has_existing_dh: ["bin", 0, 1], d_dh_m: ["num", 0, null], rho_heat_mwh_m: ["num", 0, null],
    d_coast_m: ["num", 0, null], dz_m: ["num", 0, null], d_bio_m: ["num", 0, null], d_co2_m: ["num", 0, null],
    d_pp_m: ["num", 0, null], q_fw_mw: ["num", 0, null], ind_zoning: ["bin", 0, 1], campus_area_m2: ["num", 0, null],
    agri_land_m2: ["num", 0, null], geo_storage_score: ["num", 1, 5], p_elec_usd_kwh: ["pos", 0, null],
    p_fuel_usd_kwh: ["pos", 0, null], p_steam_usd_mwh: ["num", 0, null], p_water_usd_m3: ["num", 0, null],
    p_co2_usd_ton: ["num", 0, null], d_market_m: ["num", 0, null], ci_grid_g_kwh: ["num", 0, null],
    ci_fuel_g_kwh: ["num", 0, null], eco_sens_index: ["num", 1, 5], mit_tier: ["enum", ["low", "med", "high"]],
  };
  class InputError extends Error {}

  const clip = (x, lo, hi) => Math.min(hi, Math.max(lo, x));
  const lin = (x, x0, x1) => clip((x - x0) / (x1 - x0), 0, 1);
  const r = (x, d) => { const m = 10 ** d; return Math.round(x * m) / m; };
  const r2 = x => (x == null || !Number.isFinite(x)) ? null : r(x, 2);
  const sum = a => { let s = 0; for (const v of a) s += v; return s; };

  function validateSite(site) {
    const missing = Object.keys(INPUT_SPEC).filter(k => !(k in site));
    if (missing.length) throw new InputError("missing inputs: " + missing.join(", "));
    const clean = {}, errors = [];
    for (const [k, sp] of Object.entries(INPUT_SPEC)) {
      let v = site[k]; const kind = sp[0];
      if (kind === "enum") { if (!sp[1].includes(v)) errors.push(`${k}=${v} not in (${sp[1].join(", ")})`); clean[k] = v; continue; }
      v = typeof v === "string" ? v.trim() === "" ? NaN : Number(v) : Number(v);
      if (!Number.isFinite(v)) { errors.push(`${k} must be a finite number`); continue; }
      if (kind === "bin" && v !== 0 && v !== 1) errors.push(`${k} must be 0 or 1`);
      else if (kind === "pos" && v <= 0) errors.push(`${k} must be > 0`);
      else if (kind === "num" && (v < sp[1] || (sp[2] != null && v > sp[2]))) errors.push(`${k}=${v} outside [${sp[1]}, ${sp[2]}]`);
      clean[k] = v;
    }
    if (errors.length) throw new InputError(errors.join("; "));
    clean.baseline_evaporative = (site.baseline_evaporative === 1 || site.baseline_evaporative === true || site.baseline_evaporative === "1") ? 1 : 0;
    return clean;
  }

  function normalizeClimate(tmin, tmax) {
    tmin = Array.from(tmin, Number); tmax = Array.from(tmax, Number);
    const warnings = [];
    if (tmin.length !== tmax.length) throw new InputError("t_min and t_max lengths differ");
    if (tmin.length === 366) { tmin.splice(59, 1); tmax.splice(59, 1); warnings.push("366-day series supplied; Feb 29 (day 60) dropped."); }
    if (tmin.length !== 365) throw new InputError(`climate series must have 365 or 366 rows, got ${tmin.length}`);
    if (![...tmin, ...tmax].every(Number.isFinite)) throw new InputError("climate series contains blanks/NaN (fill gaps first)");
    if (tmin.some(v => v < -90) || tmax.some(v => v > 60)) throw new InputError("climate values outside plausible range (-90..60 C); check for -999 fill values");
    let sw = 0;
    for (let i = 0; i < 365; i++) if (tmin[i] > tmax[i]) { sw++; [tmin[i], tmax[i]] = [tmax[i], tmin[i]]; }
    if (sw) warnings.push(`${sw} day(s) had t_min > t_max; values swapped.`);
    return [tmin, tmax, warnings];
  }

  function expandDiurnal(tmin, tmax) {
    const out = new Float64Array(HOURS);
    for (let d = 0; d < 365; d++) {
      const mean = 0.5 * (tmax[d] + tmin[d]), amp = 0.5 * (tmax[d] - tmin[d]);
      for (let h = 0; h < 24; h++) out[d * 24 + h] = mean + amp * -Math.cos(2 * Math.PI * (h - 4) / 24);
    }
    return out;
  }
  const coolant = (s, tamb) => s.cooling_type === "liquid" ? new Float64Array(HOURS).fill(s.t_dc_base_c)
    : tamb.map(t => Math.max(s.t_dc_base_c, t + C.air_offset_c));

  function heatPump(tdc, tsink) {
    const a = C.approach_k, cop = new Float64Array(HOURS), direct = new Uint8Array(HOURS);
    const thot = tsink + a;
    for (let i = 0; i < HOURS; i++) {
      if (tdc[i] >= tsink + a) { direct[i] = 1; cop[i] = Infinity; continue; }
      const lift = Math.max(thot - (tdc[i] - a), 1e-6);
      cop[i] = clip(C.carnot_eta * (thot + 273.15) / lift, 1.05, C.cop_cap);
    }
    return [cop, direct];
  }

  // ---- gates
  const chk = (c, m, f) => { if (!c) f.push(m); };
  const gf = (s, f) => chk(s.is_greenfield === 1, "only possible when designed in with a new build; this is an existing site", f);
  // v3.3: every rejection states the site's actual value and the limit it misses.
  const km = (m) => (m / 1000).toFixed(1);
  const n0 = (x) => Math.round(x).toLocaleString("en-US");
  const G = {
    fish: (s, h) => { const f = []; chk(h.mean_amb <= 26, `mean ambient ${h.mean_amb.toFixed(1)} C is above the 26 C limit for fish tanks`, f); chk(h.gt30 < 1500, `${n0(h.gt30)} h above 30 C (limit under 1,500 h)`, f);
      chk(s.slope_deg <= 8, `slope ${s.slope_deg} deg (limit 8 deg)`, f); chk(s.flat_land_m2 >= 10000, `flat land ${n0(s.flat_land_m2)} m2, needs 10,000 m2 for RAS tanks`, f); chk(s.d_water_m <= 3000, `water intake ${km(s.d_water_m)} km away (limit 3 km)`, f);
      chk(s.wsi_index < 4.0, `water stress ${s.wsi_index} (must be under 4.0)`, f); chk(s.q_dc_mw >= 0.5, `heat source ${s.q_dc_mw} MW (needs 0.5 MW)`, f);
      chk(s.ind_zoning === 1, "needs industrial or rural zoning; fish farms are not permitted in urban or commercial zones", f); return f; },
    dh: (s, h) => { const f = []; chk(h.lt15 >= 2000, `only ${n0(h.lt15)} h below 15 C (needs 2,000 h of heating demand)`, f);
      if (s.is_greenfield === 1) { chk(s.d_dh_m <= 3000, `heat network ${km(s.d_dh_m)} km away (limit 3 km for a new build)`, f); chk(s.rho_heat_mwh_m >= 1.5, `heat density ${s.rho_heat_mwh_m} MWh/m/yr (needs 1.5 for a new build)`, f); }
      else { chk(s.has_existing_dh === 1, "no existing district heating network to connect to (existing site)", f); chk(s.d_dh_m <= 800, `heat network ${n0(s.d_dh_m)} m away (limit 800 m for an existing site)`, f); chk(s.rho_heat_mwh_m >= 2.5, `heat density ${s.rho_heat_mwh_m} MWh/m/yr (needs 2.5 for an existing site)`, f); }
      return f; },
    biogas: (s, h) => { const f = []; chk(h.lt25 >= 2500, `only ${n0(h.lt25)} h below 25 C (needs 2,500 h)`, f); chk(s.d_bio_m <= 25000, `feedstock ${km(s.d_bio_m)} km away (limit 25 km)`, f); chk(s.slope_deg <= 10, `slope ${s.slope_deg} deg (limit 10 deg)`, f);
      chk(s.ind_zoning === 1, "needs industrial or agricultural zoning; digesters are not permitted in urban or commercial zones", f); return f; },
    absorption: (s, h) => { const f = []; chk(h.max_tdc >= 65, `coolant peaks at ${h.max_tdc.toFixed(1)} C; absorption chillers need 65 C`, f); chk(h.gt24 >= 1500, `only ${n0(h.gt24)} h above 24 C (needs 1,500 h of cooling demand)`, f); chk(s.wsi_index < 3.8, `water stress ${s.wsi_index} (must be under 3.8)`, f); return f; },
    orc: (s, h) => { const f = []; chk(h.min_tdc >= 80, `coolant drops to ${h.min_tdc.toFixed(1)} C; ORC power needs 80 C all year`, f); chk(h.lt30 >= 5000, `only ${n0(h.lt30)} h below 30 C (needs 5,000 h for condenser cooling)`, f); return f; },
    dac: (s, h) => { const f = []; chk(s.d_co2_m <= 50000, `CO2 storage or user ${km(s.d_co2_m)} km away (limit 50 km)`, f); chk(h.gt35 < 1500, `${n0(h.gt35)} h above 35 C (limit under 1,500 h)`, f); return f; },
    btes: (s, h) => { const f = []; gf(s, f); chk(s.geo_storage_score >= 3, `ground storage score ${s.geo_storage_score} of 5 (needs 3)`, f); chk(h.lt15 >= 2500, `only ${n0(h.lt15)} h below 15 C (needs 2,500 h)`, f); chk(h.gt20 >= 1000, `only ${n0(h.gt20)} h above 20 C (needs 1,000 h to charge the store)`, f); return f; },
    feedwater: (s, h) => { const f = []; gf(s, f); chk(s.d_pp_m <= 1500, `power plant ${km(s.d_pp_m)} km away (limit 1.5 km)`, f); chk(s.q_fw_mw >= 2.0, `feedwater heat demand ${s.q_fw_mw} MW (needs 2 MW)`, f); return f; },
    desal: (s, h) => { const f = []; gf(s, f); chk(s.d_coast_m <= 5000, `coast ${km(s.d_coast_m)} km away (limit 5 km)`, f); chk(s.dz_m <= 50, `site ${s.dz_m} m above the sea (limit 50 m pumping head)`, f); chk(s.wsi_index >= 2.0, `water stress ${s.wsi_index}; under 2.0 there is no need for desalinated water`, f); return f; },
    biomass: (s, h) => { const f = []; gf(s, f); chk(s.d_bio_m <= 25000, `feedstock ${km(s.d_bio_m)} km away (limit 25 km)`, f); chk(s.ind_zoning === 1, "needs industrial zoning", f); chk(s.slope_deg <= 10, `slope ${s.slope_deg} deg (limit 10 deg)`, f); return f; },
    drying: (s, h) => { const f = []; gf(s, f); chk(s.ind_zoning === 1, "needs industrial zoning", f); chk(s.q_dc_mw >= 5.0, `heat source ${s.q_dc_mw} MW (needs 5 MW)`, f); chk(s.slope_deg <= 8, `slope ${s.slope_deg} deg (limit 8 deg)`, f); return f; },
    snowmelt: (s, h) => { const f = []; gf(s, f); chk(s.campus_area_m2 >= 20000, `paved area ${n0(s.campus_area_m2)} m2 (needs 20,000 m2)`, f); chk(h.le2 >= 800, `only ${n0(h.le2)} h at or below 2 C (needs 800 h)`, f); return f; },
    greenhouse: (s, h) => { const f = []; gf(s, f); chk(s.agri_land_m2 >= 20000, `farm land ${n0(s.agri_land_m2)} m2 (needs 20,000 m2)`, f); chk(s.slope_deg <= 6, `slope ${s.slope_deg} deg (limit 6 deg)`, f); chk(s.wsi_index < 4.0, `water stress ${s.wsi_index} (must be under 4.0)`, f); chk(h.lt18 >= 2000, `only ${n0(h.lt18)} h below 18 C (needs 2,000 h)`, f); return f; },
  };
  const areaCap = (k, w) => s => Math.min(1, s[k] * w / 1e6 / s.q_dc_mw);
  const O = (id, key, name, mode, t_sink, demand, product, capex, pipe, dist_key, dist_max, market, wf, li, cap, gate) =>
    ({ id, key, name, mode, t_sink, demand, product, capex_usd_kw: capex, pipe_usd_m: pipe, dist_key, dist_max_m: dist_max, market_sensitive: market, water_factor: wf, local_impact: li, cap, gate });
  const OPTIONS = [
    O(1, "fish_farm_ras", "Fish Farm (RAS)", "both", 28, ["heating", 28, 20, 0.2], "heat", 900, 600, "d_water_m", 3000, true, 0.6, 0.8, areaCap("flat_land_m2", 250), G.fish),
    O(2, "district_heating", "District Heating", "adaptive", 65, ["heating", 15, 20, 0.15], "heat", 250, 1500, "d_dh_m", 3000, false, 0.1, 0.2, s => Math.min(1, s.rho_heat_mwh_m / 3.0), G.dh),
    O(3, "biogas", "Biogas Generator", "both", 38, ["heating", 25, 25, 0.3], "heat", 700, 300, "d_bio_m", 25000, false, 0.3, 0.5, () => 0.3, G.biogas),
    O(4, "absorption_cooling", "Absorption Cooling", "both", 85, ["cooling", 24, 10], "cooling", 450, 0, null, 1, false, 0.8, 0.4, () => 1, G.absorption),
    O(5, "orc", "Organic Rankine Cycle", "both", 100, ["constant", 0.9], "power", 2500, 0, null, 1, false, 0.5, 0.3, () => 1, G.orc),
    O(6, "dac", "Carbon Capture / DAC", "both", 90, ["constant", 0.85], "co2", 1500, 400, "d_co2_m", 50000, false, 0.2, 0.2, () => 1, G.dac),
    O(7, "btes_ates", "BTES / ATES Storage", "greenfield", 55, ["constant", 0.7], "stored_heat", 600, 0, null, 1, false, 0.3, 0.6, () => 1, G.btes),
    O(8, "feedwater_preheat", "Boiler Feedwater Preheat", "greenfield", 55, ["constant", 0.85], "steam", 200, 800, "d_pp_m", 1500, false, 0.2, 0.3, s => Math.min(1, s.q_fw_mw / s.q_dc_mw), G.feedwater),
    O(9, "desalination", "Desalination (MED/MD)", "greenfield", 70, ["constant", 0.9], "water", 1200, 900, "d_coast_m", 5000, false, -1.0, 1.0, () => 1, G.desal),
    O(10, "biomass_processing", "Biomass Processing", "greenfield", 65, ["constant", 0.7], "heat", 500, 0, "d_bio_m", 25000, true, 0.3, 0.5, () => 0.6, G.biomass),
    O(11, "industrial_drying", "Industrial Drying", "greenfield", 75, ["constant", 0.8], "heat", 450, 0, null, 1, false, 0.4, 0.4, () => 1, G.drying),
    O(12, "snow_melt", "Radiant / Snow-Melt", "greenfield", 35, ["heating", 2, 10, 0.0], "heat", 350, 0, null, 1, false, 0.1, 0.2, areaCap("campus_area_m2", 400), G.snowmelt),
    O(13, "greenhouse", "Co-Designed Greenhouse", "greenfield", 40, ["heating", 18, 25, 0.1], "heat", 400, 0, null, 1, true, 0.7, 0.4, areaCap("agri_land_m2", 300), G.greenhouse),
  ];
  function demand(o, tamb) {
    const d = o.demand;
    if (d[0] === "heating") return tamb.map(t => clip((d[1] - t) / d[2], d[3], 1));
    if (d[0] === "cooling") return tamb.map(t => clip((t - d[1]) / d[2], 0, 1));
    return new Float64Array(HOURS).fill(d[1]);
  }
  const grade = e => GRADE_BANDS.find(([lo]) => e >= lo)[1];

  function climateStats(tamb, tdc) {
    const cnt = f => { let n = 0; for (const t of tamb) if (f(t)) n++; return n; };
    return {
      mean_amb: sum(tamb) / HOURS, gt20: cnt(t => t > 20), gt24: cnt(t => t > 24), gt30: cnt(t => t > 30), gt35: cnt(t => t > 35),
      lt15: cnt(t => t < 15), lt18: cnt(t => t < 18), lt25: cnt(t => t < 25), lt30: cnt(t => t < 30), le2: cnt(t => t <= 2),
      min_tdc: Math.min(...tdc), max_tdc: Math.max(...tdc),
    };
  }

  function evaluateOption(o, s, tamb, tdc, h) {
    const fails = o.gate(s, h), gate = fails.length ? 0 : 1, q = s.q_dc_mw;
    const cap = clip(o.cap(s), 0, 1);
    const raw = demand(o, tamb);
    const qsrc = raw.map(u => q * u * cap * C.availability);
    let qdel, whp, cop = null, direct = null, meanEta = null, pThermo;
    if (o.key === "orc") {
      qdel = new Float64Array(HOURS); whp = new Float64Array(HOURS);
      for (let i = 0; i < HOURS; i++) {
        const carnot = Math.max(1 - (tamb[i] + C.orc_cond_offset_c + 273.15) / (tdc[i] + 273.15), 0);
        qdel[i] = qsrc[i] * C.orc_eta_frac * carnot;
      }
      const Qs0 = sum(qsrc); meanEta = Qs0 > 0 ? sum(qdel) / Qs0 : 0;
      pThermo = 5 * lin(meanEta, 0, 0.12);
    } else {
      [cop, direct] = heatPump(tdc, o.t_sink);
      whp = qsrc.map((v, i) => direct[i] ? 0 : v / (cop[i] - 1));
      qdel = qsrc.map((v, i) => v + whp[i]);
      const Qd0 = sum(qdel), free = Qd0 > 0 ? 1 - sum(whp) / Qd0 : 0;
      pThermo = 5 * lin(free, 0.0, 1.0);
    }
    const Qs = sum(qsrc), Qd = sum(qdel), W = sum(whp);

    let active = 0, hot = 0;
    for (let i = 0; i < HOURS; i++) { if (raw[i] >= 0.2) active++; if (tamb[i] > 35) hot++; }
    const pClimate = 5 * Math.min(1, (active / HOURS) / 0.6) * (1 - 0.5 * hot / HOURS);
    const util = Qs / (q * HOURS);
    const distPen = o.dist_key ? 1 - 0.5 * Math.min(1, s[o.dist_key] / o.dist_max_m) : 1;
    const pUtil = 5 * util * distPen;

    const pf = s.p_fuel_usd_kwh * 1000, pe = s.p_elec_usd_kwh * 1000, ciF = s.ci_fuel_g_kwh, ciG = s.ci_grid_g_kwh;
    let qty = Qd, unit = "MWh_th", value, abated;
    switch (o.product) {
      case "heat": value = Qd * pf / C.boiler_eff; abated = Qd * ciF / C.boiler_eff; break;
      case "stored_heat": { const dl = Qd * C.btes_round_trip; value = dl * pf / C.boiler_eff; abated = dl * ciF / C.boiler_eff; qty = dl; break; }
      case "steam": value = Qd * s.p_steam_usd_mwh; abated = Qd * ciF / C.boiler_eff; break;
      case "cooling": { const cool = Qd * C.absorption_cop, es = cool / C.chiller_cop; value = es * pe; abated = es * ciG; qty = cool; unit = "MWh_cool"; break; }
      case "power": value = Qd * pe; abated = Qd * ciG; unit = "MWh_e"; break;
      case "water": { const m3 = Qd * 1000 / C.med_kwh_th_m3; value = m3 * s.p_water_usd_m3; abated = m3 * C.ro_kwh_e_m3 / 1000 * ciG; qty = m3; unit = "m3"; break; }
      case "co2": { const t = Qd / C.dac_mwh_th_t; value = t * s.p_co2_usd_ton; abated = t * 1000; qty = t; unit = "tCO2"; break; }
    }
    if (o.market_sensitive) value *= 1 - 0.3 * Math.min(1, s.d_market_m / C.market_ref_m);
    const netAbated = (abated - W * ciG) / 1000;
    const carbonRev = o.product === "co2" ? 0 : Math.max(netAbated, 0) * s.p_co2_usd_ton;
    const hpCost = W * pe;
    const peakSrcKw = q * cap * 1000;
    const peakHpKw = W > 0 ? Math.max(...qdel) * 1000 : 0;
    const dist = o.dist_key ? s[o.dist_key] : 0;
    const capex = peakSrcKw * o.capex_usd_kw + dist * o.pipe_usd_m + (W > 0 ? peakHpKw * C.hp_capex_usd_kw : 0);
    const netAnnual = value + carbonRev - hpCost - C.opex_frac * capex;
    const payback = netAnnual > 0 ? capex / netAnnual : Infinity;
    const pEcon = netAnnual <= 0 ? 0 : 5 * lin(payback, C.payback_worst_yr, C.payback_best_yr);
    const rawV = 0.30 * pThermo + 0.30 * pClimate + 0.25 * pEcon + 0.15 * pUtil;
    const viability = r(gate * rawV, 2);

    const intensity = Qd > 0 ? netAbated * 1000 / Qd : 0;
    const ghgRef = s.ci_fuel_g_kwh / C.boiler_eff;
    const eGhg = intensity <= 0 || ghgRef <= 0 ? 1 : 1 + 4 * lin(intensity, 0, ghgRef);
    const mit = C.mit_mult[s.mit_tier];
    const waterCredit = 0.8 * s.wsi_index * Math.min(util, 1) * (s.baseline_evaporative || 0);
    const eWater = clip(5 - 0.8 * s.wsi_index * o.water_factor * mit + waterCredit, 1, 5);
    const eLocal = clip(5 - o.local_impact * (s.eco_sens_index - 1) * mit, 1, 5);
    const eco = r(0.40 * eGhg + 0.30 * eWater + 0.30 * eLocal, 2);

    let meanCop = null, directHours = 0;
    if (cop) {
      let wsum = 0, csum = 0;
      for (let i = 0; i < HOURS; i++) {
        if (qsrc[i] <= 0) continue;
        if (Number.isFinite(cop[i])) { wsum += qsrc[i]; csum += cop[i] * qsrc[i]; } else directHours++;
      }
      meanCop = wsum > 0 ? csum / wsum : null;
    }
    return {
      id: o.id, key: o.key, name: o.name, mode: o.mode, t_sink_c: o.t_sink,
      ko_pass: !!gate, ko_failures: fails, viability, viability_ungated: r(rawV, 2),
      subscores: { p_thermo: r2(pThermo), p_climate: r2(pClimate), p_econ: r2(pEcon), p_util: r2(pUtil) },
      eco_score: eco, eco_grade: grade(eco),
      eco_subscores: { e_ghg: r2(eGhg), e_water: r2(eWater), e_local: r2(eLocal) },
      annual: {
        q_src_mwh: r(Qs, 1), q_del_mwh: r(Qd, 1), w_hp_mwh: r(W, 1), product_qty: r(qty, 1), product_unit: unit,
        direct_hx_hours: directHours, mean_cop: r2(meanCop), orc_mean_eta: r2(meanEta), net_abated_tco2: r(netAbated, 1),
        revenue_usd: Math.round(value + carbonRev), hp_elec_cost_usd: Math.round(hpCost), capex_usd: Math.round(capex),
        net_annual_usd: Math.round(netAnnual), payback_yr: r2(payback),
        capex_plant_usd: Math.round(peakSrcKw * o.capex_usd_kw), capex_pipe_usd: Math.round(dist * o.pipe_usd_m),
        capex_hp_usd: Math.round(W > 0 ? peakHpKw * C.hp_capex_usd_kw : 0), value_usd: Math.round(value), carbon_rev_usd: Math.round(carbonRev),
        utilisation: r(util, 4), cap_fraction: r(cap, 4),
      },
    };
  }

  const sortResults = res => { res.sort((a, b) => (b.viability - a.viability) || (b.eco_score - a.eco_score) || (a.id - b.id)); res.forEach((x, i) => x.rank = i + 1); return res; };

  function evaluate(site, tmin, tmax) {
    const s = validateSite(site); const [mn, mx, warns] = normalizeClimate(tmin, tmax);
    const tamb = expandDiurnal(mn, mx), tdc = coolant(s, tamb), h = climateStats(tamb, tdc);
    return { version: VERSION, warnings: warns, climate_summary: h, options: sortResults(OPTIONS.map(o => evaluateOption(o, s, tamb, tdc, h))) };
  }

  function whatIfSummary(s, baseline, upgraded, preset) {
    const p = DSX_PRESETS[preset];
    const b = Object.fromEntries(baseline.options.map(x => [x.key, x])), u = Object.fromEntries(upgraded.options.map(x => [x.key, x]));
    const deltas = Object.keys(b).map(k => ({
      key: k, name: b[k].name, viability_before: b[k].viability, viability_after: u[k].viability,
      viability_gain: r(u[k].viability - b[k].viability, 2),
      hp_mwh_saved: r(b[k].annual.w_hp_mwh - u[k].annual.w_hp_mwh, 1),
      hp_cost_saved_usd: b[k].annual.hp_elec_cost_usd - u[k].annual.hp_elec_cost_usd,
      unlocked: !b[k].ko_pass && u[k].ko_pass, lost: b[k].ko_pass && !u[k].ko_pass,
    })).sort((a, c) => (c.viability_gain - a.viability_gain) || a.key.localeCompare(c.key));
    const tb = baseline.options[0].viability > 0 ? baseline.options[0] : null;
    const tu = upgraded.options[0].viability > 0 ? upgraded.options[0] : null;
    return {
      preset, preset_label: p.label,
      already_at_or_above_preset: s.cooling_type === "liquid" && s.t_dc_base_c >= p.t_dc_base_c,
      baseline_top: tb && { key: tb.key, name: tb.name, viability: tb.viability },
      upgraded_top: tu && { key: tu.key, name: tu.name, viability: tu.viability },
      top_option_gain: tb ? deltas.find(d => d.key === tb.key) : null,
      unlocked: deltas.filter(d => d.unlocked).map(d => d.name), lost: deltas.filter(d => d.lost).map(d => d.name),
      deltas, upgraded,
    };
  }

  // Event stream mirroring server.py, so the UI can watch each stage.
  function* runPipeline({ site, climate, what_if = true, preset = WHAT_IF_PRESET }) {
    const t0 = performance.now(), ms = () => Math.round((performance.now() - t0) * 10) / 10;
    const ev = (event, o) => ({ event, t_ms: ms(), ...o });
    yield ev("stage", { stage: 0, status: "start", msg: "Validating 31 inputs and climate series" });
    const s = validateSite(site);
    const [mn, mx, warns] = normalizeClimate(climate.t_min, climate.t_max);
    for (const w of warns) yield ev("log", { level: "warn", msg: w });
    yield ev("stage", { stage: 0, status: "done", msg: "Inputs valid" });

    function* stream(site, label) {
      yield ev("stage", { stage: 1, status: "start", msg: `[${label}] Expanding 365 days → 8,760 h diurnal profile` });
      const tamb = expandDiurnal(mn, mx), tdc = coolant(site, tamb), h = climateStats(tamb, tdc);
      yield ev("log", { msg: `[${label}] Ambient mean ${h.mean_amb.toFixed(1)} °C · ${h.lt15.toLocaleString()} h <15 °C · ${h.gt30.toLocaleString()} h >30 °C · coolant ${h.min_tdc.toFixed(0)}–${h.max_tdc.toFixed(0)} °C` });
      yield ev("stage", { stage: 1, status: "done", msg: `[${label}] Physics ready` });
      if (label === "baseline") {
        const daily = (a, f) => Array.from({ length: 365 }, (_, d) => r(f(a.slice(d * 24, d * 24 + 24)), 2));
        yield ev("climate", { series: { amb_min: daily(tamb, x => Math.min(...x)), amb_max: daily(tamb, x => Math.max(...x)),
          amb_mean: daily(tamb, x => sum(x) / 24), tdc_max: daily(tdc, x => Math.max(...x)) }, stats: h });
      }
      yield ev("stage", { stage: 2, status: "start", msg: `[${label}] Gating & scoring 13 pathways` });
      const res = [];
      for (const o of OPTIONS) {
        const x = evaluateOption(o, site, tamb, tdc, h); res.push(x);
        yield ev("option", { which: label, id: o.id, name: o.name, ko_pass: x.ko_pass, viability: x.viability, eco_grade: x.eco_grade,
          msg: `[${label}] #${o.id} ${o.name}: ${x.ko_pass ? "pass" : "KO: " + x.ko_failures[0]}${x.ko_pass ? ` · viability ${x.viability.toFixed(2)}` : ""} · eco ${x.eco_grade}` });
      }
      sortResults(res);
      yield ev("stage", { stage: 2, status: "done", msg: `[${label}] ${res.filter(x => x.ko_pass).length} of 13 pass KO gates` });
      return { version: VERSION, warnings: warns, climate_summary: h, options: res };
    }
    const baseline = yield* stream(s, "baseline");
    yield ev("stage", { stage: 3, status: "done", msg: "Dual grades computed" });
    yield ev("result", { which: "baseline", result: baseline });
    if (what_if) {
      const p = DSX_PRESETS[preset];
      yield ev("stage", { stage: 4, status: "start", msg: `What-if: upgrading to ${p.label}` });
      const up = { ...s, cooling_type: p.cooling_type, t_dc_base_c: Math.max(s.t_dc_base_c, p.t_dc_base_c) };
      const upgraded = yield* stream(up, "what-if");
      const wi = whatIfSummary(s, baseline, upgraded, preset);
      yield ev("stage", { stage: 4, status: "done", msg: `What-if complete · unlocked: ${wi.unlocked.join(", ") || "none"}` });
      yield ev("result", { which: "what_if", result: wi });
    }
    yield ev("done", { msg: `Finished in ${ms().toFixed(0)} ms` });
  }

  return { VERSION, C, INPUT_SPEC, DSX_PRESETS, WHAT_IF_PRESET, OPTIONS, InputError, evaluate, whatIfSummary, validateSite, runPipeline };
})();
