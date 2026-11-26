import { useEffect, useMemo, useRef, useState } from 'react';
import L from 'leaflet';
import type { DataCenter } from '../types/datacenter';

interface Props {
  dataCenters: DataCenter[];
}

const pinIcon = L.divIcon({
  className: 'dc-pin',
  html: '<span class="dc-pin-core"></span>',
  iconSize: [18, 18],
  iconAnchor: [9, 9],
  popupAnchor: [0, -10],
});

const esc = (s: unknown) =>
  String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]!);

function popupHtml(d: DataCenter) {
  const loc = [d.city, d.country].filter(Boolean).join(', ');
  const rows = [
    d.operator && ['Operator', d.operator],
    d.capacityMW != null && ['Capacity', `${d.capacityMW} MW`],
    d.pue != null && ['PUE', d.pue],
  ].filter(Boolean) as [string, unknown][];
  return `<div class="dc-popup">
    <h3>${esc(d.name)}</h3>
    ${loc ? `<p class="dc-loc">${esc(loc)}</p>` : ''}
    ${rows.map(([k, v]) => `<div class="dc-row"><span>${k}</span><b>${esc(v)}</b></div>`).join('')}
  </div>`;
}

interface PlaceResult { display_name: string; lat: string; lon: string }

export default function MapSection({ dataCenters }: Props) {
  const mapEl = useRef<HTMLDivElement>(null);
  const map = useRef<L.Map | null>(null);
  const layer = useRef<L.LayerGroup | null>(null);
  const markers = useRef(new Map<string, L.Marker>());
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState(false);
  const [places, setPlaces] = useState<PlaceResult[]>([]);

  // init map once
  useEffect(() => {
    if (!mapEl.current || map.current) return;
    const m = L.map(mapEl.current, { center: [30, 10], zoom: 2, minZoom: 2, worldCopyJump: true, zoomControl: false });
    L.control.zoom({ position: 'bottomright' }).addTo(m);
    const esri = 'https://server.arcgisonline.com/ArcGIS/rest/services/Canvas';
    L.tileLayer(`${esri}/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}`, {
      attribution: 'Tiles &copy; Esri &mdash; Esri, HERE, Garmin, &copy; OpenStreetMap contributors',
      maxZoom: 16,
    }).addTo(m);
    L.tileLayer(`${esri}/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}`, { maxZoom: 16 }).addTo(m);
    layer.current = L.layerGroup().addTo(m);
    map.current = m;
    return () => { m.remove(); map.current = null; };
  }, []);

  // render pins
  useEffect(() => {
    const g = layer.current;
    if (!g) return;
    g.clearLayers();
    markers.current.clear();
    dataCenters.forEach((d) => {
      const mk = L.marker([d.lat, d.lng], { icon: pinIcon, title: d.name }).bindPopup(popupHtml(d));
      mk.addTo(g);
      markers.current.set(d.id, mk);
    });
  }, [dataCenters]);

  const matches = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return [];
    return dataCenters
      .filter((d) => [d.name, d.operator, d.city, d.country].some((v) => typeof v === 'string' && v.toLowerCase().includes(q)))
      .slice(0, 8);
  }, [query, dataCenters]);

  // place search fallback (OpenStreetMap Nominatim), debounced
  useEffect(() => {
    const q = query.trim();
    if (q.length < 3) { setPlaces([]); return; }
    const ctrl = new AbortController();
    const t = setTimeout(() => {
      fetch(`https://nominatim.openstreetmap.org/search?format=json&limit=4&q=${encodeURIComponent(q)}`, { signal: ctrl.signal })
        .then((r) => r.json())
        .then(setPlaces)
        .catch(() => {});
    }, 400);
    return () => { clearTimeout(t); ctrl.abort(); };
  }, [query]);

  const focusDc = (d: DataCenter) => {
    map.current?.flyTo([d.lat, d.lng], 11, { duration: 1.2 });
    markers.current.get(d.id)?.openPopup();
    setQuery(d.name);
    setOpen(false);
  };

  const focusPlace = (p: PlaceResult) => {
    map.current?.flyTo([+p.lat, +p.lon], 9, { duration: 1.2 });
    setQuery(p.display_name.split(',')[0]);
    setOpen(false);
  };

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (matches[0]) focusDc(matches[0]);
    else if (places[0]) focusPlace(places[0]);
  };

  const showDropdown = open && query.trim() && (matches.length > 0 || places.length > 0);

  return (
    <section className="map-section" id="map">
      <div className="map-head">
        <h2>Data centers worldwide</h2>
        <p>{dataCenters.length > 0 ? `${dataCenters.length} locations loaded` : 'Location data coming soon'}</p>
      </div>

      <div className="map-wrap">
        <form className="search" onSubmit={onSubmit} role="search">
          <svg viewBox="0 0 24 24" width="22" height="22" aria-hidden>
            <circle cx="11" cy="11" r="7" fill="none" stroke="currentColor" strokeWidth="2" />
            <path d="m20 20-4-4" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
          </svg>
          <input
            value={query}
            onChange={(e) => { setQuery(e.target.value); setOpen(true); }}
            onFocus={() => setOpen(true)}
            onBlur={() => setTimeout(() => setOpen(false), 150)}
            placeholder="Search a data center, operator or city…"
            aria-label="Search"
          />
          <button type="submit" className="btn btn-primary">Search</button>

          {showDropdown && (
            <ul className="search-results">
              {matches.map((d) => (
                <li key={d.id} onMouseDown={() => focusDc(d)}>
                  <span className="tag tag-dc">DC</span>
                  <span className="r-name">{d.name}</span>
                  <span className="r-sub">{[d.city, d.country].filter(Boolean).join(', ')}</span>
                </li>
              ))}
              {places.map((p) => (
                <li key={p.lat + p.lon} onMouseDown={() => focusPlace(p)}>
                  <span className="tag">Place</span>
                  <span className="r-name">{p.display_name.split(',')[0]}</span>
                  <span className="r-sub">{p.display_name.split(',').slice(1, 3).join(',')}</span>
                </li>
              ))}
            </ul>
          )}
        </form>

        <div ref={mapEl} className="map" />
      </div>
    </section>
  );
}
