/**
 * Is a map point on water? Reads the colour of the basemap pixel under the point: on the Esri
 * World Dark Gray base layer, water (sea, lakes, wide rivers) is drawn in a fixed dark colour
 * (about rgb 35,34,39) and land in lighter grey (about 70 to 80). Labels and roads are on a separate
 * layer, so they do not disturb the reading. Returns null when the tile cannot be read (then the
 * point is allowed, so the planner never blocks on a network problem).
 */
const Z = 14;
const BASE = 'https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile';
const cache = new Map<string, Uint8ClampedArray>();

async function tile(x: number, y: number): Promise<Uint8ClampedArray> {
  const k = `${x}/${y}`;
  const hit = cache.get(k);
  if (hit) return hit;
  const r = await fetch(`${BASE}/${Z}/${y}/${x}`, { mode: 'cors' });
  if (!r.ok) throw new Error(`tile ${r.status}`);
  const bm = await createImageBitmap(await r.blob());
  const c = document.createElement('canvas');
  c.width = 256; c.height = 256;
  const g = c.getContext('2d', { willReadFrequently: true })!;
  g.drawImage(bm, 0, 0);
  const d = g.getImageData(0, 0, 256, 256).data;
  cache.set(k, d);
  return d;
}

export async function isWater(lat: number, lng: number): Promise<boolean | null> {
  try {
    const n = 2 ** Z;
    const X = ((lng + 180) / 360) * n;
    const r = (lat * Math.PI) / 180;
    const Y = ((1 - Math.log(Math.tan(r) + 1 / Math.cos(r)) / Math.PI) / 2) * n;
    const d = await tile(Math.floor(X), Math.floor(Y));
    const px = Math.floor((X % 1) * 256), py = Math.floor((Y % 1) * 256);
    // 3 x 3 pixels around the point; water only if most of them are water
    let wet = 0, seen = 0;
    for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) {
      const x = Math.min(255, Math.max(0, px + dx)), y = Math.min(255, Math.max(0, py + dy));
      const i = (y * 256 + x) * 4;
      seen++;
      if ((d[i] + d[i + 1] + d[i + 2]) / 3 < 52) wet++;
    }
    return wet > seen / 2;
  } catch {
    return null;
  }
}
