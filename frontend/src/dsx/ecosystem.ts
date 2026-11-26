/**
 * Where each of the 13 DSX pathways already works, and which NVIDIA-linked companies could build it.
 * Checked against public sources in November 2026; every entry carries its links.
 *
 * status: operating = data center heat in use today; pilot = announced or running as a trial;
 *         partial = real site, but not exactly this pathway (noted); none = no data center deployment found.
 * NVIDIA ties: investment = NVIDIA or NVentures invested; dsx = named contributor to the NVIDIA (Vera Rubin) DSX
 *         AI factory reference design / Omniverse DSX blueprint; ecosystem = NVIDIA technology partner.
 */

export type ProofStatus = 'operating' | 'pilot' | 'partial' | 'none';
export type NvidiaTie = 'investment' | 'dsx' | 'ecosystem';

export interface Source { label: string; url: string }

export interface Company {
  id: string;
  name: string;
  tie: NvidiaTie;
  /** what the NVIDIA link is, in a few words */
  tieText: string;
  source: Source;
}

export interface Builder { company: string; role: string }

export interface Proof {
  status: ProofStatus;
  title: string;
  place: string;
  summary: string;
  sources: Source[];
  /** reference pin on the map (src/dsx/referenceSites.ts) */
  siteId?: string;
}

export interface PathwayEcosystem { proof: Proof; builders: Builder[] }

const DSX_SRC: Source = {
  label: 'NVIDIA: Vera Rubin DSX reference design and Omniverse DSX blueprint partners',
  url: 'https://nvidianews.nvidia.com/news/nvidia-releases-vera-rubin-dsx-ai-factory-reference-design-and-omniverse-dsx-digital-twin-blueprint-with-broad-industry-support',
};
const DSX_ENERGY_SRC: Source = {
  label: 'NVIDIA investor release: energy partners using the DSX reference architecture',
  url: 'https://investor.nvidia.com/news/press-release-details/2026/NVIDIA-Releases-Vera-Rubin-DSX-AI-Factory-Reference-Design-and-Omniverse-DSX-Digital-Twin-Blueprint-With-Broad-Industry-Support/default.aspx',
};

export const COMPANIES: Record<string, Company> = {
  nebius: { id: 'nebius', name: 'Nebius', tie: 'investment', tieText: 'NVIDIA invested $2B (2026)',
    source: { label: 'NVIDIA and Nebius partner to scale full-stack AI cloud', url: 'https://nvidianews.nvidia.com/news/nvidia-and-nebius-partner-to-scale-full-stack-ai-cloud' } },
  nscale: { id: 'nscale', name: 'Nscale', tie: 'investment', tieText: 'NVIDIA investor; DSX contributor',
    source: { label: 'Nvidia joins $2bn funding round for Nscale', url: 'https://www.techcentral.ie/nvidia-joins-2bn-funding-round-for-ai-data-centre-start-up' } },
  crusoe: { id: 'crusoe', name: 'Crusoe', tie: 'investment', tieText: 'NVIDIA in Series D and Series F',
    source: { label: 'Crusoe $3.9B Series F with Nvidia', url: 'https://www.channelinsider.com/ai/news-crusoe-3-9-billion-series-f-nvidia-ai-infrastructure/' } },
  firmus: { id: 'firmus', name: 'Firmus Technologies', tie: 'investment', tieText: 'NVIDIA joined its funding round',
    source: { label: 'Firmus wins USD 505 million (NVIDIA participating)', url: 'https://itbrief.com.au/story/firmus-wins-usd-505-million-ai-infrastructure-boost' } },
  applied_digital: { id: 'applied_digital', name: 'Applied Digital', tie: 'investment', tieText: 'NVIDIA joined $160M round',
    source: { label: 'Nvidia joins $160M funding round for Applied Digital', url: 'https://www.nasdaq.com/articles/nvidia-nvda-joins-160m-funding-round-applied-digital-ai-push' } },
  orbital: { id: 'orbital', name: 'Orbital Industries (ex Orbital Materials)', tie: 'investment', tieText: 'NVentures investor',
    source: { label: 'Orbital Materials investment from NVentures', url: 'https://www.globenewswire.com/news-release/2024/10/22/2966994/0/en/Orbital-Materials-to-Advance-Materials-and-Climate-Technologies-with-AI-Using-Investment-from-NVentures.html' } },
  brookfield: { id: 'brookfield', name: 'Brookfield AI Infrastructure Fund', tie: 'investment', tieText: 'NVIDIA is a founding investor',
    source: { label: 'Brookfield launches $100B AI infrastructure program with NVIDIA', url: 'https://www.nasdaq.com/press-release/brookfield-launches-100-billion-ai-infrastructure-program-2025-11-19' } },
  trane: { id: 'trane', name: 'Trane Technologies', tie: 'dsx', tieText: 'DSX blueprint contributor', source: DSX_SRC },
  vertiv: { id: 'vertiv', name: 'Vertiv', tie: 'dsx', tieText: 'DSX blueprint contributor', source: DSX_SRC },
  schneider: { id: 'schneider', name: 'Schneider Electric', tie: 'dsx', tieText: 'DSX blueprint contributor', source: DSX_SRC },
  siemens: { id: 'siemens', name: 'Siemens', tie: 'dsx', tieText: 'DSX blueprint contributor', source: DSX_SRC },
  jacobs: { id: 'jacobs', name: 'Jacobs', tie: 'dsx', tieText: 'DSX blueprint contributor (design integrator)', source: DSX_SRC },
  siemens_energy: { id: 'siemens_energy', name: 'Siemens Energy', tie: 'dsx', tieText: 'DSX energy partner', source: DSX_ENERGY_SRC },
  ge_vernova: { id: 'ge_vernova', name: 'GE Vernova', tie: 'dsx', tieText: 'DSX energy partner', source: DSX_ENERGY_SRC },
  caterpillar: { id: 'caterpillar', name: 'Caterpillar', tie: 'dsx', tieText: 'Named in the DSX release (gigawatt AI factory site with Nscale)', source: DSX_SRC },
  phaidra: { id: 'phaidra', name: 'Phaidra', tie: 'dsx', tieText: 'DSX contributor (Max-Q cooling AI agent)', source: DSX_SRC },
  zutacore: { id: 'zutacore', name: 'ZutaCore', tie: 'ecosystem', tieText: 'NVIDIA cooling partner (two-phase DLC)',
    source: { label: 'ZutaCore partners and ecosystem', url: 'https://zutacore.com/partners-and-ecosystem' } },
};

