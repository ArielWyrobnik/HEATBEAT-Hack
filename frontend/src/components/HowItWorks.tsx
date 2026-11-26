import { useRef, useState } from 'react';

type Status = 'built' | 'review' | 'planned';

const STATUS_LABEL: Record<Status, string> = {
  built: 'Built',
  review: 'Built, in review',
  planned: 'Planned',
};

function Badge({ s }: { s: Status }) {
  return (
    <span className={`status status-${s}`}>
      <span className="status-icon" aria-hidden>{s === 'built' ? '●' : s === 'review' ? '◐' : '○'}</span>
      {STATUS_LABEL[s]}
    </span>
  );
}

interface Step {
  n: string;
  title: string;
  status: Status;
  summary: string;
  details: string[];
  inputs: string[];
  output: string;
  note?: string;
}

const STEPS: Step[] = [
  {
    n: '01',
    title: 'Pick a data center',
    status: 'built',
    summary:
      'The map shows data centers, mainly in the US and some in Israel. Search by name, operator or city, or click a pin.',
    details: [
      'Each pin carries a site id that links it to the location database.',
      'If a place is not in our list, the search falls back to OpenStreetMap so you can still fly to any location.',
    ],
    inputs: ['Site list (59 sites in the database)', 'Search text'],
    output: 'One selected site id',
    note: 'Pins are not loaded into the map yet. The connection from pin to database is planned.',
  },
  {
    n: '02',
    title: 'Pull the location data',
    status: 'review',
    summary:
      'For the selected site we load a full year (2024) of hourly data. Climate and grid decide what a solution is worth at that spot.',
    details: [
      'Weather: hourly ERA5 reanalysis via Open-Meteo, for example dry bulb temperature. It drives cooling demand, free cooling hours and heating demand nearby.',
      'Electricity prices: EIA and US ISO day-ahead markets. Price level and spread decide the value of saved or shifted electricity.',
      'Grid carbon intensity: EPA eGRID (US) and Ember (other countries). Turns MWh saved into tCO2 avoided.',
      'Israel: IEC tariffs as the price signal.',
      'From the hourly data we derive heating and cooling degree hours, mean temperature and price percentiles.',
    ],
    inputs: ['Site latitude and longitude', 'Grid region of the site'],
    output: '8,760 hourly rows plus a site summary',
    note: 'PJM prices need an API key. Non-US retail prices and the Israel tariff mapping are unverified placeholders.',
  },
  {
    n: '03',
    title: 'Describe the heat source',
    status: 'review',
    summary:
      'Nearly all electricity a data center uses ends up as heat. What matters for reuse is how much, how hot and in which medium (water loop or exhaust air).',
    details: [
      'Site profile: IT power in MW (low, typical, high), PUE, chip generation and cooling type.',
      'A cooling profile maps chip generation to facility water temperatures. Example: NVIDIA Vera Rubin, coolant in at about 45 C and out at about 55 C, 100 % liquid cooled (NVIDIA blog, June 2026).',
      'Recoverable liquid heat = IT load x liquid heat share. The rest leaves as warm exhaust air (about 30 to 35 C), which is much harder to use.',
      'Older air cooled halls return chilled water at about 13 C, so almost every reuse option needs a heat pump there.',
    ],
    inputs: ['Site profile', 'Cooling profile lookup (9 profiles, cited)'],
    output: 'Heat in MW and its temperature level',
    note: 'Every per-site value is currently flagged as assumed. Real sites may run colder loops than the reference designs.',
  },
  {
    n: '04',
    title: 'Screen 21 reuse solutions',
    status: 'review',
    summary:
      'A catalogue of 21 solutions, each with the temperature window, climate and site conditions it needs. Every site is screened against all of them in seconds.',
    details: [
      'Temperature score: is the coolant return hot enough? Below the minimum, solutions that can use a heat pump get a reduced score based on its efficiency (COP).',
      'Demand score: is there a need for the output here? Heating degree hours for heat uses, cooling degree hours for heat driven chillers, water stress for desalination, price spread for flexible compute.',
      'Ambient score: share of hours in the year when outside temperature is in the ideal range.',
      'Maturity score: technology readiness level (TRL) divided by 9.',
      'Hard requirements switch a solution off, for example desalination needs a coastal site.',
    ],
    inputs: ['Heat source from step 03', 'Site summary from step 02', 'Context: coastal, water stress, country'],
    output: 'Shortlist with score, sub scores and reasons',
    note: 'Weights and reference scales are team assumptions and can be tuned. The screening ranks potential, it does not know if a fish farm or desalination plant is actually next door.',
  },
  {
    n: '05',
    title: 'Model, compare and rank',
    status: 'planned',
    summary:
      'Each shortlisted solution runs through its own parametric model. The models are compared on the same KPIs and ranked by feasibility and impact.',
    details: [
      'Baseline: the data center as it runs today, heat rejected to air or water.',
      'Counterfactual: the same site with the solution in place.',
      'Energy balance: every MWh in, out, reused and lost is accounted for, hour by hour.',
      'Sensitivity: a tornado chart shows which inputs (IT load, coolant temperature, electricity price, capex) move the result most.',
    ],
    inputs: ['Shortlist from step 04', 'Hourly data from step 02', 'Prices and capex per solution'],
    output: 'Ranked solutions with MWh, tCO2, m3 water, money and payback',
  },
];

