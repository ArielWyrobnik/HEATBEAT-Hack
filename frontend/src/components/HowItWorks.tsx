import Tex from './Tex';
import { useRef, useState } from 'react';
import Pie from './Pie';
import { ECO_PARTS, VIABILITY_PARTS } from './ScoreBreakdown';

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
  details: (string | { tex: string; text: string })[];
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
      'The map shows the data centers in the Heat Beat database plus gold reference pins: real sites where data center heat is already reused. Search by name, operator, city or any place.',
    details: [
      'Each pin carries a site id that links it to the location database, or to a reference profile built from public sources.',
      'Plan a new data center anywhere: click the map, enter IT load and cooling, and the same model runs for that point.',
    ],
    inputs: ['Site list from the backend', 'Reference sites (Nebius Mäntsälä, Green Mountain Rjukan, Equinix AM3 and PA10, EcoDataCenter Falun and more)'],
    output: 'One selected site',
  },
  {
    n: '02',
    title: 'Load the location data',
    status: 'built',
    summary:
      'For the selected site we load its 31 inputs (heat, land, distances, prices, grid carbon, water stress, ecology) and a full year of daily temperatures.',
    details: [
      'Inputs come from the Heat Beat database, each flagged real, estimated or synthetic, with its source.',
      'Daily minimum and maximum temperatures for 2024 come from the Open-Meteo archive (ERA5); if it is unreachable, a year is shaped from the site weather summary and flagged synthetic.',
      'The 365 days are expanded to 8,760 hours with a daily cosine wave (coldest at 04:00, warmest at 16:00).',
    ],
    inputs: ['Site id or map point', 'Latitude and longitude'],
    output: '31 inputs and 8,760 hourly temperatures',
    note: 'Many site values are still planning estimates; open the Inputs tab to see which.',
  },
  {
    n: '03',
    title: 'Model the heat source',
    status: 'built',
    summary:
      'Liquid-cooled racks return coolant at a steady temperature; air-cooled halls follow the weather (ambient + 12 C, never below the design value).',
    details: [
      'Where the coolant is hotter than a pathway needs (sink + 5 K), the heat is used directly through a heat exchanger.',
      'Otherwise a heat pump lifts it: COP at 50 % of Carnot with 5 K approach on each side, capped at 8; its electricity is counted every hour.',
    ],
    inputs: ['Cooling type and coolant temperature', 'Recoverable heat (about 0.9 x IT load)'],
    output: 'Hourly coolant temperature, heat pump power and COP',
  },
  {
    n: '04',
    title: 'Screen 13 pathways with knock-out gates',
    status: 'built',
    summary:
      'Thirteen reuse pathways, from fish farms and district heating to desalination and direct air capture. Each has hard gates: climate hours, distances, land, zoning, water stress and whether the site is new.',
    details: [
      'A pathway that fails any gate is knocked out and the reason is shown.',
      'Seven pathways need civil work designed in from the start and only pass on greenfield sites; the panel has a Greenfield toggle.',
    ],
    inputs: ['31 inputs', 'Hourly climate and coolant'],
    output: 'Feasible pathways and knock-out reasons',
  },
  {
    n: '05',
    title: 'Score and grade',
    status: 'built',
    summary:
      'Feasible pathways get a viability score from 0 to 5 and a separate eco grade from A to F, so high profit cannot hide environmental harm.',
    details: [
      { text: 'Viability, 0 to 5 (G = 0 if any knock-out gate fails):', tex: String.raw`\text{Viability} = G\cdot\left(0.30\,P_{thermo} + 0.30\,P_{climate} + 0.25\,P_{econ} + 0.15\,P_{util}\right)` },
      { text: 'Eco grade, scored separately and adjusted by the mitigation tier:', tex: String.raw`E = 0.40\,e_{GHG} + 0.30\,e_{water} + 0.30\,e_{local}\quad\Rightarrow\quad A \ge 4.2,\ B \ge 3.4,\ C \ge 2.6,\ D \ge 1.8` },
      'Show calculation opens every step with its formula, the numbers put in and their sources; a tornado chart shows which inputs move the net value most.',
    ],
    inputs: ['Feasible pathways', 'Prices, carbon and ecology inputs'],
    output: 'Ranked pathways with MWh, tCO2, water, money and payback',
    note: 'CAPEX uses generic per-kW and per-metre costs, so payback is indicative.',
  },
  {
    n: '06',
    title: 'Show where it works and who could build it',
    status: 'built',
    summary:
      'Every pathway is linked to a real data center where it already runs (or marked as not yet proven) and to NVIDIA-linked companies that could build it.',
    details: [
      'Proof is checked against public sources and labelled operating, pilot, related site or not deployed yet.',
      'Companies are listed only with a public NVIDIA link: an NVIDIA or NVentures investment, a DSX reference design role, or an NVIDIA technology partnership.',
    ],
    inputs: ['Top ranked pathways'],
    output: 'Execution stack for the top 3',
  },
];

