"""Response schema of the HEATBEAT API. This is the contract between models and the frontend.

Any model (today `heatbeat_ranking`, later `heatbeat_engineering`) returns a `ModelResult`.
The frontend only reads these types, so a new model plugs in without frontend changes.
TypeScript mirror: frontend/src/types/api.ts (keep both in sync).

Units are in the field names: _mwh_yr = MWh per year, _t_yr = tonnes CO2 per year,
_m3_yr = cubic metres per year, _usd = US dollars, _yr = years.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

# How trustworthy a number is. Shown next to every value in the UI.
#   real       measured or looked up for this site (database, GIS, published table)
#   estimated  team estimate or a default that is not site specific (low confidence)
#   synthetic  generated data standing in for missing real data
#   user       set by the user in the UI
Flag = Literal["real", "estimated", "synthetic", "user"]


class SiteSummary(BaseModel):
    """One map pin."""
    site_id: str
    name: str
    lat: float
    lon: float
    operator: str | None = None
    city: str | None = None
    region: str | None = None
    country: str | None = Field(None, description="ISO 3166-1 alpha-2")
    capacity_mw: float | None = None
    it_load_mw: float | None = None
    cooling_type: str | None = None
    pue: float | None = None
    grid_region: str | None = None
    retail_usd_mwh: float | None = None
    co2_kg_mwh: float | None = None
    is_hypothetical: bool = False
    weather_stored: bool = Field(True, description="False: first ranking call fetches weather live (needs internet)")
    setup_status: str | None = Field(None, description="How well today's setup is documented: verified, partial, "
                                     "context (operator or area level only) or None (nothing found)")


class InputValue(BaseModel):
    key: str
    label: str | None = None
    value: Any
    unit: str | None = None
    flag: Flag
    status: str = Field(description="Raw status from the model input layer (data, assumption, user, ...)")
    source: str | None = None
    description: str | None = None
    sens_low: float | None = Field(None, description="Low end of the sensitivity range")
    sens_high: float | None = None


class SiteInputs(BaseModel):
    site_id: str
    inputs: list[InputValue]
    weather: dict[str, Any] = Field(default_factory=dict, description="Annual weather and price indicators")
    flag_counts: dict[str, int] = Field(default_factory=dict)


class Kpis(BaseModel):
    """Annual results of one option against the site baseline. None = the model does not compute it."""
    heat_recovered_mwh_yr: float | None = None
    heat_delivered_mwh_yr: float | None = None
    electricity_used_mwh_yr: float | None = Field(None, description="Extra electricity (heat pump, pumps)")
    electricity_saved_mwh_yr: float | None = None
    co2_avoided_t_yr: float | None = None
    water_saved_m3_yr: float | None = None
    net_value_usd_yr: float | None = None
    cash_value_usd_yr: float | None = Field(None, description="Part of net value that is real money (bills, revenue, O&M)")
    water_value_usd_yr: float | None = Field(None, description="Part of net value from the water scarcity shadow price (not cash)")
    capex_usd: float | None = None
    payback_yr: float | None = Field(None, description="None if the option never pays back")
    pue_baseline: float | None = None
    pue_with: float | None = None
    wue_baseline_l_kwh: float | None = None
    wue_with_l_kwh: float | None = None
    ere: float | None = None
    cop: float | None = None
    capacity_factor: float | None = None


class EnergyFlow(BaseModel):
    """One line of the energy balance (Sankey or table). Positive mwh_yr = flow from source to target."""
    source: str
    target: str
    mwh_yr: float
    kind: Literal["heat", "electricity", "cooling", "fuel", "loss", "other"] = "heat"


class HeatRoute(BaseModel):
    """Annual server heat entering one application or cooling device."""
    name: str
    mwh_yr: float
    kind: Literal["reuse", "cooling"]


class HeatLoop(BaseModel):
    """Annual server heat collected by one cooling loop, split by destination."""
    name: str
    mwh_yr: float
    return_c: float
    routes: list[HeatRoute]


class CalcTerm(BaseModel):
    """One number that goes into a calculation step, with where it comes from."""
    key: str
    label: str | None = None
    value: float | str | None = None
    unit: str | None = None
    flag: Flag | None = Field(None, description="None = computed by the model in an earlier step")
    source: str | None = None


class CalcStep(BaseModel):
    """One step of an option's calculation: formula, the numbers put in, the result."""
    title: str
    formula: str = Field(..., description="Plain text formula, e.g. 'PUE = (IT + cooling + other) / IT'")
    terms: list[CalcTerm] = Field(default_factory=list)
    result: float | None = None
    unit: str | None = None
    note: str | None = None


