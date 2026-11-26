import { COMMON_BUILDERS, COMPANIES, ECOSYSTEM, STATUS_LABEL, TIE_LABEL, type Builder, type Proof } from '../dsx/ecosystem';
import { referenceById } from '../dsx/referenceSites';
import type { ModelResult } from '../types/api';
import type { DataCenter } from '../types/datacenter';

const PATHWAY_NAME: Record<string, string> = {
  fish_farm_ras: 'Fish Farm (RAS)', district_heating: 'District Heating', biogas: 'Biogas Generator',
  absorption_cooling: 'Absorption Cooling', orc: 'Organic Rankine Cycle', dac: 'Carbon Capture / DAC',
  btes_ates: 'BTES / ATES Storage', feedwater_preheat: 'Boiler Feedwater Preheat', desalination: 'Desalination (MED/MD)',
  biomass_processing: 'Biomass Processing', industrial_drying: 'Industrial Drying', snow_melt: 'Radiant / Snow-Melt',
  greenhouse: 'Co-Designed Greenhouse',
};

function StatusBadge({ s }: { s: Proof['status'] }) {
  return <span className={`proof proof-${s}`}>{STATUS_LABEL[s]}</span>;
}

function Links({ sources }: { sources: { label: string; url: string }[] }) {
  return (
    <span className="eco-links">
      {sources.map((s, i) => <a key={s.url} href={s.url} target="_blank" rel="noreferrer" title={s.label}>source {sources.length > 1 ? i + 1 : ''}</a>)}
    </span>
  );
}

function Company({ b }: { b: Builder }) {
  const c = COMPANIES[b.company];
  if (!c) return null;
  return (
    <li>
      <b>{c.name}</b> <span className={`tie tie-${c.tie}`} title={c.tieText}>{TIE_LABEL[c.tie]}</span>
      <small>{b.role}. <a href={c.source.url} target="_blank" rel="noreferrer" title={c.source.label}>{c.tieText}</a></small>
    </li>
  );
}

/** Proof and builders for one pathway, shown under an expanded option. */
export function OptionEcosystem({ optionId }: { optionId: string }) {
  const e = ECOSYSTEM[optionId];
  if (!e) return null;
  const p = e.proof;
  return (
    <div className="eco">
      <div className="eco-proof">
        <div className="eco-h">Where it already works <StatusBadge s={p.status} /></div>
        <p><b>{p.title}</b>{p.place && <span className="muted"> · {p.place}</span>}</p>
        <p className="muted">{p.summary} <Links sources={p.sources} /></p>
      </div>
      <div className="eco-builders">
        <div className="eco-h">Who could build it (NVIDIA-linked)</div>
        <ul>{e.builders.map((b) => <Company key={b.company} b={b} />)}</ul>
        <p className="muted small">Also for every pathway: {COMMON_BUILDERS.map((b) => COMPANIES[b.company].name).join(', ')}. A listed company is a candidate, not a commitment.</p>
      </div>
    </div>
  );
}

/** Execution stack for the top 3 feasible options of a result. */
export function TopStack({ r }: { r: ModelResult }) {
  const top = r.options.filter((o) => o.feasible).slice(0, 3);
  if (!top.length) return null;
  return (
    <section className="stack">
      <h4>NVIDIA-partner companies for the top {top.length}</h4>
      <p className="muted small">Companies NVIDIA has invested in or named as partners in its Vera Rubin DSX AI factory design, matched to each recommended option. Click a name for the source of the NVIDIA link.</p>
      <div className="stack-grid">
        {top.map((o) => {
          const e = ECOSYSTEM[o.option_id];
          return (
            <div key={o.option_id} className="stack-card">
              <span className="stack-rank">#{o.rank}</span>
              <b>{o.name}</b>
              {e && <>
                <p><StatusBadge s={e.proof.status} /> {e.proof.status === 'none' ? e.proof.title : `${e.proof.title}, ${e.proof.place}`}</p>
                <ul className="nv-chips">
                  {e.builders.map((b) => {
                    const c = COMPANIES[b.company];
                    return c ? (
                      <li key={b.company} title={`${b.role}. ${c.tieText}.`}>
                        <a href={c.source.url} target="_blank" rel="noreferrer">{c.name}</a>
                        <span className={`tie tie-${c.tie}`}>{TIE_LABEL[c.tie]}</span>
                        <small>{b.role}</small>
                      </li>
                    ) : null;
                  })}
                </ul>
              </>}
            </div>
          );
        })}
      </div>
      <p className="muted small nv-common">For every option: {COMMON_BUILDERS.map((b, i) => {
        const c = COMPANIES[b.company];
        return c ? <span key={b.company}>{i > 0 ? ' · ' : ''}<a href={c.source.url} target="_blank" rel="noreferrer" title={`${b.role}. ${c.tieText}.`}>{c.name}</a></span> : null;
      })}</p>
    </section>
  );
}

