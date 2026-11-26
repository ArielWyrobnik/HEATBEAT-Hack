import { useCallback, useEffect, useState } from 'react';
import Header from './components/Header';
import Hero from './components/Hero';
import Leaderboard from './components/Leaderboard';
import MapSection from './components/MapSection';
import PlanPanel, { type PlanPoint } from './components/PlanPanel';
import SitePanel from './components/SitePanel';
import { loadDataCenters } from './data';
import type { DataCenter } from './types/datacenter';

export default function App() {
  const [dataCenters, setDataCenters] = useState<DataCenter[]>([]);
  const [fromApi, setFromApi] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [planning, setPlanning] = useState(false);
  const [planPoint, setPlanPoint] = useState<PlanPoint | null>(null);
  const [board, setBoard] = useState(false);
  const [focus, setFocus] = useState<{ id: string; n: number } | null>(null);

  useEffect(() => {
    loadDataCenters().then((r) => { setDataCenters(r.dataCenters); setFromApi(r.fromApi); });
  }, []);

  const onSelect = useCallback((id: string) => { setSelected(id); setPlanning(false); setPlanPoint(null); }, []);
  const onMapClick = useCallback((lat: number, lng: number) => { setPlanPoint({ lat, lng }); setSelected(null); }, []);
  const togglePlan = () => {
    if (planning) { setPlanning(false); setPlanPoint(null); } else { setPlanning(true); setSelected(null); setBoard(false); }
  };
  const site = dataCenters.find((d) => d.id === selected) ?? null;

  return (
    <>
      <Header />
      <main>
        <Hero />
        <MapSection dataCenters={dataCenters} fromApi={fromApi} selectedId={selected} onSelect={onSelect}
          planning={planning} onPlanToggle={togglePlan} planPoint={planPoint} onMapClick={onMapClick}
          focus={focus} boardOpen={board} onBoardToggle={() => setBoard(!board)}>
          {board && <Leaderboard selectedId={selected} onClose={() => setBoard(false)}
            onPick={(id) => { onSelect(id); setFocus({ id, n: Date.now() }); }} />}
          {site && !planning && <SitePanel site={site} onClose={() => setSelected(null)} />}
          {planning && planPoint && <PlanPanel point={planPoint} onClose={() => { setPlanning(false); setPlanPoint(null); }} />}
        </MapSection>
      </main>
      <footer className="footer">
        <span>Heat Beat</span> · built at the NVIDIA Hackathon 2026
      </footer>
    </>
  );
}
