import { Fragment, useEffect, useMemo, useRef, useState } from 'react';
import L from 'leaflet';
import type { DataCenter } from '../types/datacenter';

interface Props {
  dataCenters: DataCenter[];
  /** Pins come from the backend: a click selects the site instead of opening a popup */
  fromApi?: boolean;
  selectedId?: string | null;
  onSelect?: (id: string) => void;
  /** Rendered on top of the map (the site panel) */
  children?: React.ReactNode;
  /** Plan mode: a click on the map places a planned data center */
  planning?: boolean;
  onPlanToggle?: () => void;
  planPoint?: { lat: number; lng: number } | null;
  onMapClick?: (lat: number, lng: number) => void;
}

const planIcon = L.divIcon({ className: 'dc-pin dc-pin-plan', html: '<span class="dc-pin-core"></span>', iconSize: [22, 22], iconAnchor: [11, 11] });

const makeIcon = (selected: boolean) => L.divIcon({
  className: selected ? 'dc-pin dc-pin-selected' : 'dc-pin',
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

export default function MapSection({ dataCenters, fromApi = false, selectedId = null, onSelect, children,
  planning = false, onPlanToggle, planPoint = null, onMapClick }: Props) {
  const clickRef = useRef(onMapClick);
  clickRef.current = planning ? onMapClick : undefined;
  const planMarker = useRef<L.Marker | null>(null);
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
      attribution: 'Tiles &copy; Esri, Esri, HERE, Garmin, &copy; OpenStreetMap contributors',
      maxZoom: 16,
    }).addTo(m);
    L.tileLayer(`${esri}/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}`, { maxZoom: 16 }).addTo(m);
    layer.current = L.layerGroup().addTo(m);
    m.on('click', (e: L.LeafletMouseEvent) => clickRef.current?.(e.latlng.lat, L.Util.wrapNum(e.latlng.lng, [-180, 180], true)));
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
      const mk = L.marker([d.lat, d.lng], { icon: makeIcon(false), title: d.name });
      if (fromApi && onSelect) {
        mk.bindTooltip(esc(d.name), { direction: 'top', offset: [0, -8], className: 'dc-tooltip' });
        mk.on('click', () => onSelect(d.id));
      } else {
        mk.bindPopup(popupHtml(d));
      }
      mk.addTo(g);
      markers.current.set(d.id, mk);
    });
  }, [dataCenters, fromApi, onSelect]);

  // highlight the selected pin
  useEffect(() => {
    markers.current.forEach((mk, id) => {
      const sel = id === selectedId;
      mk.setIcon(makeIcon(sel));
      mk.setZIndexOffset(sel ? 1000 : 0);
    });
  }, [selectedId, dataCenters]);

  // planned site marker and crosshair cursor
  useEffect(() => {
    const m = map.current;
    if (!m) return;
    m.getContainer().classList.toggle('planning', planning);
    planMarker.current?.remove();
    planMarker.current = null;
    if (planPoint) planMarker.current = L.marker([planPoint.lat, planPoint.lng], { icon: planIcon, zIndexOffset: 2000 }).addTo(m);
  }, [planning, planPoint]);

  const label = (d: DataCenter) => [d.city, (d.region as string | undefined), d.country].filter(Boolean).join(', ');

  // all data centers, sorted by country then name; filtered by the query when there is one
  const sorted = useMemo(() => [...dataCenters].sort((a, b) =>
    String(a.country ?? '').localeCompare(String(b.country ?? '')) || a.name.localeCompare(b.name)), [dataCenters]);
  const matches = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return sorted;
    return sorted.filter((d) => [d.name, d.operator, d.city, d.region, d.country]
      .some((v) => typeof v === 'string' && v.toLowerCase().includes(q)));
  }, [query, sorted]);
  const [active, setActive] = useState(0);
  useEffect(() => setActive(0), [query]);

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
    const m = map.current;
    if (m) {
      // keep the pin in the visible part of the map, left of the side panel
      const zoom = 11;
      const panel = fromApi && m.getSize().x > 720 ? Math.min(460, m.getSize().x) / 2 : 0;
      const target = m.unproject(m.project([d.lat, d.lng], zoom).add([panel, 0]), zoom);
      m.flyTo(target, zoom, { duration: 1.2 });
    }
    if (fromApi && onSelect) onSelect(d.id);
    else markers.current.get(d.id)?.openPopup();
    setQuery(d.name);
    setOpen(false);
  };

  const focusPlace = (p: PlaceResult) => {
    map.current?.flyTo([+p.lat, +p.lon], 9, { duration: 1.2 });
    if (planning && onMapClick) onMapClick(+p.lat, +p.lon);
    setQuery(p.display_name.split(',')[0]);
    setOpen(false);
  };

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (matches[active]) focusDc(matches[active]);
    else if (places[0]) focusPlace(places[0]);
  };

  const showDropdown = open && (matches.length > 0 || places.length > 0);
  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') { setOpen(false); return; }
    if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return;
    e.preventDefault();
    setOpen(true);
    setActive((i) => Math.max(0, Math.min(matches.length - 1, i + (e.key === 'ArrowDown' ? 1 : -1))));
  };
  const listRef = useRef<HTMLUListElement>(null);
  useEffect(() => {
    listRef.current?.querySelector('li.active')?.scrollIntoView({ block: 'nearest' });
  }, [active]);

  const showsAll = dataCenters.some((d) => (d as DataCenter & { setup_status?: string | null }).setup_status !== 'verified');

  return (
    <section className="map-section" id="map">
      <div className="map-head">
        <h2>Data centers worldwide</h2>
        <p>
          {dataCenters.length > 0 ? `${dataCenters.length} locations loaded` : 'Location data coming soon'}
          {dataCenters.length > 0 && (fromApi
            ? ' · click a pin for its ranking'
            : ' · backend offline, start it with ./scripts/dev.sh to see rankings')}
          {fromApi && dataCenters.length > 0 && (showsAll
            ? <> · all sites, including those without documented cooling (<a href="?sites=verified#map">only verified</a>)</>
            : <> · only sites with documented cooling (<a href="?sites=all#map">show all</a>)</>)}
        </p>
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
            onKeyDown={onKey}
            placeholder="Pick a data center or search an operator, city or place…"
            aria-label="Search"
          />
          {dataCenters.length > 0 && (
            <button type="button" className={`list-toggle${open ? ' on' : ''}`} aria-label="Show all data centers"
              title="Show all data centers"
              onMouseDown={(e) => { e.preventDefault(); setOpen(!open); (e.currentTarget.form?.querySelector('input') as HTMLInputElement | null)?.focus(); }}>
              <span>All {dataCenters.length}</span>
              <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden><path d="m6 9 6 6 6-6" fill="none" stroke="currentColor" strokeWidth="2" /></svg>
            </button>
          )}
          <button type="submit" className="btn btn-primary">Search</button>

          {showDropdown && (
            <ul className="search-results" ref={listRef}>
              {matches.map((d, i) => (
                <Fragment key={d.id}>
                  {d.country && (i === 0 || matches[i - 1].country !== d.country) && (
                    <li className="r-group" aria-hidden>{d.country}</li>
                  )}
                  <li className={`${i === active ? 'active' : ''}${d.id === selectedId ? ' current' : ''}`}
                    onMouseDown={() => focusDc(d)} onMouseEnter={() => setActive(i)}>
                    <span className="tag tag-dc">DC</span>
                    <span className="r-name">{d.name}</span>
                    <span className="r-sub">{[d.operator, label(d)].filter(Boolean).join(' · ')}</span>
                  </li>
                </Fragment>
              ))}
              {query.trim() && matches.length === 0 && <li className="r-empty">No data center matches, places below</li>}
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
        {fromApi && onPlanToggle && (
          <button className={`plan-toggle${planning ? ' on' : ''}`} onClick={onPlanToggle}>
            {planning ? (planPoint ? 'Exit planning' : 'Click the map to place the site · cancel') : '+ Plan a new data center'}
          </button>
        )}
        {children}
      </div>
    </section>
  );
}
