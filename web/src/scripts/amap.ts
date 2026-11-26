// Shared AMap loader. Key/security code come from build-env only (never logged or written to text).
// Without a key (or on load failure) the page keeps its StaticMap fallback and labels the source.

import gcoord from 'gcoord';

type Json = any;

const KEY = import.meta.env.PUBLIC_AMAP_KEY || '';
const SECURITY = import.meta.env.PUBLIC_AMAP_SECURITY_CODE || '';

export function wgsToGcj(lng: number, lat: number): [number, number] {
  const [a, b] = gcoord.transform([lng, lat], gcoord.WGS84, gcoord.GCJ02);
  return [a, b];
}

export function hasKey(): boolean {
  return Boolean(KEY && SECURITY);
}

export type AmapKit = {
  AMap: any;
  Loca: any;
  map: any;
  loca: any;
};

/** AMap injects its logo link and helper iframe without names; label them for keyboard/screen readers. */
function patchAmapA11y(containerId: string) {
  const root = document.getElementById(containerId);
  if (!root) return;
  const fix = () => {
    root.querySelectorAll<HTMLImageElement>('.amap-logo img').forEach((img) => {
      if (!img.alt) img.alt = '高德地图';
    });
    root.querySelectorAll<HTMLAnchorElement>('a.amap-logo').forEach((a) => {
      a.setAttribute('aria-label', '高德地图');
    });
    root.querySelectorAll<HTMLIFrameElement>('iframe').forEach((f) => {
      if (!f.title) f.title = '高德地图交互层';
      // AMap's helper iframe is a hidden cross-domain target, not a visible control.
      if (!f.hasAttribute('tabindex')) f.setAttribute('tabindex', '-1');
    });
  };
  fix();
  if (typeof MutationObserver === 'undefined') return;
  const mo = new MutationObserver(fix);
  mo.observe(root, { childList: true, subtree: true });
  window.setTimeout(() => mo.disconnect(), 8000);
}

/** Load AMap 2.0 + Loca into a container element. Resolves null on any failure. */
export async function loadAmap(containerId: string): Promise<AmapKit | null> {
  if (!hasKey()) return null;
  try {
    (window as any)._AMapSecurityConfig = { securityJsCode: SECURITY };
    const loader = (await import('@amap/amap-jsapi-loader')).default;
    const AMap = await loader.load({
      key: KEY,
      version: '2.0',
      plugins: ['AMap.HeatMap', 'AMap.GeoJSON', 'AMap.Geocoder', 'AMap.PlaceSearch'],
      Loca: { version: '2.0.0' },
    });
    const Loca = (window as any).Loca;
    const map = new AMap.Map(containerId, {
      viewMode: '2D',
      zoom: 10.6,
      center: [121.4737, 31.2304],
      mapStyle: 'amap://styles/whitesmoke',
      showLabel: true,
      resizeEnable: true,
    });
    patchAmapA11y(containerId);
    // Keep the static map visible until the live map has actually painted (no empty white frame).
    const frame = document.getElementById(containerId)?.closest('.map-frame');
    map.on('complete', () => {
      frame?.setAttribute('data-map-ready', 'true');
      frame?.dispatchEvent(new CustomEvent('amap-ready'));
    });
    let loca: any = null;
    try {
      loca = Loca ? new Loca.Container({ map }) : null;
    } catch {
      loca = null;
    }
    return { AMap, Loca, map, loca };
  } catch (err) {
    console.warn('AMap load failed, keeping static fallback:', err?.message || err);
    return null;
  }
}

export function fitMarkers(map: any, pts: [number, number][]) {
  if (!map || !pts.length) return;
  try {
    map.setFitView(pts, false, [80, 80, 170, 130], 11);
  } catch {
    /* fit */
  }
}

/** Fetch local map data (metro points, POI, venues). Returns null on any failure. */
export async function loadMapData(): Promise<{ metro: Json[]; poi: Json[]; venues: Json[] } | null> {
  try {
    const [metro, poi, venues] = await Promise.all([
      fetch('/data/map/metro.json').then((r) => r.json()),
      fetch('/data/map/poi.json').then((r) => r.json()),
      fetch('/data/map/venues.json').then((r) => r.json()),
    ]);
    return { metro, poi, venues };
  } catch {
    return null;
  }
}