class Vendor(BaseModel):
    """A company that can build one part of an option (heatbeat_data.vendors, docs/VENDORS.md)."""
    vendor_id: str
    name: str
    role: str = Field(description="Part of the option it covers, e.g. district_heating")
    role_label: str | None = None
    one_line: str | None = None
    url: str | None = None
    where: str | None = Field(None, description="Base and distance, e.g. 'Saint Paul, MN, 11 km away'")
    distance_km: float | None = None
    nvidia: str | None = Field(None, description="NVIDIA link, e.g. 'NVIDIA DSX partner'; None = none found")
    nvidia_source: str | None = None
    verified: str = Field("unverified", description="verified, partly or unverified (see note)")
    source_url: str | None = None
    note: str | None = None


class OptionResult(BaseModel):
    """One candidate: a single option (ranking engine) or a heat chain of components (engineering)."""
    option_id: str
    name: str
    rank: int | None = Field(None, description="1 = best. None = knocked out")
    feasible: bool
    score: float | None = Field(None, description="Higher is better. Scale given by ModelResult.score_scale")
    reuse_npv_usd: float | None = Field(None, description="Incremental NPV versus the same cooling design without heat reuse")
    eco_grade: str | None = None
    components: list[str] = Field(default_factory=list, description="Heat chain parts, e.g. ['dry_cooler', 'heat_pump', 'district_heating']")
    product: str | None = Field(None, description="What it delivers, e.g. '65,961 MWh heat at 38 C'")
    ko_reasons: list[str] = Field(default_factory=list)
    implementation: str | None = Field(None, description="How it would be built at this site, one or two sentences")
    capex_breakdown: dict[str, float] = Field(default_factory=dict, description="USD per cost item, sums to kpis.capex_usd")
    kpis: Kpis = Field(default_factory=Kpis)
    energy_balance: list[EnergyFlow] = Field(default_factory=list)
    heat_loops: list[HeatLoop] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict, description="Model specific extra columns")
    calculation: list[CalcStep] = Field(default_factory=list, description="Step by step calculation trace with sources")
    calculation_inputs: list[InputValue] = Field(default_factory=list,
                                                 description="Every input this option uses, with flag and source")
    already_in_place: list[str] = Field(default_factory=list,
                                        description="Parts of this option the site already has today, with source")
    is_today: bool = Field(False, description="True for the option that is the site's current setup (no change)")
    vendors: list[Vendor] = Field(default_factory=list, description="Up to 3 companies that can build it, nearest first")


class SetupFact(BaseModel):
    """One fact about what the data center does today, with its source (heatbeat_data.current_setup)."""
    field: str
    label: str | None = None
    value: Any = None
    unit: str | None = None
    scope: str | None = Field(None, description="site, campus, cluster, area, operator_region, operator_fleet")
    confidence: str | None = Field(None, description="high, medium, low")
    evidence: str | None = Field(None, description="operator, press, permit, third_party, inferred")
    note: str | None = None
    source_url: str | None = None
    source_title: str | None = None
    source_date: str | None = None


class Baseline(BaseModel):
    """The site without any solution (counterfactual reference)."""
    it_load_mw: float | None = None
    it_energy_mwh_yr: float | None = None
    facility_energy_mwh_yr: float | None = None
    heat_rejected_mwh_yr: float | None = Field(None, description="Heat the cooling plant rejects to ambient")
    pue: float | None = None
    wue_l_kwh: float | None = None
    water_use_m3_yr: float | None = None
    co2_t_yr: float | None = None
    electricity_cost_usd_yr: float | None = None
    cooling_type: str | None = None
    cooling_profile: str | None = None
    heat_rejection: str | None = Field(None, description="dry, adiabatic or tower: what the baseline rejects heat with")
    heat_rejection_flag: Flag | None = Field(None, description="real = from a public source for this site")
    heat_rejection_source: str | None = None
    setup_status: str | None = Field(None, description="verified, partial, context or None")
    current_setup: list[SetupFact] = Field(default_factory=list, description="What the site already does, with sources")


class TornadoBar(BaseModel):
    input: str
    label: str | None = None
    low_value: float
    high_value: float
    metric_low: float
    metric_high: float
    flag: Flag | None = None


class Tornado(BaseModel):
    option_id: str
    metric: str
    unit: str | None = None
    base: float
    bars: list[TornadoBar]