// Values from heatbeat_solutions/catalogue.yaml (PR #3): minimum source temperature (lower bound)
// and ideal source temperature range. Solutions without a heat temperature are left out.
type Cat = 'heat' | 'water' | 'enabler';
interface Window { name: string; cat: Cat; min: number; idealLo: number; idealHi: number; israel: string }
const WINDOWS: Window[] = [
  { name: 'District heating, 5th gen', cat: 'heat', min: 20, idealLo: 25, idealHi: 40, israel: 'low' },
  { name: 'Heat pump booster', cat: 'enabler', min: 15, idealLo: 30, idealHi: 60, israel: 'medium' },
  { name: 'Desalination feed preheat (SWRO)', cat: 'water', min: 25, idealLo: 30, idealHi: 45, israel: 'high' },
  { name: 'Fish farm (RAS aquaculture)', cat: 'heat', min: 28, idealLo: 32, idealHi: 45, israel: 'medium' },
  { name: 'Pool heating', cat: 'heat', min: 30, idealLo: 35, idealHi: 50, israel: 'low' },
  { name: 'Greenhouse heating', cat: 'heat', min: 30, idealLo: 40, idealHi: 60, israel: 'medium' },
  { name: 'Microalgae', cat: 'heat', min: 35, idealLo: 40, idealHi: 55, israel: 'medium' },
  { name: 'Biogas (anaerobic digestion)', cat: 'heat', min: 40, idealLo: 45, idealHi: 65, israel: 'medium' },
  { name: 'Low temperature drying', cat: 'heat', min: 40, idealLo: 50, idealHi: 70, israel: 'medium' },
  { name: 'Membrane distillation', cat: 'water', min: 45, idealLo: 60, idealHi: 80, israel: 'medium' },
  { name: 'Adsorption chiller', cat: 'heat', min: 50, idealLo: 60, idealHi: 75, israel: 'high' },
  { name: 'District heating, 4th gen', cat: 'heat', min: 55, idealLo: 65, idealHi: 80, israel: 'low' },
  { name: 'MED desalination', cat: 'water', min: 55, idealLo: 65, idealHi: 75, israel: 'high' },
  { name: 'Domestic hot water', cat: 'heat', min: 58, idealLo: 60, idealHi: 70, israel: 'medium' },
  { name: 'Absorption chiller', cat: 'heat', min: 65, idealLo: 80, idealHi: 95, israel: 'medium' },
  { name: 'ORC power generation', cat: 'heat', min: 70, idealLo: 90, idealHi: 120, israel: 'low' },
  { name: 'Direct air capture (DAC)', cat: 'heat', min: 75, idealLo: 85, idealHi: 110, israel: 'low' },
];