export const TIE_LABEL: Record<NvidiaTie, string> = {
  investment: 'NVIDIA investment', dsx: 'NVIDIA DSX partner', ecosystem: 'NVIDIA ecosystem',
};
export const STATUS_LABEL: Record<ProofStatus, string> = {
  operating: 'Operating', pilot: 'Pilot / announced', partial: 'Related site', none: 'Not deployed yet',
};

/** Shown under every pathway: they enable the whole stack rather than one pathway. */
export const COMMON_BUILDERS: Builder[] = [
  { company: 'jacobs', role: 'Design integration of heat recovery into an AI factory' },
  { company: 'zutacore', role: 'Two-phase direct liquid cooling that returns hotter coolant' },
  { company: 'brookfield', role: 'Capital for AI infrastructure including energy assets' },
  { company: 'phaidra', role: 'AI control of the cooling plant, so heat export and cooling run together' },
];

export const ECOSYSTEM: Record<string, PathwayEcosystem> = {
  fish_farm_ras: {
    proof: { status: 'operating', siteId: 'ref-rjukan', title: 'Green Mountain TEL-Rjukan → Hima Seafood trout farm', place: 'Rjukan, Norway',
      summary: 'Warm water from the data center is piped 800 m to a land-based trout farm (RAS); the cooled water returns to the data center. Running since autumn 2025.',
      sources: [
        { label: 'Green Mountain: heat reuse with Hima Seafood', url: 'https://greenmountain.no/sustainability/heat-reuse/' },
        { label: 'We Are Aquaculture: heat reuse is up and running', url: 'https://weareaquaculture.com/news/sustainability/green-mountains-data-center-heat-reuse-by-hima-seafood-is-up-and-running' },
      ] },
    builders: [{ company: 'nscale', role: 'Operates AI campuses in Norway that could host the heat source' }, { company: 'trane', role: 'Heat pumps and heat exchange to the farm loop' }],
  },
  district_heating: {
    proof: { status: 'operating', siteId: 'ref-mantsala', title: 'Nebius Mäntsälä data center → Nivos district heating', place: 'Mäntsälä, Finland',
      summary: 'Server heat warms water to 35–40 C for the town network; about 20,000 MWh a year, roughly 2,500 homes.',
      sources: [
        { label: 'Nebius: turning heat into a resource', url: 'https://nebius.com/sustainability/turning-heat-into-a-resource' },
        { label: 'Nebius: tripling Mäntsälä capacity (20,000 MWh recovered)', url: 'https://nebius.com/blog/posts/nebius-to-triple-finland-dc-capacity' },
      ] },
    builders: [{ company: 'nebius', role: 'Already runs this at Mäntsälä' }, { company: 'trane', role: 'Heat pumps lifting heat to network temperature' }, { company: 'siemens', role: 'Substations and network automation' }],
  },
  biogas: {
    proof: { status: 'none', title: 'No data center heating a digester found', place: '',
      summary: 'Projects so far run the other way: biogas powers a data center (BEKON digester near Trilj, Croatia). The closest case is Microsoft\'s 2012 Cheyenne pilot, where a biogas fuel cell at a wastewater plant powered a 200 kW data center and returned heat to the plant, but that heat came from the fuel cell, not the servers. Crusoe burns gas to power compute; it does not reuse heat.',
      sources: [{ label: 'MIT Technology Review: Microsoft data center fueled by waste gases (2012)', url: 'https://www.technologyreview.com/2012/11/17/254548/microsoft-data-center-fueled-by-waste-gases/' }, { label: 'BEKON biogas plant supplies a data centre (Croatia)', url: 'https://kleanindustries.com/insights/market-analysis-reports/bekon-biogas-data-centre-waste-to-energy/' }] },
    builders: [{ company: 'crusoe', role: 'Energy-first AI campuses next to gas and waste resources' }, { company: 'siemens_energy', role: 'Gas engines and plant integration' }],
  },
  absorption_cooling: {
    proof: { status: 'partial', siteId: 'ref-syracuse', title: 'Syracuse University Green Data Center', place: 'Syracuse, New York, USA',
      summary: 'Absorption chillers cool the data center, but they run on microturbine exhaust, not on server heat. Same equipment, different heat source.',
      sources: [{ label: 'NYSERDA case study: microturbines with absorption chillers', url: 'https://www.nyserda.ny.gov/-/media/Project/Nyserda/Files/Publications/Case-Studies/On-Site-Power-Application/CHP-sugreendatacenter-cs.pdf' }] },
    builders: [{ company: 'trane', role: 'Chillers and heat-driven cooling plant' }, { company: 'vertiv', role: 'Thermal management and heat reuse integration' },
      { company: 'caterpillar', role: 'Gas gensets with exhaust heat recovery, the kind of drive the Syracuse absorption chillers use' }],
  },
  orc: {
    proof: { status: 'none', title: 'Lab and vendor experiments only', place: '',
      summary: 'Prototypes reach about 2–8 % efficiency on 60–85 C server heat. Vertiv has published experimental results; no commercial data center ORC was found.',
      sources: [
        { label: 'Vertiv: Experimental lessons of an ORC in a data center', url: 'https://www.vertiv.com/en-us/about/news-and-events/articles/white-papers/experimental-lessons-of-organic-rankine-cycle/' },
        { label: 'ORC prototype for data center waste heat (ITherm 2018)', url: 'https://par.nsf.gov/biblio/10065782' },
      ] },
    builders: [{ company: 'vertiv', role: 'Has tested ORC on data center heat' }, { company: 'siemens_energy', role: 'Power cycle equipment' }],
  },
  dac: {
    proof: { status: 'pilot', siteId: 'ref-civo', title: 'Orbital + Civo carbon removal pilot', place: 'United Kingdom (site not disclosed)',
      summary: 'Civo bought an Orbital carbon removal system that uses data center heat to regenerate an AI-designed sorbent. Announced April 2025.',
      sources: [
        { label: 'DCD: Civo partners with Orbital to pilot carbon removal', url: 'https://datacenterdynamics.com/en/news/civo-partners-with-orbital-to-pilot-carbon-removal-technology-at-uk-data-center' },
        { label: 'Orbital Materials and Civo press release', url: 'https://natlawreview.com/press-releases/orbital-materials-partners-civo-pilot-data-center-integrated-carbon-removal' },
      ] },
    builders: [{ company: 'orbital', role: 'Supplies the data center carbon removal system' }],
  },
  btes_ates: {
    proof: { status: 'operating', siteId: 'ref-am3', title: 'Equinix AM3, Amsterdam Science Park', place: 'Amsterdam, Netherlands',
      summary: 'Aquifer thermal energy storage cools the data center instead of chillers; excess heat warms neighbouring Science Park buildings.',
      sources: [
        { label: 'Baxtel: Equinix Science Park campus (ATES)', url: 'https://baxtel.com/campus/equinix-amsterdam-science-park-campus' },
        { label: 'Equinix activates AM3 (ATES, heat to nearby buildings)', url: 'https://convergedigest.com/equinix-activates-3rd-data-center-in/' },
      ] },
    builders: [{ company: 'trane', role: 'Heat pumps and thermal storage plant' }, { company: 'siemens', role: 'Controls for seasonal storage' }],
  },
  feedwater_preheat: {
    proof: { status: 'none', title: 'Research concept, no deployment found', place: '',
      summary: 'Studied for coal and CHP plants. At Falun the data center heat goes to the neighbouring CHP plant for district heating and pellets, not documented as feedwater preheat.',
      sources: [
        { label: 'Survey of carbon-neutral data centers (feedwater preheat concept)', url: 'https://arxiv.org/pdf/2110.09284' },
        { label: 'DCD: EcoDataCenter piping heat to the Falun CHP plant', url: 'https://datacenterdynamics.com/analysis/sharing-warmth-nordic-way' },
      ] },
    builders: [{ company: 'siemens_energy', role: 'Steam cycle and feedwater train' }, { company: 'ge_vernova', role: 'Power plant equipment' }],
  },
  desalination: {
    proof: { status: 'pilot', title: 'Endeavour + Trevi Systems (announced)', place: 'USA',
      summary: 'Partnership to drive forward-osmosis desalination with 60–80 C data center heat. Trevi had not yet deployed at a data center when announced.',
      sources: [{ label: 'DCD: Endeavour partners with Trevi', url: 'https://datacenterdynamics.com/en/news/endeavour-partners-with-us-desalination-firm-trevi-to-turn-data-center-waste-heat-into-clean-water' }] },
    builders: [{ company: 'zutacore', role: 'Two-phase cooling returns coolant near 70 C, which cuts the heat-pump lift to the 70 C MED/MD plant' }, { company: 'jacobs', role: 'Water and desalination engineering' }],
  },
  biomass_processing: {
    proof: { status: 'operating', siteId: 'ref-falun', title: 'EcoDataCenter Falun → Falu Energi & Vatten pellet plant', place: 'Falun, Sweden',
      summary: 'Data center heat (30–32 C) goes to the neighbouring CHP plant, where it heats the city and dries sawdust for wood pellets.',
      sources: [
        { label: 'Vattenfall: EcoDataCenter next to a pellet factory', url: 'https://group.vattenfall.com/press-and-media/newsroom/2024/from-gigabytes-to-megawatts-why-residual-heat-it-hotter-than-ever/' },
        { label: 'SWEP: 30–32 C heat to Falu Energi & Vatten', url: 'https://www.swepgroup.com/about-us/news-and-events/case-stories/ecodatacenter-depends-on-powerful-sustainable-swep-solution' },
      ] },
    builders: [{ company: 'siemens', role: 'Process automation for the drying and pellet line' }, { company: 'trane', role: 'Heat pumps for higher drying temperatures' }],
  },
  industrial_drying: {
    proof: { status: 'operating', siteId: 'ref-falun', title: 'EcoDataCenter Falun: sawdust drying', place: 'Falun, Sweden',
      summary: 'Pellet production dries sawdust on belts with warm air; data center heat replaces propane in that step.',
      sources: [{ label: 'DCD: Sharing warmth the Nordic way', url: 'https://www.datacenterdynamics.com/en/analysis/sharing-warmth-nordic-way/' }] },
    builders: [{ company: 'zutacore', role: 'Two-phase cooling returns coolant near 70 C, which cuts the heat-pump lift to the 75 C dryer' }, { company: 'siemens', role: 'Dryer automation' }],
  },
  snow_melt: {
    proof: { status: 'operating', title: 'Epic Systems campus (3.5 MW data center)', place: 'Verona, Wisconsin, USA',
      summary: 'Heat from a 3.5 MW data center is stored in about 6,100 borehole wells and heats about 40 campus buildings, hot water for the kitchens, and melts snow off the sidewalks. The Westin Building Exchange in Seattle (map pin) heats Amazon buildings but has no documented snow-melt.',
      sources: [{ label: 'Fast Company: how a data center saves its heat for winter (Epic)', url: 'https://fastcompany.com/91621557/data-centers-heat-how-to-save-it-for-winter' },
        { label: 'Amazon: the heat source hidden below its headquarters', url: 'https://www.aboutamazon.com/sustainability/the-super-efficient-heat-source-hidden-below-amazons-new-headquarters' }] },
    builders: [{ company: 'trane', role: 'Heat pumps for hydronic slab loops' }, { company: 'schneider', role: 'Controls and power for the loop' }],
  },
  greenhouse: {
    proof: { status: 'operating', siteId: 'ref-pa10', title: 'Equinix PA10 rooftop greenhouse', place: 'Saint-Denis, Paris, France',
      summary: 'A 430 m² rooftop greenhouse grows fruit and vegetables with server heat; the site also heats the Olympic Aquatic Centre network.',
      sources: [
        { label: 'DCD: Equinix opens urban farm on PA10', url: 'https://datacenterdynamics.com/en/news/equinix-opens-urban-farm-on-its-pa10-paris-data-center-in-paris' },
        { label: 'Choose Paris Region: 6.6 MW recovered, heat network', url: 'https://www.chooseparisregion.org/sites/default/files/pdf/About%20us/Press%20releases/20230216-Press-Release-Choose-Paris-Region-Data-centers-Equinix.pdf' },
      ] },
    builders: [{ company: 'schneider', role: 'Building and greenhouse climate control' }, { company: 'trane', role: 'Heat pumps to greenhouse temperature' }],
  },
};