class BudgetSummary(BaseModel):
    """Compute + infrastructure sizing solved from a total build budget (USD)."""
    budget_usd: float
    solved_it_mw: float
    vera_rubin_racks: int
    rack_kw: float
    compute_capex_usd: float
    facility_capex_usd: float
    cooling_reuse_capex_usd: float
    total_build_capex_usd: float
    compute_usd_per_mw: float
    facility_usd_per_mw: float


class PlanDefaults(BaseModel):
    """Pre-filled regional estimates for a planned point before running the full simulation."""
    lat: float
    lon: float
    template_site_id: str
    template_km: float
    inputs: list[InputValue] = Field(default_factory=list)


class ModelResult(BaseModel):
    """Everything the frontend shows for one site."""
    site_id: str
    model: str
    mode: str
    model_version: str | None = None
    score_scale: str = "0 to 5"
    baseline: Baseline
    options: list[OptionResult] = Field(description="Sorted, best first; knocked out options last")
    tornado: Tornado | None = None
    warnings: list[str] = Field(default_factory=list, description="Shown above the results, e.g. unverified CAPEX")
    verdict: str | None = Field(None, description="Plain answer: does anything beat today's setup, and by how much")
    verdict_level: str | None = Field(None, description="no_gain, small_gain or gain (heatbeat_engineering.verdict)")
    inputs_used: dict[str, Any] = Field(default_factory=dict)
    inputs: list["InputValue"] = Field(default_factory=list, description="Inputs with flags (filled for planned sites)")
    cooling_vendors: list[Vendor] = Field(default_factory=list,
                                          description="Planned sites: who supplies the chosen IT cooling")
    planned_site: "PlanRequest | dict[str, Any] | None" = Field(
        None, description="Set when the result is for a planned data center (the request, or a model's own summary)")
    budget_summary: BudgetSummary | None = Field(
        None, description="Filled when PlanRequest specifies budget_usd instead of it_mw")


class ModelInfo(BaseModel):
    name: str
    label: str
    modes: list[str]
    default_mode: str
    description: str
    default: bool = False


class EvaluateRequest(BaseModel):
    """What-if for an existing database site: rerun a model with changed inputs."""
    site_id: str
    model: str | None = None
    mode: str | None = None
    is_greenfield: int | None = Field(None, ge=0, le=1)
    overrides: dict[str, Any] = Field(default_factory=dict)
    tornado: bool = True


class CoolingProfile(BaseModel):
    cooling_profile_id: str
    label: str
    cooling_type: str = Field(description="air or liquid (what the ranking engine distinguishes)")
    heat_temp_c: float | None = Field(None, description="Temperature of the recoverable heat (facility return or exhaust air)")
    pue_typical: float | None = None
    description: str | None = None


class PlanRequest(BaseModel):
    """A future data center at any location: the model ranks the options for it.

    Inputs that depend on the region (power price, grid CO2, gas and water prices, water stress)
    come from the nearest database site; distance inputs use US defaults. Both are flagged estimated.
    """
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    it_mw: float | None = Field(None, gt=0, le=10000, description="IT load in MW (1 GW = 1000 MW)")
    budget_usd: float | None = Field(None, gt=0, le=1e12, description="Total build budget in USD (sizes IT MW + cooling/reuse)")
    cooling_profile: str = Field("dlc_hot", description="cooling_profile_id; defaults to dlc_hot (Vera Rubin NVL144 class)")
    name: str | None = None
    pue: float | None = Field(None, ge=1.0, le=3.0, description="Design PUE; default typical for the cooling profile")
    is_greenfield: int = Field(1, ge=0, le=1, description="1 = solution designed in from the start")
    model: str | None = None
    mode: str | None = None
    overrides: dict[str, Any] = Field(default_factory=dict)
    tornado: bool = True

    @model_validator(mode="after")
    def _require_size_or_budget(self):
        if self.it_mw is None and self.budget_usd is None:
            raise ValueError("Provide either it_mw or budget_usd")
        return self


ModelResult.model_rebuild()


class LeaderboardRow(BaseModel):
    """One data center in the opportunity ranking: its best improvement over today's setup."""
    site_id: str
    name: str
    city: str | None = None
    region: str | None = None
    country: str | None = None
    operator: str | None = None
    it_load_mw: float | None = None
    verdict_level: str | None = None
    option_id: str | None = Field(None, description="Best option that changes something, None if nothing is feasible")
    option_name: str | None = None
    npv_usd: float | None = None
    cash_value_usd_yr: float | None = None
    co2_avoided_t_yr: float | None = None
    water_saved_m3_yr: float | None = None
    payback_yr: float | None = None
