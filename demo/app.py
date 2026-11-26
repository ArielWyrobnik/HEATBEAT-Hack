"""HEATBEAT demo: pick a data center, see every input the model would be fed, and check the pipeline.

Run from the repository root:
    pip install -r requirements.txt -r demo/requirements.txt
    streamlit run demo/app.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import plotly.express as px  # noqa: E402
import plotly.graph_objects as go  # noqa: E402
import streamlit as st  # noqa: E402

import heatbeat_data as hd  # noqa: E402
from data_pipeline.common import REGION_TZ, YEAR, hourly_index, load_grid_regions, load_sites  # noqa: E402
from demo import checks as ck  # noqa: E402
from demo import live  # noqa: E402

st.set_page_config(page_title="HEATBEAT input overview", layout="wide")

BADGE = {ck.REAL: "🟢 real", ck.DERIVED: "🔵 derived", ck.ESTIMATED: "🟠 estimated",
         ck.SYNTHETIC: "🔴 synthetic", ck.USER: "⚪ user input"}
HOURS = len(hourly_index())
CUSTOM = "Custom location (enter coordinates)"


# ---------------------------------------------------------------- data access (cached)

@st.cache_data(show_spinner=False)
def db_status() -> dict:
    try:
        m = hd.meta()
        return {"ok": True, **m}
    except FileNotFoundError as exc:
        return {"ok": False, "error": str(exc)}


@st.cache_data(show_spinner=False)
def site_table() -> pd.DataFrame:
    return hd.list_sites() if db_status()["ok"] else load_sites()


@st.cache_data(show_spinner=False)
def stored_site(site_id: str):
    s = hd.get_site(site_id)
    return s.meta, s.grid, s.weather, s.prices


@st.cache_data(show_spinner=False)
def stored_region(grid_region_id: str):
    g = hd.list_grid_regions()
    grid = g[g["grid_region_id"] == grid_region_id].iloc[0].to_dict()
    prices = hd._hourly("price_hourly", "grid_region_id", grid_region_id)
    return grid, prices


@st.cache_data(show_spinner=False)
def source_table() -> pd.DataFrame:
    return hd.sources().set_index("source_id") if db_status()["ok"] else pd.DataFrame()


@st.cache_data(show_spinner=False, ttl=3600)
def live_weather(lat: float, lon: float, with_nasa: bool):
    log = live.CallLog()
    om = live.open_meteo_weather(lat, lon, log)
    elev = live.elevation(lat, lon, log)
    nasa = live.nasa_power_weather(lat, lon, log) if with_nasa else None
    return om, elev, nasa, log.frame()


@st.cache_data(show_spinner=False, ttl=3600)
def live_prices(iso: str, location: str):
    log = live.CallLog()
    s = live.iso_prices_week(iso, location, log)
    return s, log.frame()


def src_name(source_id) -> str:
    t = source_table()
    if source_id is None or (isinstance(source_id, float) and np.isnan(source_id)):
        return "n/a"
    if not t.empty and source_id in t.index:
        return f"{t.loc[source_id, 'name']} ({source_id})"
    return str(source_id)


def nn(v):
    return None if v is None or (isinstance(v, float) and np.isnan(v)) else v


# ---------------------------------------------------------------- sidebar: selection

status = db_status()
sites = site_table()
regions = load_grid_regions()
profiles = hd.cooling_profiles()

st.sidebar.title("HEATBEAT")
st.sidebar.caption("Input overview and pipeline check")
if not status["ok"]:
    st.sidebar.error("No stored database found. Only live calls and the curated CSV files are available. "
                     "Pull the Parquet files from the repo or run `python -m data_pipeline.build_db`.")
elif status.get("build_mode") != "online":
    st.sidebar.warning(f"Stored database was built in **{status.get('build_mode')}** mode: weather and prices in "
                       "it are synthetic placeholders. Pull the real build from GitHub Actions.")
else:
    st.sidebar.success(f"Stored database: real build from {status.get('built_utc', '')[:16]} UTC")

names = sites.sort_values(["country_iso2", "name"])
labels = [CUSTOM] + [f"{r.country_iso2} · {r.name}" for r in names.itertuples()]
label_to_id = {f"{r.country_iso2} · {r.name}": r.site_id for r in names.itertuples()}

if "pick" not in st.session_state:
    il = [lab for lab in labels if lab.startswith("IL ")]
    st.session_state.pick = il[0] if il else labels[1]

pick = st.sidebar.selectbox("Data center", labels, key="pick")
is_custom = pick == CUSTOM

if is_custom:
    c1, c2 = st.sidebar.columns(2)
    lat = c1.number_input("Latitude", -90.0, 90.0, 31.25, format="%.4f")
    lon = c2.number_input("Longitude", -180.0, 180.0, 34.79, format="%.4f")
    d2 = (sites["lat"] - lat) ** 2 + ((sites["lon"] - lon) * np.cos(np.radians(lat))) ** 2
    nearest = sites.loc[d2.idxmin()]
    rid_list = regions["grid_region_id"].tolist()
    region_id = st.sidebar.selectbox("Grid region (prices, carbon)", rid_list,
                                     index=rid_list.index(nearest["grid_region_id"]),
                                     help=f"Default: region of the nearest known site, {nearest['name']}")
    prof_ids = profiles["cooling_profile_id"].tolist()
    prof_id = st.sidebar.selectbox("Cooling profile", prof_ids, index=prof_ids.index("dlc_warm")
                                   if "dlc_warm" in prof_ids else 0)
    it_mw = st.sidebar.number_input("Average IT load (MW)", 0.1, 5000.0, 50.0)
    pue = st.sidebar.number_input("PUE", 1.0, 2.5, 1.25)
    site_id, site_name = None, f"Custom location {lat:.3f}, {lon:.3f}"
else:
    site_id = label_to_id[pick]
    row = sites[sites["site_id"] == site_id].iloc[0]
    lat, lon, region_id, site_name = float(row["lat"]), float(row["lon"]), row["grid_region_id"], row["name"]

st.sidebar.divider()
st.sidebar.subheader("Live calls")
do_live = st.sidebar.toggle("Open-Meteo weather + elevation (no key)", value=True)
do_nasa = st.sidebar.toggle("NASA POWER cross-check (slow, 20 to 60 s)", value=False)
iso = regions.set_index("grid_region_id").loc[region_id, "iso_rto"]
lmp_loc = regions.set_index("grid_region_id").loc[region_id, "lmp_location"]
can_live_price = isinstance(iso, str) and iso in live.LIVE_PRICE_ISOS and isinstance(lmp_loc, str)
do_price = st.sidebar.toggle(f"gridstatus {iso if isinstance(iso, str) else ''} prices, 1 week (no key)",
                             value=False, disabled=not can_live_price,
                             help="Only for CAISO, MISO, NYISO, ISO-NE and SPP regions")
if st.sidebar.button("Clear live cache and refetch"):
    live_weather.clear()
    live_prices.clear()

# ---------------------------------------------------------------- load everything

calls = []
w_live = elev = w_nasa = None
with st.spinner("Calling APIs ..."):
    if do_live or do_nasa:
        w_live, elev, w_nasa, log_df = live_weather(round(lat, 4), round(lon, 4), do_nasa)
        if not do_live:
            w_live = None
        calls.append(log_df)
    p_live = None
    if do_price and can_live_price:
        p_live, log_df = live_prices(iso, lmp_loc)
        calls.append(log_df)
call_log = pd.concat(calls, ignore_index=True) if calls else pd.DataFrame()

meta, grid, w_db, prices = {}, {}, None, None
if status["ok"]:
    if site_id:
        meta, grid, w_db, prices = stored_site(site_id)
    else:
        grid, prices = stored_region(region_id)

if w_live is not None:
    weather, w_origin = w_live, "LIVE"
    w_src = "open_meteo_era5"
elif w_db is not None and not w_db.empty:
    weather, w_origin = w_db, "DB"
    w_src = w_db["source"].iloc[0]
else:
    weather, w_origin, w_src = None, "missing", None

tz = REGION_TZ.get(region_id, "UTC")

if site_id:
    hp = hd.heat_profile(site_id)
    hp_kind, hp_origin = ck.heat_kind(hp.get("evidence"), hp.get("is_assumed")), "CSV"
else:
    pr = profiles[profiles["cooling_profile_id"] == prof_id].iloc[0].to_dict()
    hp = {**{k: nn(v) for k, v in pr.items()}, "it_load_mw": it_mw, "it_load_mw_low": it_mw,
          "it_load_mw_high": it_mw, "pue_assumed": pue, "chip_family": pr.get("chip_family_typical"),
          "facility_power_mw": round(it_mw * pue, 1), "evidence": "user", "confidence": "n/a"}
    share = hp.get("liquid_heat_share") or 0.0
    hp["recoverable_heat_mw_liquid"] = round(it_mw * share, 1)
    hp["recoverable_heat_mw_air"] = round(it_mw * (1 - share), 1)
    hp_kind, hp_origin = ck.USER, "user + CSV"

# ---------------------------------------------------------------- header + map

st.title(site_name)
info = []
if meta:
    info.append(f"**Operator:** {meta.get('operator') or 'n/a'}")
    info.append(f"**Coordinates:** {lat:.4f}, {lon:.4f} ({meta.get('coord_precision')})")
    if meta.get("is_hypothetical"):
        info.append("**Hypothetical site**")
else:
    info.append(f"**Coordinates:** {lat:.4f}, {lon:.4f}")
info.append(f"**Grid region:** {region_id} · **Local time zone:** {tz}")
if elev is not None:
    info.append(f"**Elevation (live):** {elev:.0f} m")
st.markdown(" · ".join(info))

m = sites[["site_id", "name", "lat", "lon"]].copy()
m["selected"] = m["site_id"] == site_id
if is_custom:
    m = pd.concat([m, pd.DataFrame([{"site_id": "custom", "name": site_name, "lat": lat, "lon": lon,
                                     "selected": True}])], ignore_index=True)
fig = px.scatter_map(m, lat="lat", lon="lon", hover_name="name", color="selected",
                     color_discrete_map={True: "#d62728", False: "#1f77b4"}, size=np.where(m["selected"], 14, 7),
                     size_max=14, zoom=1, height=330)
fig.update_layout(margin=dict(l=0, r=0, t=0, b=0), showlegend=False, map_style="carto-positron")
st.plotly_chart(fig, width="stretch")

# ---------------------------------------------------------------- model input table


def kpis(w: pd.DataFrame) -> dict:
    return {"t_mean": w["t_db_c"].mean(), "t_min": w["t_db_c"].min(), "t_max": w["t_db_c"].max(),
            "wb_p99": w["t_wb_c"].quantile(0.99), "fc_hours": int((w["t_wb_c"] < 18).sum()),
            "hdh": float((18 - w["t_db_c"]).clip(lower=0).sum()), "ghi": w["ghi_wm2"].mean(),
            "wind": w["wind_ms"].mean(), "rh": w["rh_pct"].mean()}


rows = []


def add(group, param, value, unit, kind, origin, source):
    rows.append({"group": group, "input": param, "value": value, "unit": unit, "status": BADGE[kind],
                 "from": origin, "source": source})


if weather is not None:
    k = kpis(weather)
    wk = ck.source_kind(w_src)
    ws = src_name(w_src)
    add("Weather", "Hourly profile (8784 h): t_db, RH, dew point, wind, GHI", f"{weather['t_db_c'].notna().sum()} h",
        "", wk, w_origin, ws)
    add("Weather", "Annual mean dry bulb", round(k["t_mean"], 1), "C", wk, w_origin, ws)
    add("Weather", "Min / max dry bulb", f"{k['t_min']:.1f} / {k['t_max']:.1f}", "C", wk, w_origin, ws)
    add("Weather", "Mean relative humidity", round(k["rh"], 0), "%", wk, w_origin, ws)
    add("Weather", "Wet bulb, 99th percentile", round(k["wb_p99"], 1), "C", ck.DERIVED, w_origin,
        "Stull (2011) from t_db and RH")
    add("Weather", "Free cooling hours (wet bulb < 18 C)", k["fc_hours"], "h/yr", ck.DERIVED, w_origin, "computed")
    add("Weather", "Heating degree hours (base 18 C)", f"{k['hdh']:,.0f}", "Kh/yr", ck.DERIVED, w_origin,
        "computed; demand proxy for heat reuse")
    add("Weather", "Mean solar irradiance (GHI)", round(k["ghi"], 0), "W/m2", wk, w_origin, ws)
    add("Weather", "Mean wind speed (10 m)", round(k["wind"], 1), "m/s", wk, w_origin, ws)
else:
    add("Weather", "Hourly profile", "missing", "", ck.SYNTHETIC, "missing", "no live call and no stored data")

if prices is not None and not prices.empty:
    p = prices["price_usd_mwh"]
    pk = ck.SYNTHETIC if prices["is_synthetic"].mean() > 0.5 else ck.REAL
    ps = src_name(prices["source"].iloc[0])
    loc = prices.copy()
    loc.index = loc.index.tz_convert(tz)
    by_h = loc.groupby(loc.index.hour.rename("hour"))["price_usd_mwh"].mean()
    add("Electricity", f"Hourly price profile ({prices['price_kind'].iloc[0]})", f"{len(prices)} h", "", pk, "DB", ps)
    add("Electricity", "Mean hourly price", round(p.mean(), 1), "USD/MWh", pk, "DB", ps)
    add("Electricity", "P10 / P90 hourly price", f"{p.quantile(.1):.1f} / {p.quantile(.9):.1f}", "USD/MWh", pk,
        "DB", ps)
    add("Electricity", "Most expensive local hour", int(by_h.idxmax()), "h", ck.DERIVED, "DB", "computed")
if grid:
    add("Electricity", "Retail industrial price (bill level)",
        nn(grid.get("retail_industrial_usd_mwh")) and round(grid["retail_industrial_usd_mwh"], 1), "USD/MWh",
        ck.source_kind(grid.get("retail_price_source"), grid.get("retail_price_is_synthetic")), "DB",
        src_name(grid.get("retail_price_source")))
    add("Carbon", "Grid carbon intensity (annual average)", nn(grid.get("co2_kg_mwh")) and round(grid["co2_kg_mwh"]),
        "kg CO2/MWh", ck.source_kind(grid.get("co2_source"), grid.get("co2_is_synthetic")), "DB",
        f"{src_name(grid.get('co2_source'))}, year {nn(grid.get('co2_year'))}")

hs = hp.get("source_ids") or ("user input" if is_custom else "")
add("Data center", "Average IT load (low / mid / high)",
    f"{hp.get('it_load_mw_low')} / {hp.get('it_load_mw')} / {hp.get('it_load_mw_high')}", "MW", hp_kind, hp_origin, hs)
add("Data center", "Facility power", hp.get("facility_power_mw"), "MW", ck.DERIVED, hp_origin,
    f"IT load x PUE {hp.get('pue_assumed')}")
add("Data center", "PUE", hp.get("pue_assumed"), "", hp_kind, hp_origin, hs)
add("Data center", "Chip family", hp.get("chip_family"), "", hp_kind, hp_origin, hs)
add("Data center", "Cooling type / profile", f"{hp.get('cooling_type')} / {hp.get('cooling_profile_id')}", "",
    hp_kind, hp_origin, hs)
add("Data center", "Facility water supply / return",
    f"{hp.get('facility_supply_temp_c')} / {hp.get('facility_return_temp_c')}", "C", ck.ESTIMATED, "CSV",
    "cooling_profiles.csv (vendor specs, typical values)")
add("Data center", "Exhaust air temperature", hp.get("exhaust_air_temp_c"), "C", ck.ESTIMATED, "CSV",
    "cooling_profiles.csv")
add("Data center", "Liquid heat share", hp.get("liquid_heat_share"), "0..1", ck.ESTIMATED, "CSV",
    "cooling_profiles.csv")
liq, air = hp.get("recoverable_heat_mw_liquid") or 0, hp.get("recoverable_heat_mw_air") or 0
add("Waste heat", f"Heat in liquid at {hp.get('facility_return_temp_c')} C", liq, "MW", ck.DERIVED, "computed",
    "IT load x liquid heat share")
add("Waste heat", f"Heat in air at {hp.get('exhaust_air_temp_c')} C", air, "MW", ck.DERIVED, "computed",
    "IT load x (1 - liquid share)")
add("Waste heat", "Annual waste heat (liquid + air, constant load)", f"{(liq + air) * HOURS:,.0f}", "MWh/yr",
    ck.DERIVED, "computed", f"MW x {HOURS} h; assumes flat load")
if grid and nn(grid.get("co2_kg_mwh")) and hp.get("facility_power_mw"):
    add("Carbon", "Electricity emissions (facility, flat load)",
        f"{hp['facility_power_mw'] * HOURS * grid['co2_kg_mwh'] / 1000:,.0f}", "t CO2/yr", ck.DERIVED, "computed",
        "facility MW x hours x grid intensity")

inputs = pd.DataFrame(rows)
inputs["value"] = inputs["value"].astype(str)

# ---------------------------------------------------------------- tabs

t_in, t_w, t_p, t_h, t_chk, t_api = st.tabs(["Model inputs", "Weather", "Electricity price", "Heat source",
                                             "Pipeline check", "API calls"])

with t_in:
    counts = inputs["status"].value_counts()
    cols = st.columns(len(BADGE))
    for c, (kind, lab) in zip(cols, BADGE.items()):
        c.metric(lab, int(counts.get(lab, 0)))
    st.dataframe(inputs, width="stretch", hide_index=True, height=min(40 + 35 * len(inputs), 900))
    st.caption("from: LIVE = fetched just now from the API, DB = stored database (built by GitHub Actions), "
               "CSV = curated file in data_pipeline/, computed = derived in this app. "
               "Status follows the source: estimated means a team estimate or unverified value, synthetic means "
               "a generated placeholder, not measured data.")
    st.download_button("Download this table (CSV)", inputs.to_csv(index=False), f"inputs_{site_id or 'custom'}.csv")


def daily_band(w: pd.DataFrame, name: str, color: str) -> list[go.Scatter]:
    loc = w["t_db_c"].tz_convert(tz)
    d = loc.resample("D").agg(["min", "mean", "max"])
    d = d[d.index.year == YEAR]  # drop the partial local day at the year boundary
    return [go.Scatter(x=d.index, y=d["max"], line=dict(width=0), showlegend=False, hoverinfo="skip"),
            go.Scatter(x=d.index, y=d["min"], fill="tonexty", line=dict(width=0), fillcolor=color.replace(")", ",0.18)").replace("rgb", "rgba"),
                       name=f"{name} daily min to max"),
            go.Scatter(x=d.index, y=d["mean"], line=dict(color=color, width=1.6), name=f"{name} daily mean")]


with t_w:
    if weather is None:
        st.info("No weather data. Turn on the live call or build the database.")
    else:
        fig = go.Figure(daily_band(weather, w_origin, "rgb(214,39,40)"))
        if w_db is not None and w_origin == "LIVE" and not w_db.empty:
            d = w_db["t_db_c"].tz_convert(tz).resample("D").mean()
            fig.add_trace(go.Scatter(x=d.index, y=d, name="DB daily mean", line=dict(color="rgb(31,119,180)",
                                                                                     width=1, dash="dot")))
        if w_nasa is not None:
            d = w_nasa["t_db_c"].tz_convert(tz).resample("D").mean()
            fig.add_trace(go.Scatter(x=d.index, y=d, name="NASA POWER daily mean",
                                     line=dict(color="rgb(44,160,44)", width=1)))
        wb = weather["t_wb_c"].tz_convert(tz).resample("D").mean()
        fig.add_trace(go.Scatter(x=wb.index, y=wb, name="wet bulb daily mean", line=dict(color="rgb(148,103,189)",
                                                                                         width=1)))
        fig.update_layout(title=f"Annual profile {YEAR}, dry bulb temperature (C), local days", height=420,
                          margin=dict(t=50, b=20), legend=dict(orientation="h", y=-0.15))
        st.plotly_chart(fig, width="stretch")

        loc = weather.copy()
        loc.index = loc.index.tz_convert(tz)
        c1, c2 = st.columns(2)
        hm = loc.groupby([loc.index.month.rename("month"), loc.index.hour.rename("hour")])["t_db_c"].mean().unstack()
        f2 = px.imshow(hm, aspect="auto", color_continuous_scale="RdBu_r", labels=dict(x="local hour", y="month",
                       color="C"), title="Typical day per month, dry bulb (C)")
        c1.plotly_chart(f2, width="stretch")
        prof = loc.groupby([loc.index.month.rename("month"), loc.index.hour.rename("hour")])["t_db_c"].mean().reset_index()
        prof.columns = ["month", "hour", "t_db_c"]
        prof = prof[prof["month"].isin([1, 4, 7, 10])]
        prof["month"] = prof["month"].map({1: "January", 4: "April", 7: "July", 10: "October"})
        f3 = px.line(prof, x="hour", y="t_db_c", color="month", title="Daily profile, selected months (C)",
                     labels=dict(hour="local hour", t_db_c="C"))
        c2.plotly_chart(f3, width="stretch")
        mon = loc.groupby(loc.index.month.rename("month")).agg({"t_db_c": ["mean", "min", "max"], "t_wb_c": "mean", "rh_pct": "mean",
                                      "ghi_wm2": "mean", "wind_ms": "mean"}).round(1)
        mon.columns = ["t_db mean", "t_db min", "t_db max", "t_wb mean", "RH %", "GHI W/m2", "wind m/s"]
        mon.index = pd.to_datetime(mon.index, format="%m").strftime("%b")
        st.dataframe(mon.T, width="stretch")

with t_p:
    if prices is None or prices.empty:
        st.info("No stored price data for this grid region.")
    else:
        kind = prices["price_kind"].iloc[0]
        syn = prices["is_synthetic"].mean()
        if syn > 0.5:
            st.warning(f"Price profile is **synthetic** ({syn:.0%} of hours): annual retail price times a generated "
                       "day and season shape. Use it for rough levels only, not for load shifting value.")
        elif kind == "wholesale_da_lmp":
            st.info("Real day-ahead wholesale prices. These exclude grid fees, capacity charges and taxes, so they "
                    "are lower than the bill. Use the retail price for the bill level and this for the shape.")
        loc = prices.copy()
        loc.index = loc.index.tz_convert(tz)
        d = loc["price_usd_mwh"].resample("D").agg(["min", "mean", "max"])
        d = d[d.index.year == YEAR]
        fig = go.Figure([go.Scatter(x=d.index, y=d["max"], line=dict(width=0), showlegend=False, hoverinfo="skip"),
                         go.Scatter(x=d.index, y=d["min"], fill="tonexty", line=dict(width=0),
                                    fillcolor="rgba(255,127,14,0.18)", name="daily min to max"),
                         go.Scatter(x=d.index, y=d["mean"], line=dict(color="rgb(255,127,14)"), name="daily mean")])
        if p_live is not None:
            pl = p_live.tz_convert(tz)
            fig.add_trace(go.Scatter(x=pl.index, y=pl, name="LIVE hourly (1 week)", line=dict(color="black", width=1)))
        fig.update_layout(title=f"Annual price profile {YEAR} ({kind}), USD/MWh", height=400, margin=dict(t=50, b=20),
                          legend=dict(orientation="h", y=-0.15))
        st.plotly_chart(fig, width="stretch")
        c1, c2 = st.columns(2)
        hm = loc.groupby([loc.index.month.rename("month"), loc.index.hour.rename("hour")])["price_usd_mwh"].mean().unstack()
        c1.plotly_chart(px.imshow(hm, aspect="auto", color_continuous_scale="YlOrRd",
                                  labels=dict(x="local hour", y="month", color="USD/MWh"),
                                  title="Average price by month and hour"), width="stretch")
        loc["day"] = np.where(loc.index.dayofweek >= 5, "weekend", "weekday")
        prof = loc.groupby(["day", loc.index.hour.rename("hour")])["price_usd_mwh"].mean().reset_index()
        prof.columns = ["day", "hour", "price"]
        c2.plotly_chart(px.line(prof, x="hour", y="price", color="day", title="Average daily profile",
                                labels=dict(hour="local hour", price="USD/MWh")), width="stretch")

with t_h:
    st.markdown(f"**Cooling profile:** {hp.get('cooling_profile_id')} · {hp.get('description', '')}")
    c = st.columns(4)
    c[0].metric("IT load (mid)", f"{hp.get('it_load_mw')} MW")
    c[1].metric("Facility power", f"{hp.get('facility_power_mw')} MW")
    c[2].metric("Heat in liquid", f"{liq} MW", help=f"at {hp.get('facility_return_temp_c')} C")
    c[3].metric("Heat in air", f"{air} MW", help=f"at {hp.get('exhaust_air_temp_c')} C")
    temps = pd.DataFrame({
        "stream": ["facility water supply", "facility water return", "exhaust air"],
        "min": [hp.get("facility_supply_temp_c_min"), hp.get("facility_return_temp_c_min"), None],
        "typical": [hp.get("facility_supply_temp_c"), hp.get("facility_return_temp_c"), hp.get("exhaust_air_temp_c")],
        "max": [hp.get("facility_supply_temp_c_max"), hp.get("facility_return_temp_c_max"), None]})
    st.dataframe(temps, hide_index=True, width="stretch")
    st.caption(f"Evidence: {hp.get('evidence')} · confidence: {hp.get('confidence')} · sources: {hs}")
    if hp.get("notes"):
        st.caption(f"Notes: {hp.get('notes')}")
    if hp.get("profile_notes"):
        st.caption(f"Profile notes: {hp.get('profile_notes')}")

with t_chk:
    res = []
    res += ck.weather_checks(w_db, "DB weather") if status["ok"] and site_id else []
    res += ck.weather_checks(w_live, "LIVE weather") if do_live else []
    res += ck.weather_checks(w_nasa, "NASA weather") if do_nasa else []
    if w_db is not None and w_live is not None and status.get("build_mode") == "online":
        res += ck.compare_weather(w_live, w_db, "LIVE vs DB weather (same API, should match)", 0.2)
    if w_nasa is not None and (w_live is not None or w_db is not None):
        res += ck.compare_weather(w_nasa, w_live if w_live is not None else w_db,
                                  "NASA vs Open-Meteo (independent sources)", 2.0,
                                  independent=True)
    res += ck.price_checks(prices) if status["ok"] else []
    if do_price:
        res += ck.compare_prices(p_live, prices)
    res += ck.grid_checks(grid) if grid else []
    res += ck.heat_checks(hp)
    res_df = pd.DataFrame(res)
    n_fail = int((res_df["result"] == "FAIL").sum())
    n_pass = int((res_df["result"] == "pass").sum())
    n_warn = int((res_df["result"] == "warn").sum())
    msg = f"{n_pass} passed, {n_warn} warnings (data works but is not real), {n_fail} failed"
    (st.error if n_fail else st.warning if n_warn else st.success)(msg)
    st.dataframe(res_df, hide_index=True, width="stretch", height=min(40 + 35 * len(res_df), 900))
    if status["ok"] and status.get("build_mode") != "online":
        st.caption("The live versus stored comparison is skipped because the stored database is an offline "
                   "synthetic build.")
    rep = ROOT / "data" / "build_report.json"
    if rep.exists():
        with st.expander("Build report of the stored database (data/build_report.json)"):
            st.json(rep.read_text())

with t_api:
    if call_log.empty:
        st.info("No live calls in this run. Turn them on in the sidebar.")
    else:
        ok = int(call_log["ok"].sum())
        st.write(f"{ok} of {len(call_log)} calls succeeded. Results are cached for one hour per location.")
        show = call_log.copy()
        show["ok"] = show["ok"].map({True: "✅", False: "❌"})
        show["params"] = show["params"].astype(str)
        st.dataframe(show.drop(columns=["url"]), hide_index=True, width="stretch",
                     column_config={"full_url": st.column_config.LinkColumn("request (click to open)")})
    st.markdown("""
**Where each input comes from**

| Input | How it gets here | Key needed |
|---|---|---|
| Hourly weather | Open-Meteo archive API (ERA5), live here and in the Actions build; NASA POWER as fallback | no |
| Hourly prices, US ISO regions | gridstatus (ISO day-ahead LMP), Actions build; one week live here | no (PJM needs a free key) |
| Hourly prices, Israel | IEC time of use tariff, hand entered from the published PDF | no |
| Hourly prices, other regions | synthetic shape times annual price | no |
| Retail price, US | EIA annual xlsx download | no |
| Carbon intensity | EPA eGRID (US, transcribed) and Ember yearly CSV download | no |
| IT load, chip, cooling, temperatures | curated CSVs in data_pipeline/, team estimates with citations | no |
""")
