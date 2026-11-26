import { useEffect, useState } from 'react';
import Header from './components/Header';
import Hero from './components/Hero';
import HowItWorks from './components/HowItWorks';
import MapSection from './components/MapSection';
import { loadDataCenters } from './data';
import type { DataCenter } from './types/datacenter';

export default function App() {
  const [dataCenters, setDataCenters] = useState<DataCenter[]>([]);

  useEffect(() => {
    loadDataCenters().then(setDataCenters);
  }, []);

  return (
    <>
      <Header />
      <main>
        <Hero />
        <HowItWorks />
        <MapSection dataCenters={dataCenters} />
      </main>
      <footer className="footer">
        <span>Heat Beat</span> · built at the NVIDIA Hackathon 2026
      </footer>
    </>
  );
}