// The 13 DSX pathways and their sink temperatures (src/dsx/engine.ts). Direct use needs coolant at sink + 5 K;
// below that a heat pump lifts the heat. Sink temperatures come from the evaluator specification.
type Cat = 'heat' | 'water' | 'enabler';
interface Window { name: string; cat: Cat; sink: number; mode: string }
const WINDOWS: Window[] = [
  { name: 'Fish farm (RAS)', cat: 'heat', sink: 28, mode: 'any site' },
  { name: 'Radiant / snow-melt', cat: 'heat', sink: 35, mode: 'greenfield' },
  { name: 'Biogas digester', cat: 'heat', sink: 38, mode: 'any site' },
  { name: 'Greenhouse', cat: 'heat', sink: 40, mode: 'greenfield' },
  { name: 'BTES / ATES storage', cat: 'enabler', sink: 55, mode: 'greenfield' },
  { name: 'Boiler feedwater preheat', cat: 'enabler', sink: 55, mode: 'greenfield' },
  { name: 'District heating', cat: 'heat', sink: 65, mode: 'any site' },
  { name: 'Biomass processing', cat: 'heat', sink: 65, mode: 'greenfield' },
  { name: 'Desalination (MED/MD)', cat: 'water', sink: 70, mode: 'greenfield' },
  { name: 'Industrial drying', cat: 'heat', sink: 75, mode: 'greenfield' },
  { name: 'Absorption cooling', cat: 'heat', sink: 85, mode: 'any site' },
  { name: 'Direct air capture (DAC)', cat: 'enabler', sink: 90, mode: 'any site' },
  { name: 'ORC power', cat: 'heat', sink: 100, mode: 'any site' },
];

// The four DSX cooling presets of the evaluator
const SOURCES = [
  { t: 28, label: 'Legacy air', sub: 'air cooled' },
  { t: 60, label: 'Cold plate', sub: 'direct to chip' },
  { t: 65, label: 'Immersion', sub: 'single phase' },
  { t: 70, label: 'Two-phase DLC', sub: 'DSX design' },
];

const CAT_LABEL: Record<Cat, string> = { heat: 'Heat use', water: 'Water', enabler: 'Storage, power plant or carbon' };