// Typical facility return temperatures from data_pipeline/cooling_profiles.csv (PR #4)
const SOURCES = [
  { t: 13, label: 'Legacy air', sub: 'chilled water' },
  { t: 38, label: 'Hopper', sub: 'cold DLC' },
  { t: 42, label: 'Blackwell', sub: 'warm DLC' },
  { t: 55, label: 'Vera Rubin', sub: 'hot DLC' },
];

const CAT_LABEL: Record<Cat, string> = { heat: 'Waste heat use', water: 'Water', enabler: 'Enabler' };

function TemperatureChart() {
  const [hover, setHover] = useState<{ w: Window; x: number; y: number } | null>(null);
  const [source, setSource] = useState(55);
  const box = useRef<HTMLDivElement>(null);
  const pos = (e: React.MouseEvent) => {
    const r = box.current!.getBoundingClientRect();
    return { x: e.clientX - r.left + box.current!.scrollLeft, y: e.clientY - r.top };
  };
  const T0 = 10, T1 = 120;
  const W = 760, labelW = 230, rowH = 22, top = 46, bottom = 34;
  const plotW = W - labelW - 16;
  const H = top + WINDOWS.length * rowH + bottom;
  const x = (t: number) => labelW + ((t - T0) / (T1 - T0)) * plotW;
  const ticks = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110, 120];

  const fit = (w: Window) =>
    source > w.idealHi ? 'above' : source >= w.idealLo ? 'ideal' : source >= w.min ? 'partial' : 'boost';
  const counts = WINDOWS.reduce((a, w) => ({ ...a, [fit(w)]: (a[fit(w)] ?? 0) + 1 }), {} as Record<string, number>);

  return (
    <div className="tchart">
      <div className="tchart-controls" role="group" aria-label="Choose heat source">
        <span className="tchart-controls-label">Heat source</span>
        {SOURCES.map((s) => (
          <button key={s.t} className={`chip ${source === s.t ? 'chip-on' : ''}`} onClick={() => setSource(s.t)}>
            {s.label} <b>{s.t} C</b>
          </button>
        ))}
      </div>
      <p className="tchart-readout">
        At <b>{source} C</b>: <b>{counts.ideal ?? 0}</b> solutions are inside their ideal range,{' '}
        <b>{counts.above ?? 0}</b> get hotter water than ideal (usable by mixing it down),{' '}
        <b>{counts.partial ?? 0}</b> work below their ideal range, <b>{counts.boost ?? 0}</b> need a heat pump.
      </p>
      <div className="tchart-scroll" ref={box}>
        <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img"
          aria-label="Temperature windows of heat reuse solutions compared with coolant return temperatures">
          {ticks.map((t) => (
            <g key={t}>
              <line x1={x(t)} x2={x(t)} y1={top - 8} y2={H - bottom + 4} className="tc-grid" />
              <text x={x(t)} y={H - bottom + 20} className="tc-tick" textAnchor="middle">{t}</text>
            </g>
          ))}
          <text x={W - 16} y={H - 2} className="tc-tick" textAnchor="end">Source temperature, C</text>

          {WINDOWS.map((w, i) => {
            const y = top + i * rowH;
            const f = fit(w);
            return (
              <g key={w.name} className={`tc-row tc-${w.cat} tc-fit-${f}`}
                onMouseEnter={(e) => setHover({ w, ...pos(e) })}
                onMouseMove={(e) => setHover({ w, ...pos(e) })}
                onMouseLeave={() => setHover(null)}>
                <rect x={0} y={y} width={W} height={rowH} className="tc-hit" />
                <text x={labelW - 10} y={y + rowH / 2 + 4} textAnchor="end" className="tc-label">{w.name}</text>
                <rect x={x(w.min)} y={y + 9} width={x(w.idealLo) - x(w.min)} height={4} rx={2} className="tc-min" />
                <rect x={x(w.idealLo)} y={y + 5} width={Math.max(2, x(w.idealHi) - x(w.idealLo) - 2)} height={12} rx={4} className="tc-ideal" />
              </g>
            );
          })}

          <line x1={x(source)} x2={x(source)} y1={top - 14} y2={H - bottom + 4} className="tc-source" />
          <text x={x(source)} y={top - 20} textAnchor="middle" className="tc-source-label">
            {SOURCES.find((s) => s.t === source)?.label} {source} C
          </text>
        </svg>
        {hover && (
          <div className="tc-tip" style={{ left: hover.x + 14, top: hover.y + 10 }}>
            <b>{hover.w.name}</b>
            <span>{CAT_LABEL[hover.w.cat]}</span>
            <span>Minimum {hover.w.min} C, ideal {hover.w.idealLo} to {hover.w.idealHi} C</span>
            <span>Fit for Israel: {hover.w.israel}</span>
          </div>
        )}
      </div>
      <div className="tchart-legend">
        <span><i className="lg lg-heat" /> Waste heat use</span>
        <span><i className="lg lg-water" /> Water</span>
        <span><i className="lg lg-enabler" /> Enabler</span>
        <span><i className="lg lg-min" /> Works, below ideal</span>
        <span><i className="lg lg-ideal" /> Ideal range</span>
        <span className="tchart-fade">Faded rows are out of reach at the chosen source without a heat pump.</span>
      </div>
      <p className="fineprint">
        Windows from the HEATBEAT solution catalogue (lower bound of the minimum, ideal range). Return
        temperatures are typical values of our cooling profiles. Several catalogue entries are flagged
        estimate or unverified. Four more solutions (flexible compute, battery arbitrage, dry or free
        cooling, reclaimed water cooling) do not depend on heat and are not shown.
      </p>
    </div>
  );
}