/** Banner on a reference pin's panel: what is proven there, with sources. */
export function ReferenceBanner({ site }: { site: DataCenter }) {
  const ref = referenceById(site.id);
  if (!ref) return null;
  return (
    <div className="ref-banner">
      <span className="ref-tag">Reference site</span>
      {ref.pathways.map((k) => {
        const p = ECOSYSTEM[k]?.proof;
        return p ? <p key={k}><b>{PATHWAY_NAME[k]}</b> <StatusBadge s={p.status} /> {p.summary} <Links sources={p.sources} /></p> : null;
      })}
    </div>
  );
}

/** Landing page section: all 13 pathways, proof status and NVIDIA-linked builders. */
export default function EcosystemSection() {
  const counts = Object.values(ECOSYSTEM).reduce((a, e) => ({ ...a, [e.proof.status]: (a[e.proof.status] ?? 0) + 1 }), {} as Record<string, number>);
  return (
    <section className="how proven" id="proven">
      <div className="how-inner">
        <p className="eyebrow">Proof and partners</p>
        <h2>Where each pathway already works, and who could build it</h2>
        <p className="how-lead">
          Every pathway the model ranks is checked against real data centers. {counts.operating ?? 0} are operating today,
          {' '}{counts.pilot ?? 0} are pilots or announced, {counts.partial ?? 0} have a related site and {counts.none ?? 0} have
          no data center deployment yet. Companies are listed only where their NVIDIA link is public: an NVIDIA or NVentures
          investment, a role in the NVIDIA DSX AI factory reference design, or an NVIDIA technology partnership.
        </p>
        <div className="table-scroll">
          <table className="rank-table proven-table">
            <thead><tr><th>Pathway</th><th>Status</th><th>Real site</th><th>Who could build it</th></tr></thead>
            <tbody>
              {Object.entries(ECOSYSTEM).map(([k, e]) => (
                <tr key={k}>
                  <td className="opt-name">{PATHWAY_NAME[k]}</td>
                  <td><StatusBadge s={e.proof.status} /></td>
                  <td>{e.proof.title}{e.proof.place && <small>{e.proof.place}</small>} <Links sources={e.proof.sources} /></td>
                  <td>{e.builders.map((b) => {
                    const c = COMPANIES[b.company];
                    return c ? <span key={b.company} className={`co tie-${c.tie}`} title={`${b.role}. ${c.tieText}`}>{c.name}</span> : null;
                  })}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="tie-legend">
          {(Object.keys(TIE_LABEL) as (keyof typeof TIE_LABEL)[]).map((t) => <span key={t}><i className={`co tie-${t}`}>{TIE_LABEL[t]}</i></span>)}
          <span>Across all pathways: {COMMON_BUILDERS.map((b) => `${COMPANIES[b.company].name} (${b.role})`).join('; ')}.</span>
        </div>
        <p className="fineprint">
          Checked against public sources in November 2026. The original brief also cited Crusoe for biogas, a Vertiv ORC testbed,
          Falun for feedwater preheat, Midwest grain drying, a Seattle snow-melt loop and Corintis as an NVIDIA partner; those could
          not be confirmed as data center heat reuse or as an NVIDIA link and are shown as such or left out. Gold pins on the map
          are the real sites and can be evaluated like any other data center.
        </p>
      </div>
    </section>
  );
}