function TemperatureChart() {
  const [hover, setHover] = useState<{ w: Window; x: number; y: number } | null>(null);
  const [source, setSource] = useState(60);
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

  const fit = (w: Window) => (source >= w.sink + 5 ? 'ideal' : 'boost');
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
        At <b>{source} C</b>: <b>{counts.ideal ?? 0}</b> of 13 pathways can use the heat directly through a heat exchanger,{' '}
        <b>{counts.boost ?? 0}</b> need a heat pump to lift it.
      </p>
      <div className="tchart-scroll" ref={box}>
        <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img"
          aria-label="Sink temperature of each pathway compared with the coolant temperature">
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
                <rect x={x(T0)} y={y + 9} width={x(w.sink + 5) - x(T0)} height={4} rx={2} className="tc-min" />
                <rect x={x(w.sink + 5)} y={y + 5} width={Math.max(2, x(T1) - x(w.sink + 5) - 2)} height={12} rx={4} className="tc-ideal" />
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
            <span>Sink {hover.w.sink} C · direct use from {hover.w.sink + 5} C coolant</span>
            <span>Allowed on: {hover.w.mode}</span>
          </div>
        )}
      </div>
      <div className="tchart-legend">
        <span><i className="lg lg-heat" /> Heat use</span>
        <span><i className="lg lg-water" /> Water</span>
        <span><i className="lg lg-enabler" /> Storage, power plant or carbon</span>
        <span><i className="lg lg-min" /> Needs a heat pump</span>
        <span><i className="lg lg-ideal" /> Direct use</span>
        <span className="tchart-fade">Faded rows need a heat pump at the chosen coolant temperature.</span>
      </div>
      <p className="fineprint">
        Sink temperatures of the 13 pathways in the DSX evaluator. Direct use assumes a 5 K heat exchanger
        approach. Air-cooled halls run warmer in hot hours, so their coolant moves with the weather.
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
          answers this in six steps, from a pin on the map to a ranked list of pathways with numbers behind
          each one, proof that it works somewhere and companies that could build it.
        </p>
        <div className="status-legend">
          <Badge s="built" /> <span>working in this version</span>
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
                    {s.details.map((d) => typeof d === 'string' ? <li key={d}>{d}</li> : <li key={d.tex}>{d.text}<Tex block>{d.tex}</Tex></li>)}
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
          <h3>How the two scores are weighted</h3>
          <p>
            Every option gets a viability score (can it work and does it pay) and a separate eco grade (is it good for the
            climate, water and the area). Each is a weighted sum of sub-scores from 0 to 5. Open any option on the map and
            click "Show calculation" to see its own points, money and energy as pie charts.
          </p>
          <div className="pie-grid">
            <Pie title="Viability score (0–5)" fmt={(v) => `${Math.round(v * 100)} %`} pct={false}
              slices={VIABILITY_PARTS.map((x) => ({ label: x.label, value: x.w, color: x.color, note: x.hint }))}
              caption="A failed knock-out gate (for example, no heat network nearby) sets viability to 0." />
            <Pie title="Eco grade (A–F)" fmt={(v) => `${Math.round(v * 100)} %`} pct={false}
              slices={ECO_PARTS.map((x) => ({ label: x.label, value: x.w, color: x.color, note: x.hint }))}
              caption="A ≥ 4.2, B ≥ 3.4, C ≥ 2.6, D ≥ 1.8, else F." />
          </div>
        </div>

        <div className="how-block">
          <h3>Temperature decides what is possible</h3>
          <p>
            The hotter the coolant leaving the chips, the more pathways can use the heat directly. Pick a cooling
            technology to see which pathways its coolant reaches. Air cooling at about 28 C only serves fish farms
            without a heat pump; 70 C two-phase direct liquid cooling also reaches storage, feedwater preheat,
            district heating and biomass processing directly. Desalination, drying, absorption cooling, carbon
            capture and ORC still need a heat pump or hotter coolant.
          </p>
          <TemperatureChart />
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

        <div className="how-block">
          <h3>Data behind it</h3>
          <ul className="sources">
            <li><b>Weather</b><span>ERA5 reanalysis via Open-Meteo: hourly in the database, daily minimum and maximum for the model, 2024</span></li>
            <li><b>Electricity prices</b><span>EIA, US ISO day-ahead markets, IEC tariffs (Israel)</span></li>
            <li><b>Grid carbon intensity</b><span>EPA eGRID (US), Ember (other countries)</span></li>
            <li><b>Cooling and chips</b><span>NVIDIA, Lenovo, ASHRAE TC 9.9, DCD, Schneider Electric, US DOE, operator disclosures</span></li>
            <li><b>Pathways</b><span>DSX evaluator v3.1: 13 pathways, knock-out gates, viability 0 to 5, eco grade A to F</span></li>
            <li><b>Proof and partners</b><span>Real heat reuse sites and NVIDIA links checked against public sources (see below the map)</span></li>
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