const KPIS = [
  { k: 'PUE', name: 'Power Usage Effectiveness', f: 'Total facility energy / IT energy', d: '1.0 is the ideal. Shows how much energy goes into cooling and power losses on top of the IT load.' },
  { k: 'WUE', name: 'Water Usage Effectiveness', f: 'Site water use (L) / IT energy (kWh)', d: 'Key in Israel. Evaporative cooling saves electricity but costs water.' },
  { k: 'ERE', name: 'Energy Reuse Effectiveness', f: '(Total facility energy - reused energy) / IT energy', d: 'Like PUE, but credits heat that is put to use. Reuse can push it below 1.0.' },
];

const OUTPUTS = [
  { u: 'MWh', d: 'Energy saved or reused per year (heat and electricity kept apart)' },
  { u: 'tCO2', d: 'MWh of electricity or fuel avoided x local grid carbon intensity' },
  { u: 'm3', d: 'Water saved or produced per year' },
  { u: '$', d: 'Annual savings or revenue minus operating cost' },
  { u: 'years', d: 'Payback = capex / annual net savings' },
];

export default function HowItWorks() {
  return (
    <section className="how" id="how">
      <div className="how-inner">
        <p className="eyebrow">How it works</p>
        <h2>One question per site: which waste stream solution is most feasible here?</h2>
        <p className="how-lead">
          Data centers turn almost all of their electricity into heat, and many also use large amounts of water.
          Whether that heat, water or spare power can be put to use depends on where the site is. Heat Beat
          answers this in five steps, from a pin on the map to a ranked list of solutions with numbers behind
          each one.
        </p>
        <div className="status-legend">
          <Badge s="built" /> <span>working in the app</span>
          <Badge s="review" /> <span>code written, waiting to be merged</span>
          <Badge s="planned" /> <span>next step</span>
        </div>

        <ol className="steps">
          {STEPS.map((s) => (
            <li key={s.n} className={`step step-${s.status}`}>
              <div className="step-num">{s.n}</div>
              <div className="step-body">
                <div className="step-head">
                  <h3>{s.title}</h3>
                  <Badge s={s.status} />
                </div>
                <p className="step-summary">{s.summary}</p>
                <div className="step-grid">
                  <ul className="step-details">
                    {s.details.map((d) => <li key={d}>{d}</li>)}
                  </ul>
                  <dl className="step-io">
                    <dt>In</dt>
                    <dd>{s.inputs.map((i) => <span key={i}>{i}</span>)}</dd>
                    <dt>Out</dt>
                    <dd><span>{s.output}</span></dd>
                  </dl>
                </div>
                {s.note && <p className="step-note"><b>Limits:</b> {s.note}</p>}
              </div>
            </li>
          ))}
        </ol>

        <div className="how-block">
          <h3>Temperature decides what is possible</h3>
          <p>
            The hotter the coolant leaving the chips, the more solutions can use the heat directly. Pick a chip
            generation to see which windows its return water reaches. Current AI racks top out at about 55 C,
            enough for fish farms, greenhouses, biogas, drying and adsorption chillers. Absorption chillers,
            classic district heating and direct air capture need a heat pump on top.
          </p>
          <TemperatureChart />
        </div>

        <div className="how-block">
          <h3>Example: a 100 MW Vera Rubin site</h3>
          <div className="calc">
            <div><span>IT load</span><b>100 MW</b></div>
            <div><span>x liquid heat share</span><b>0.95</b></div>
            <div><span>= heat in the water loop</span><b>95 MW at about 55 C</b></div>
            <div><span>x 8,760 hours</span><b>about 832,000 MWh of heat per year</b></div>
          </div>
          <p className="fineprint">
            Illustrative upper bound. Assumes constant full IT load all year and the NVIDIA reference loop
            temperatures. The real models use the hourly load range of each site and lose heat in transport.
          </p>
        </div>

        <div className="how-block">
          <h3>What every model reports</h3>
          <div className="kpis">
            {KPIS.map((k) => (
              <div key={k.k} className="kpi">
                <b>{k.k}</b>
                <span className="kpi-name">{k.name}</span>
                <code>{k.f}</code>
                <p>{k.d}</p>
              </div>
            ))}
          </div>
          <ul className="outputs">
            {OUTPUTS.map((o) => <li key={o.u}><b>{o.u}</b><span>{o.d}</span></li>)}
          </ul>
          <p className="fineprint">
            PUE, WUE and ERE follow the definitions of The Green Grid. Each model compares a baseline (site
            without the solution) with a counterfactual (site with it) and includes a tornado chart of the inputs
            that move the result most.
          </p>
        </div>

        <div className="how-block israel">
          <h3>Why location changes the answer: Israel</h3>
          <div className="israel-grid">
            <div><b>Low heating demand</b><p>Mild winters mean little use for district or greenhouse heating. Heat based options score low.</p></div>
            <div><b>High cooling demand</b><p>Long hot summers favour heat driven cooling, for example adsorption chillers fed by the warm loop.</p></div>
            <div><b>Water scarcity</b><p>Water saved by dry or free cooling and reclaimed water counts more than in wet climates.</p></div>
            <div><b>Coastal desalination</b><p>A large desalination sector next to the coast makes feed water preheating and thermal desalination worth checking.</p></div>
          </div>
          <p>
            The same Vera Rubin rack screened in a Tel Aviv-like climate puts flexible compute, low temperature
            drying, dry cooling, desalination preheating and adsorption chillers on top. In a Stockholm-like
            climate fish farms, greenhouses, biogas and district heating lead.
          </p>
          <p className="fineprint">
            Example screenings run on synthetic climate summaries, not database output. Shown to illustrate the
            method.
          </p>
        </div>

        <div className="how-block">
          <h3>Data behind it</h3>
          <ul className="sources">
            <li><b>Weather</b><span>ERA5 reanalysis via Open-Meteo, hourly, 2024</span></li>
            <li><b>Electricity prices</b><span>EIA, US ISO day-ahead markets, IEC tariffs (Israel)</span></li>
            <li><b>Grid carbon intensity</b><span>EPA eGRID (US), Ember (other countries)</span></li>
            <li><b>Cooling and chips</b><span>NVIDIA, Lenovo, ASHRAE TC 9.9, DCD, Schneider Electric, US DOE, operator disclosures</span></li>
            <li><b>Solution parameters</b><span>21 catalogue entries with sources and a confidence flag each</span></li>
          </ul>
          <p className="fineprint">
            Rule for the whole project: every real number cites a source. Where real data is missing we use
            synthetic values and flag them.
          </p>
        </div>
      </div>
    </section>
  );
}
