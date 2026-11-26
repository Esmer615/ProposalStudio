// Input workbench controller:
// - Supports ANY custom Shanghai company/brand/landmark via /api/geocode (backed by xinyun-bigdata) + AMap + presets
// - Dynamically renders the exact selected location & rings on BOTH live AMap AND dark SVG StaticMap fallback
// - Interactive multi-turn Agent consultation via POST /api/agent/consult
// - Submits POST /api/proposals (generating 3 strategy variants + real xinyun coverage/routes/portrait)

import AirDatepicker from 'air-datepicker';
import 'air-datepicker/air-datepicker.css';
import { loadAmap, loadMapData, wgsToGcj } from './amap';

type Json = Record<string, any>;

interface CustomVenue {
  id: string;
  name: string;
  province?: string;
  city?: string;
  district: string;
  address: string;
  coords: { lng: number; lat: number };
  rings_km: number[];
  is_shanghai?: boolean;
  verified?: boolean;
}

interface PlaceCandidate {
  name: string;
  province?: string;
  city: string;
  district: string;
  address: string;
  lng: number;
  lat: number;
  type?: string;
  scope?: string;
  is_shanghai?: boolean;
  source?: string;
}

interface PresetLoc {
  id: string;
  name: string;
  district: string;
  industry: string;
  preset: boolean;
  coords: { lng: number; lat: number };
}

const DEFAULT_PRESETS: PresetLoc[] = [
  { id: 'lego_shanghai', name: '上海乐高乐园', district: '金山区', industry: '乐园', preset: true, coords: { lng: 121.104, lat: 30.880 } },
  { id: 'disney_shanghai', name: '上海迪士尼度假区', district: '浦东新区', industry: '乐园', preset: true, coords: { lng: 121.657, lat: 31.141 } },
  { id: 'haichang_shanghai', name: '上海海昌海洋公园', district: '浦东新区', industry: '乐园', preset: true, coords: { lng: 121.908, lat: 30.910 } },
  { id: 'custom_pingan', name: '中国平安金融中心（陆家嘴）', district: '浦东新区', industry: '银行保险', preset: false, coords: { lng: 121.5016, lat: 31.2397 } },
  { id: 'custom_jingan', name: '静安寺商圈', district: '静安区', industry: '食品饮料', preset: false, coords: { lng: 121.4465, lat: 31.2238 } },
  { id: 'custom_xujiahui', name: '徐家汇港汇恒隆', district: '徐汇区', industry: '私立医院', preset: false, coords: { lng: 121.4375, lat: 31.1945 } },
  { id: 'custom_peoplesq', name: '人民广场核心商圈', district: '黄浦区', industry: '保健品', preset: false, coords: { lng: 121.4737, lat: 31.2304 } },
];

// Projection constants matching StaticMap.astro exactly (W=1000, H=760, GCJ02)
const SVG_W = 1000;
const SVG_H = 760;
const SVG_BBOX = { minLng: 120.85, maxLng: 122.25, minLat: 30.68, maxLat: 31.88 };
const SVG_MID_LAT = (SVG_BBOX.minLat + SVG_BBOX.maxLat) / 2;
const SVG_KM_PER_LNG = 111 * Math.cos((SVG_MID_LAT * Math.PI) / 180);
const SVG_XKM_MAX = (SVG_BBOX.maxLng - SVG_BBOX.minLng) * SVG_KM_PER_LNG;
const SVG_YKM_MAX = (SVG_BBOX.maxLat - SVG_BBOX.minLat) * 111;
const SVG_SCALE = Math.min(SVG_W / SVG_XKM_MAX, SVG_H / SVG_YKM_MAX) * 0.94;

function projectSvg(lng: number, lat: number): [number, number] {
  const x = ((lng - SVG_BBOX.minLng) * SVG_KM_PER_LNG - SVG_XKM_MAX / 2) * SVG_SCALE + SVG_W / 2;
  const y = ((SVG_BBOX.maxLat - lat) * 111 - SVG_YKM_MAX / 2) * SVG_SCALE + SVG_H / 2;
  return [x, y];
}

const form = document.getElementById('plan-form');
if (form) initInput();

function initInput() {
  const $ = <T extends HTMLElement = HTMLElement>(s: string) => document.querySelector<T>(s);

  const venueSel = $<HTMLSelectElement>('#f-venue');
  const venueQuery = $<HTMLInputElement>('#f-venue-query');
  const btnVenueSearch = $<HTMLButtonElement>('#btn-venue-search');
  const venueNote = $('#venue-search-note');
  const locBadge = $('#selected-loc-badge');
  const industrySel = $<HTMLSelectElement>('#f-industry');
  const strategySel = $<HTMLSelectElement>('#f-strategy');
  const startInput = $<HTMLInputElement>('#f-start');
  const btnStartPicker = $<HTMLButtonElement>('#btn-start-picker');
  const startMonthWrap = $('#start-month-wrap');
  const weeksInput = $<HTMLInputElement>('#f-weeks');
  const customerSel = $<HTMLSelectElement>('#f-customer');
  const budgetSlider = $<HTMLInputElement>('#f-budget');
  const budgetNum = $<HTMLInputElement>('#f-budget-num');
  const budgetVal = $('#budget-val');
  const lockInc = $<HTMLInputElement>('#f-lock-include');
  const lockExc = $<HTMLInputElement>('#f-lock-exclude');
  const btnGenerate = $<HTMLButtonElement>('#btn-generate');
  const runNote = $('#run-note');
  const formError = $('#form-error');
  const dialog = $('#agent-dialog');
  const chatInput = $<HTMLInputElement>('#agent-chat-input');
  const btnChatSend = $<HTMLButtonElement>('#btn-agent-send');
  const stagesEl = $('#run-stages');
  const stageLive = $('[data-out="stage-live"]');
  const runModal = $('#run-progress-modal');
  const runModalScrim = $('#run-modal-scrim');
  const modalStageLive = $('[data-out="modal-stage-live"]');
  const modalTargetSummary = $('[data-out="modal-target-summary"]');
  const modalElapsed = $('[data-out="modal-elapsed"]');
  const modalNote = $('[data-out="modal-note"]');
  const btnCloseRunModal = $<HTMLButtonElement>('#btn-close-run-modal');
  const btnModalDismiss = $<HTMLButtonElement>('#btn-modal-dismiss');
  const btnReopenProgress = $<HTMLButtonElement>('#btn-reopen-progress');
  const mapFrame = $('#input-map');

  let presets: PresetLoc[] = [...DEFAULT_PRESETS];
  let selectedVenueId = 'lego_shanghai';
  let customVenue: CustomVenue | null = null;
  let venueConfirmed = false;
  let candidatePlaces: PlaceCandidate[] = [];
  let currentCompanyProfile: Json | null = null;
  let agentBriefText = '';
  let mapKit: { AMap: any; map: any } | null = null;
  let mapData: any = null;
  let mapOverlays: any[] = [];
  let chatHistory: { role: string; content: string }[] = [];

  const STAGE_ORDER = ['intake', 'data_inventory', 'data_bigdata', 'engine', 'data_routes', 'visualize', 'narrative', 'done'];
  const STAGE_LABELS: Record<string, string> = {
    intake: '解析需求与地点',
    data_inventory: '实时拉取红豆可售库存',
    data_bigdata: '拉取新云周边覆盖与 POI',
    engine: 'CP-SAT 凹模型求解三套方案',
    data_routes: '拉取新云真实轨迹与人群画像',
    visualize: '合成人流热力图与图层',
    narrative: '组装三方案对比话术',
    done: '交付就绪',
  };
  let runStartedAt = 0;
  let liveTimer: number | null = null;

  function openRunModal(summaryText?: string) {
    if (summaryText && modalTargetSummary) modalTargetSummary.textContent = summaryText;
    if (runModalScrim) {
      runModalScrim.setAttribute('data-open', 'true');
      runModalScrim.setAttribute('aria-hidden', 'false');
    }
    if (runModal) runModal.setAttribute('data-open', 'true');
    if (btnReopenProgress) btnReopenProgress.hidden = false;
  }
  function closeRunModal() {
    if (runModalScrim) {
      runModalScrim.setAttribute('data-open', 'false');
      runModalScrim.setAttribute('aria-hidden', 'true');
    }
    if (runModal) runModal.setAttribute('data-open', 'false');
  }
  function setModalStatus(status: 'running' | 'done' | 'error', note?: string) {
    if (runModal) runModal.setAttribute('data-status', status);
    if (note && modalNote) modalNote.textContent = note;
    if (btnModalDismiss) btnModalDismiss.hidden = status === 'running';
  }
  function setStage(id: string, state: string) {
    const el = stagesEl?.querySelector<HTMLElement>(`[data-stage="${id}"]`);
    if (el) el.setAttribute('data-state', state);
  }
  function setStagesProgress(pct: number) {
    if (stagesEl) stagesEl.style.setProperty('--stage-progress', `${Math.max(0, Math.min(100, pct))}%`);
  }
  function setLive(text: string) {
    if (modalStageLive) modalStageLive.textContent = text;
    if (stageLive) stageLive.textContent = text;
  }
  function resetStages() {
    STAGE_ORDER.forEach((s) => setStage(s, 'pending'));
    setStagesProgress(0);
    if (modalElapsed) modalElapsed.textContent = '0s';
    setLive('正在启动 Agent 管线…');
  }

  function showVenueNote(msg: string) {
    if (!venueNote) return;
    venueNote.textContent = msg;
    venueNote.hidden = !msg;
  }

  function escapeHtml(s: string): string {
    return String(s).replace(/[<>&"]/g, (c) => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;', '"': '&quot;' }[c] || c));
  }

  function updateLocationBadge() {
    if (!locBadge) return;
    if (customVenue) {
      locBadge.textContent = `${customVenue.name} · ${customVenue.district || '自定义'}`;
      locBadge.className = 'chip chip--accent mono';
    } else {
      const p = presets.find((x) => x.id === selectedVenueId) || presets[0];
      locBadge.textContent = `${p?.name || selectedVenueId} · ${p?.district || ''}`;
      locBadge.className = 'chip chip--quiet mono';
    }
    const cardTitle = $('[data-out="map-card-title"]');
    if (cardTitle) {
      const nm = customVenue ? customVenue.name : (presets.find((x) => x.id === selectedVenueId)?.name || '客户公司');
      cardTitle.textContent = `客户公司地址定位 · ${nm}`;
    }
    // Sync preset pill highlight
    document.querySelectorAll<HTMLButtonElement>('[data-loc-preset]').forEach((b) => {
      const pid = b.dataset.locPreset || '';
      const active = customVenue ? customVenue.id === pid : selectedVenueId === pid;
      b.classList.toggle('is-active', active);
    });
  }

  // Parse month string like "2027.01", "2027.1", "2027-07", "2027年7月", "2027-07-01" -> { display: "2027.07", iso: "2027-07-01" }
  function parseStartMonth(raw: string): { display: string; iso: string } | null {
    const cleaned = String(raw || '').trim().replace(/年/g, '.').replace(/月/g, '').replace(/[\/\-]/g, '.');
    const m = cleaned.match(/^(\d{4})\.(\d{1,2})(?:\.\d{1,2})?$/);
    if (!m) return null;
    const yr = Number(m[1]);
    const mo = Number(m[2]);
    if (yr < 2020 || yr > 2035 || mo < 1 || mo > 12) return null;
    const mm = String(mo).padStart(2, '0');
    return { display: `${yr}.${mm}`, iso: `${yr}-${mm}-01` };
  }

  // Distinct Neumorphic visual state for empty (deep recessed) vs. filled (soft raised + subtle Mint completion cue)
  function syncFilledStates() {
    const controls = form!.querySelectorAll<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>(
      'input[type="text"], input[type="search"], input[type="number"], textarea, select:not([hidden])',
    );
    controls.forEach((el) => {
      const filled = String(el.value || '').trim().length > 0;
      const unitWrap = el.closest('.unit-input');
      if (unitWrap) {
        unitWrap.classList.toggle('is-filled', filled);
        el.classList.remove('is-filled');
      } else {
        el.classList.toggle('is-filled', filled);
      }
    });
  }

  function syncBudgetUI(val: number, source: 'slider' | 'num' | 'ext' = 'ext') {
    if (!Number.isFinite(val) || val <= 0) return;
    const rounded = Math.round(val);
    if (budgetVal) budgetVal.textContent = String(rounded);
    if (budgetSlider && source !== 'slider') {
      const min = Number(budgetSlider.min || 100);
      const max = Number(budgetSlider.max || 500);
      budgetSlider.value = String(Math.min(max, Math.max(min, rounded)));
    }
    if (budgetNum && source !== 'num') {
      budgetNum.value = String(rounded);
    }
    syncFilledStates();
  }

  function getActiveCoordsGcj(): { name: string; district: string; gcj: [number, number]; rings: number[]; isCustom: boolean } {
    if (customVenue) {
      return {
        name: customVenue.name,
        district: customVenue.district,
        gcj: [customVenue.coords.lng, customVenue.coords.lat],
        rings: customVenue.rings_km?.length ? customVenue.rings_km : [3, 8, 20],
        isCustom: true,
      };
    }
    const v = mapData?.venues?.find((x: any) => x.id === selectedVenueId);
    if (v?.coords?.lng) {
      const gcj = wgsToGcj(Number(v.coords.lng), Number(v.coords.lat));
      return { name: v.name, district: v.district || '', gcj, rings: v.rings_km || [6, 20, 50], isCustom: false };
    }
    const p = presets.find((x) => x.id === selectedVenueId) || presets[0];
    return {
      name: p.name,
      district: p.district,
      gcj: wgsToGcj(p.coords.lng, p.coords.lat),
      rings: [6, 20, 50],
      isCustom: !p.preset,
    };
  }

  // Render exact active target location on the dark SVG StaticMap fallback (hiding the 3 hardcoded park rings)
  function drawSvgSelection() {
    const svg = mapFrame?.querySelector<SVGSVGElement>('.map-fallback svg');
    if (!svg) return;
    const staticVenues = svg.querySelector<SVGGElement>('[data-map-layer="venues"]');
    if (staticVenues) staticVenues.style.display = 'none';
    const targetLayer = svg.querySelector<SVGGElement>('[data-map-layer="dynamic-target"]');
    if (!targetLayer) return;
    targetLayer.replaceChildren();

    const active = getActiveCoordsGcj();
    const [x, y] = projectSvg(active.gcj[0], active.gcj[1]);
    const NS = 'http://www.w3.org/2000/svg';

    // Subtle luminous halo
    const halo = document.createElementNS(NS, 'circle');
    halo.setAttribute('cx', x.toFixed(1));
    halo.setAttribute('cy', y.toFixed(1));
    halo.setAttribute('r', String(Math.max(24, (active.rings[0] || 6) * SVG_SCALE * 1.4)));
    halo.setAttribute('fill', 'url(#ps-heat-gold)');
    targetLayer.append(halo);

    // Concentric catchment rings (only for active selected location!)
    active.rings.slice(0, 2).forEach((km, idx) => {
      const c = document.createElementNS(NS, 'circle');
      c.setAttribute('cx', x.toFixed(1));
      c.setAttribute('cy', y.toFixed(1));
      c.setAttribute('r', Math.max(18, km * SVG_SCALE).toFixed(1));
      c.setAttribute('fill', 'none');
      c.setAttribute('stroke', '#6d5dfc');
      c.setAttribute('stroke-opacity', idx === 0 ? '0.68' : '0.32');
      c.setAttribute('stroke-width', idx === 0 ? '2' : '1.4');
      c.setAttribute('stroke-dasharray', '6 6');
      targetLayer.append(c);
    });

    // Pin dot
    const pin = document.createElementNS(NS, 'circle');
    pin.setAttribute('cx', x.toFixed(1));
    pin.setAttribute('cy', y.toFixed(1));
    pin.setAttribute('r', '7.5');
    pin.setAttribute('fill', '#6d5dfc');
    pin.setAttribute('stroke', '#ffffff');
    pin.setAttribute('stroke-width', '2.4');
    targetLayer.append(pin);

    // Label pill (keep inside SVG bounds)
    const labelText = active.name.length > 14 ? active.name.slice(0, 14) + '…' : active.name;
    const tx = x > 740 ? x - 14 : x + 14;
    const anchor = x > 740 ? 'end' : 'start';
    const txt = document.createElementNS(NS, 'text');
    txt.setAttribute('x', tx.toFixed(1));
    txt.setAttribute('y', (y + 5).toFixed(1));
    txt.setAttribute('text-anchor', anchor);
    txt.setAttribute('class', 'ps-map-venue-label');
    txt.textContent = labelText;
    targetLayer.append(txt);

    const sub = document.createElementNS(NS, 'text');
    sub.setAttribute('x', tx.toFixed(1));
    sub.setAttribute('y', (y + 24).toFixed(1));
    sub.setAttribute('text-anchor', anchor);
    sub.setAttribute('font-size', '12');
    sub.setAttribute('fill', '#6d5dfc');
    sub.textContent = `${active.district || '上海市'} · ${active.rings.slice(0, 2).join('/')}km 辐射圈`;
    targetLayer.append(sub);

    const note = $('[data-map-note]');
    if (note && mapFrame?.getAttribute('data-mode') !== 'live') {
      note.textContent = `已定位 · ${active.name}（${active.district || '上海'}） · ${active.rings.slice(0, 2).join('/')}km 圈层`;
    }
  }

  function distanceKm(a: [number, number], b: [number, number]): number {
    const R = 6371;
    const dLat = ((b[1] - a[1]) * Math.PI) / 180;
    const dLng = ((b[0] - a[0]) * Math.PI) / 180;
    const la1 = (a[1] * Math.PI) / 180;
    const la2 = (b[1] * Math.PI) / 180;
    const h = Math.sin(dLat / 2) ** 2 + Math.cos(la1) * Math.cos(la2) * Math.sin(dLng / 2) ** 2;
    return 2 * R * Math.asin(Math.min(1, Math.sqrt(h)));
  }

  function drawVenueSelection() {
    updateLocationBadge();
    drawSvgSelection();
    if (!mapKit || !mapData) return;
    const { AMap, map } = mapKit;
    if (mapOverlays.length) mapOverlays.forEach((overlay) => map.remove(overlay));
    mapOverlays = [];
    const add = (overlay: any) => {
      map.add(overlay);
      mapOverlays.push(overlay);
    };

    const active = getActiveCoordsGcj();
    const origin = active.gcj;
    const isPending = customVenue ? customVenue.verified === false : false;

    // Subtle soft highlight halo around the client company's exact building/address
    add(new AMap.Circle({
      center: origin,
      radius: 450,
      strokeColor: isPending ? '#d9822b' : '#6d5dfc',
      strokeOpacity: 0.55,
      strokeWeight: 1.5,
      strokeStyle: 'dashed',
      fillColor: isPending ? '#d9822b' : '#6d5dfc',
      fillOpacity: 0.09,
    }));

    const cityBadge = customVenue?.city || active.district || '';
    const badgeLabel = isPending ? '待确认' : (cityBadge ? cityBadge.replace(/市$/, '') : '');
    const content = `<div class="amap-venue-marker is-selected"><i class="amap-pin amap-pin--venue${isPending ? ' is-pending' : ''}"></i><span class="amap-venue">${escapeHtml(active.name)}${badgeLabel ? `<em>${escapeHtml(badgeLabel)}</em>` : ''}</span></div>`;
    add(new AMap.Marker({ position: origin, content, offset: new AMap.Pixel(-8, -8), zIndex: 140 }));

    // Draw clickable alternative branch/address markers when multiple candidates exist
    const extraMarkers: any[] = [];
    if (candidatePlaces.length > 1) {
      candidatePlaces.slice(0, 4).forEach((cand, idx) => {
        if (!Number.isFinite(cand.lng) || !Number.isFinite(cand.lat)) return;
        const dist = distanceKm(origin, [cand.lng, cand.lat]);
        if (dist < 0.05) return;
        const cHtml = `<div class="amap-cand-marker" title="点击切换到此公司地址"><b>${idx + 1}</b><span>${escapeHtml(cand.name)}</span></div>`;
        const mk = new AMap.Marker({
          position: [cand.lng, cand.lat],
          content: cHtml,
          offset: new AMap.Pixel(-10, -10),
          zIndex: 130,
          clickable: true,
        });
        mk.on('click', () => {
          confirmPickedPlace(cand);
        });
        add(mk);
        extraMarkers.push(mk);
      });
    }

    try {
      // Zoom smoothly to street/building view of the client company's real nationwide address!
      map.setZoomAndCenter(active.isCustom ? 14 : 12, origin);
    } catch { /* map not ready */ }

    const note = $('[data-map-note]');
    if (note) {
      const addrText = customVenue?.address || [customVenue?.city, active.district, active.name].filter(Boolean).join('');
      note.textContent = `高德定位 · ${addrText || active.name}`;
    }
  }

  function applyLocationPreset(id: string) {
    const p = presets.find((x) => x.id === id);
    if (!p) return;
    candidatePlaces = [];
    venueConfirmed = true;
    if (p.preset) {
      selectedVenueId = p.id;
      customVenue = null;
      if (venueSel) venueSel.value = p.id;
    } else {
      selectedVenueId = 'custom';
      customVenue = {
        id: p.id,
        name: p.name,
        city: '上海市',
        district: p.district,
        address: `上海市${p.district}${p.name}`,
        coords: { lng: p.coords.lng, lat: p.coords.lat },
        rings_km: [3, 8, 20],
        is_shanghai: true,
        verified: true,
      };
    }
    if (venueQuery) venueQuery.value = p.name;
    if (industrySel && p.industry) industrySel.value = p.industry;
    showVenueNote(`已定位客户「${p.name}」（${p.district} · ${p.industry}）`);
    drawVenueSelection();
    syncFilledStates();
  }

  function applyCustomPlace(
    name: string,
    lng: number,
    lat: number,
    district = '',
    address = '',
    source = '',
    opts: { province?: string; city?: string; isShanghai?: boolean; verified?: boolean } = {},
  ) {
    const isSh = opts.isShanghai !== undefined
      ? opts.isShanghai
      : (120.8 <= lng && lng <= 122.2 && 30.65 <= lat && lat <= 31.9);
    const verified = opts.verified !== false;
    selectedVenueId = 'custom';
    venueConfirmed = verified;
    customVenue = {
      id: 'custom',
      name,
      province: opts.province || '',
      city: opts.city || (isSh ? '上海市' : ''),
      district: district || '',
      address: address || [opts.province, opts.city, district, name].filter(Boolean).join(''),
      coords: { lng, lat },
      rings_km: [3, 8, 20],
      is_shanghai: isSh,
      verified,
    };
    if (venueQuery) venueQuery.value = name;
    drawVenueSelection();
    syncFilledStates();
    const locLabel = customVenue.address || [opts.city, district].filter(Boolean).join('') || '全国';
    showVenueNote(`已定位客户地址：${locLabel}${source ? ' · ' + source : ''}`);
  }

  // Live Nationwide AMap PlaceSearch helper for locating client companies anywhere in China
  function amapPlaceSearchOnce(query: string, city: string, citylimit: boolean): Promise<PlaceCandidate[]> {
    return new Promise((resolve) => {
      const AMap = mapKit?.AMap;
      if (!AMap?.PlaceSearch || !query.trim()) {
        resolve([]);
        return;
      }
      let settled = false;
      const timer = window.setTimeout(() => {
        if (!settled) { settled = true; resolve([]); }
      }, 6000);
      try {
        const ps = new AMap.PlaceSearch({ city, citylimit, pageSize: 6 });
        ps.search(query.trim(), (status: string, result: any) => {
          if (settled) return;
          settled = true;
          window.clearTimeout(timer);
          if (status !== 'complete' || !result?.poiList?.pois?.length) {
            resolve([]);
            return;
          }
          const out: PlaceCandidate[] = [];
          for (const poi of result.poiList.pois) {
            if (!poi?.location) continue;
            const lng = Number(poi.location.getLng());
            const lat = Number(poi.location.getLat());
            if (!Number.isFinite(lng) || !Number.isFinite(lat)) continue;
            const provName = String(poi.pname || '').trim();
            const cityName = String(poi.cityname || (citylimit ? '上海市' : '')).trim();
            const distName = String(poi.adname || '').trim();
            const rawAddr = String(poi.address || '').trim();
            const prefix = provName && provName !== cityName && !cityName.includes(provName)
              ? `${provName}${cityName}`
              : (cityName || provName);
            const fullAddr = rawAddr
              ? (rawAddr.includes(cityName) || !prefix ? rawAddr : `${prefix}${distName && !rawAddr.includes(distName) ? distName : ''}${rawAddr}`)
              : `${prefix}${distName}${poi.name || ''}`;
            const isSh = cityName.includes('上海') || (120.8 <= lng && lng <= 122.2 && 30.65 <= lat && lat <= 31.9);
            out.push({
              name: String(poi.name || query).trim(),
              province: provName,
              city: cityName || (isSh ? '上海市' : ''),
              district: distName,
              address: fullAddr,
              lng,
              lat,
              type: String(poi.type || '').trim(),
              scope: isSh ? 'shanghai' : 'national',
              is_shanghai: isSh,
              source: '高德地图全国检索',
            });
          }
          resolve(out);
        });
      } catch {
        if (!settled) { settled = true; window.clearTimeout(timer); resolve([]); }
      }
    });
  }

  async function searchAmapPlaces(queries: string[]): Promise<PlaceCandidate[]> {
    const uniqQueries = [...new Set(queries.map((q) => q.trim()).filter(Boolean))].slice(0, 3);
    if (!uniqQueries.length) return [];

    // NATIONWIDE FIRST: client companies can be anywhere in China!
    const tasks: Promise<PlaceCandidate[]>[] = uniqQueries.map((q) => amapPlaceSearchOnce(q, '全国', false));
    // Only also run Shanghai-scoped search when query explicitly mentions Shanghai
    if (uniqQueries.some((q) => /上海|陆家嘴|静安|徐家汇|张江|浦东|黄浦|虹桥|前滩/.test(q))) {
      tasks.push(amapPlaceSearchOnce(uniqQueries[0], '上海市', true));
    }

    const batches = await Promise.all(tasks);
    const merged: PlaceCandidate[] = [];
    const seen = new Set<string>();
    for (const list of batches) {
      for (const item of list) {
        const key = `${item.name}|${item.lng.toFixed(4)}|${item.lat.toFixed(4)}`;
        if (seen.has(key)) continue;
        seen.add(key);
        merged.push(item);
      }
    }
    return merged.slice(0, 8);
  }

  function confirmPickedPlace(place: PlaceCandidate, customSendText?: string) {
    candidatePlaces = [];
    applyCustomPlace(
      place.name,
      place.lng,
      place.lat,
      place.district,
      place.address,
      place.source || '高德定位确认',
      { province: place.province, city: place.city, isShanghai: place.is_shanghai, verified: true },
    );
    const msg = customSendText || `改定位到：${place.name}（${place.address || place.district || place.city}）`;
    sendConsultMessage(msg, { preCandidates: [place], lookupDone: true, enterpriseHint: place.name });
  }

  async function searchVenue() {
    const q = venueQuery?.value?.trim() || '';
    if (!q) {
      showVenueNote('请输入客户公司或品牌名称');
      return;
    }
    const hitPreset = presets.find((p) => p.name === q);
    if (hitPreset) {
      applyLocationPreset(hitPreset.id);
      return;
    }

    // Hand off directly to the Agent: Phase 1 normalizes official company name + strategy, Phase 2 locates nationwide on AMap!
    showVenueNote(`已交由 Agent 调研「${q}」的企业地址、行业与广告策略…`);
    $('#pipeline-card')?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    await sendConsultMessage(`客户公司是「${q}」，请调研并定位公司地址、所属行业与推荐广告策略`, { enterpriseHint: q });
  }

  // --- Dialog helpers ---
  function pushDialog(role: 'user' | 'agent' | 'error' | 'thinking', content: string | HTMLElement): HTMLElement | null {
    if (!dialog) return null;
    const el = document.createElement('div');
    el.className = `msg msg--${role}`;
    if (typeof content === 'string') {
      el.textContent = content;
    } else {
      el.append(content);
    }
    dialog.append(el);
    dialog.scrollTop = dialog.scrollHeight;
    return el;
  }

  function pushThinkingBubble(initialText: string): { el: HTMLElement | null; setText: (t: string) => void; remove: () => void } {
    const wrap = document.createElement('div');
    wrap.className = 'thinking-row';
    const dots = document.createElement('span');
    dots.className = 'thinking-dots';
    dots.innerHTML = '<i></i><i></i><i></i>';
    const txt = document.createElement('span');
    txt.className = 'thinking-text';
    txt.textContent = initialText;
    wrap.append(dots, txt);
    const el = pushDialog('thinking', wrap);
    return {
      el,
      setText: (t: string) => {
        txt.textContent = t;
        if (dialog) dialog.scrollTop = dialog.scrollHeight;
      },
      remove: () => el?.remove(),
    };
  }

  function renderCompanyProfileCard(profile: Json): HTMLElement {
    const card = document.createElement('div');
    card.className = 'agent-profile-card';

    const top = document.createElement('div');
    top.className = 'agent-profile-card__top';
    const nameEl = document.createElement('b');
    nameEl.textContent = profile.company_name || '客户公司';
    const indChip = document.createElement('span');
    indChip.className = 'chip chip--accent';
    indChip.textContent = profile.industry_detail
      ? `${profile.industry || '其他'} · ${profile.industry_detail}`
      : (profile.industry || '其他');
    top.append(nameEl, indChip);

    const grid = document.createElement('div');
    grid.className = 'agent-profile-card__grid';

    const addRow = (lbl: string, val: string, isAccent = false) => {
      if (!val) return;
      const row = document.createElement('div');
      row.className = 'agent-profile-card__row';
      const s = document.createElement('span');
      s.textContent = lbl;
      const p = document.createElement('p');
      if (isAccent) p.className = 'is-accent';
      p.textContent = val;
      row.append(s, p);
      grid.append(row);
    };

    const mediaText = Array.isArray(profile.recommended_media) && profile.recommended_media.length
      ? profile.recommended_media.map((m: string) => (m === 'bus' ? '公交车身' : '地铁出入口')).join(' + ')
      : '';
    addRow('公司地址', profile.address || [profile.city, profile.district].filter(Boolean).join(''));
    addRow('主营业务', profile.core_business || '');
    addRow('核心客群', profile.target_audience || '');
    addRow(
      '推荐策略',
      [profile.ad_strategy_label, mediaText ? `推荐媒介：${mediaText}` : ''].filter(Boolean).join(' · '),
      true,
    );
    addRow('策略建议', profile.ad_strategy_reason || '');

    card.append(top, grid);
    return card;
  }

  function applyDraftFromAgent(draft: Json, geocoded?: Json, locationStatus?: string, candidates?: PlaceCandidate[]) {
    if (!draft) return;
    candidatePlaces = Array.isArray(candidates) && candidates.length > 1 ? candidates : [];
    if (draft.company_profile) currentCompanyProfile = draft.company_profile;

    if (draft.custom_venue && draft.custom_venue.name && draft.custom_venue.coords) {
      const cv = draft.custom_venue;
      const isVerified = locationStatus === 'confirmed' || locationStatus === 'located' || Boolean(draft.venue_confirmed);
      applyCustomPlace(
        cv.name,
        Number(cv.coords.lng),
        Number(cv.coords.lat),
        cv.district || geocoded?.district || '',
        cv.address || geocoded?.address || cv.name,
        cv.source || geocoded?.source || 'Agent 全国定位',
        {
          province: cv.province || geocoded?.province || '',
          city: cv.city || geocoded?.city || '',
          isShanghai: cv.is_shanghai !== undefined ? Boolean(cv.is_shanghai) : undefined,
          verified: isVerified,
        },
      );
    } else if (draft.venue && presets.some((p) => p.id === draft.venue) && (locationStatus === 'confirmed' || draft.venue_confirmed)) {
      applyLocationPreset(draft.venue);
    } else if (locationStatus === 'not_found' && draft.pending_enterprise) {
      venueConfirmed = false;
      showVenueNote(`高德地图暂未找到「${draft.pending_enterprise}」的准确地址，请在下方对话框补充公司全称或所在城市`);
    }

    if (draft.industry && industrySel) {
      const hasOpt = [...industrySel.options].some((o) => o.value === draft.industry);
      if (hasOpt) industrySel.value = draft.industry;
    }
    if (draft.strategy_mode && strategySel) strategySel.value = draft.strategy_mode;
    if (draft.budget_wan) syncBudgetUI(Number(draft.budget_wan));
    if (draft.weeks && weeksInput) weeksInput.value = String(Math.max(2, Math.round(Number(draft.weeks))));
    if (draft.start_date && startInput) {
      syncStartMonth(String(draft.start_date));
    }
    if (draft.customer_type && customerSel) customerSel.value = draft.customer_type;
    if (Array.isArray(draft.media) && draft.media.length) {
      form!.querySelectorAll<HTMLInputElement>('input[name="media"]').forEach((c) => {
        c.checked = draft.media.includes(c.value);
      });
    }
    if (draft.brief_text) agentBriefText = String(draft.brief_text).trim();
    syncFilledStates();
  }

  async function callConsultApi(
    msg: string,
    draft: Json,
    placeCandidates?: PlaceCandidate[],
    lookupDone = false,
    enterpriseHint?: string,
  ): Promise<Json> {
    const ctrl = new AbortController();
    const timer = window.setTimeout(() => ctrl.abort(), 30000);
    try {
      const res = await fetch('/api/agent/consult', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        signal: ctrl.signal,
        body: JSON.stringify({
          message: msg,
          draft,
          history: chatHistory.slice(-8),
          place_candidates: placeCandidates || [],
          lookup_done: lookupDone,
          enterprise_hint: enterpriseHint || undefined,
        }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return await res.json();
    } finally {
      window.clearTimeout(timer);
    }
  }

  async function sendConsultMessage(
    text: string,
    opts: { preCandidates?: PlaceCandidate[]; lookupDone?: boolean; enterpriseHint?: string } = {},
  ) {
    const msg = text.trim();
    if (!msg) return;
    pushDialog('user', msg);
    chatHistory.push({ role: 'user', content: msg });
    if (chatInput) chatInput.value = '';
    if (btnChatSend) btnChatSend.disabled = true;
    if (btnVenueSearch) btnVenueSearch.disabled = true;

    const thinking = pushThinkingBubble(
      opts.enterpriseHint
        ? `Agent 正在调研「${opts.enterpriseHint}」的企业信息与全国地址…`
        : 'Agent 正在理解需求并调研客户公司信息…',
    );

    try {
      const draft = readForm();
      let data = await callConsultApi(
        msg,
        draft,
        opts.preCandidates || [],
        Boolean(opts.lookupDone),
        opts.enterpriseHint,
      );

      // Phase 2 tool loop: Agent normalized official company name -> now run live nationwide AMap PlaceSearch!
      if (data.need_place_lookup && Array.isArray(data.search_queries) && data.search_queries.length) {
        const label = data.pending_enterprise || data.search_queries[0];
        thinking.setText(`Agent 正在高德地图全国检索「${label}」的公司地址…`);
        showVenueNote(`Agent 正在高德地图定位「${label}」…`);
        const liveCandidates = await searchAmapPlaces(data.search_queries);
        thinking.setText(
          liveCandidates.length
            ? `已定位到 ${liveCandidates.length} 条高德地图地址，Agent 正在整理行业与广告策略…`
            : `高德地图未直接命中「${label}」，Agent 正在整理核实建议…`,
        );
        data = await callConsultApi(msg, data.draft || draft, liveCandidates, true, opts.enterpriseHint || label);
      }

      thinking.remove();

      if (data.draft) {
        applyDraftFromAgent(data.draft, data.geocoded, data.location_status, data.candidates);
      }

      const wrap = document.createElement('div');
      const head = document.createElement('div');
      head.className = 'msg__head';
      const engineTag = data.agent_mode === 'llm' ? 'DeepSeek Agent' : 'Agent（离线兜底）';
      if (data.company_profile && data.location_status !== 'not_found') {
        head.textContent = data.location_status === 'confirmed'
          ? `${engineTag} · 客户档案与策略已确认`
          : `${engineTag} · 客户调研完成 · 请确认信息`;
      } else if (data.location_status === 'not_found') {
        head.textContent = `${engineTag} · 请核实客户公司名称`;
      } else {
        head.textContent = `${engineTag} · 策略顾问`;
      }
      wrap.append(head);

      // Render structured Client Research & Ad Strategy Confirmation Card inside Agent bubble
      if (data.company_profile && data.location_status !== 'not_found') {
        wrap.append(renderCompanyProfileCard(data.company_profile));
      }

      const body = document.createElement('div');
      body.style.whiteSpace = 'pre-line';
      body.textContent = String(data.reply || '').replace(/\*\*/g, '');
      wrap.append(body);

      const suggs: Json[] = data.suggestions || [];
      if (suggs.length) {
        const chips = document.createElement('div');
        chips.className = 'agent-chips';
        suggs.forEach((s) => {
          const b = document.createElement('button');
          b.type = 'button';
          b.className = s.action === 'generate' || s.action === 'pick_place' ? 'q-chip q-chip--primary' : 'q-chip';
          b.textContent = s.label || s.send_text || '';
          b.addEventListener('click', () => {
            if (s.action === 'generate') {
              onGenerate();
            } else if (s.action === 'pick_place' && s.place) {
              confirmPickedPlace(s.place as PlaceCandidate, s.send_text);
            } else if (s.send_text) {
              sendConsultMessage(s.send_text);
            }
          });
          chips.append(b);
        });
        wrap.append(chips);
      }
      pushDialog('agent', wrap);
      chatHistory.push({ role: 'assistant', content: data.reply || '' });
    } catch {
      thinking.remove();
      pushDialog('error', '无法连接 Agent 顾问接口或响应超时，请确认本地后端服务（127.0.0.1:8010）正常运行后重试。');
    } finally {
      if (btnChatSend) btnChatSend.disabled = false;
      if (btnVenueSearch) btnVenueSearch.disabled = false;
    }
  }

  const xinyunPill = $<HTMLButtonElement>('#xinyun-status-pill');

  function setXinyunState(state: 'loading' | 'online' | 'degraded' | 'offline', label: string) {
    if (xinyunPill) xinyunPill.setAttribute('data-state', state);
    const xyEl = $('[data-out="xinyun-status"]');
    if (xyEl) {
      xyEl.textContent = label;
      xyEl.style.color = '';
    }
  }

  function applyXinyunFromMeta(m: Json) {
    const xy = m?.xinyun_session || {};
    if (xy.authenticated) {
      setXinyunState('online', '已连接 · 实时就绪');
    } else {
      setXinyunState('degraded', '未登录 · 自动降级');
    }
  }

  // --- Load /api/meta ---
  async function loadMeta() {
    setXinyunState('loading', '检测连接中…');
    try {
      const res = await fetch('/api/meta');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const m = await res.json();

      if (Array.isArray(m.preset_locations) && m.preset_locations.length) {
        presets = m.preset_locations;
      }

      const venues: Json[] = m.venues || [];
      if (venueSel) {
        venueSel.replaceChildren();
        venues.forEach((v) => {
          const opt = document.createElement('option');
          opt.value = v.id;
          opt.textContent = v.name;
          venueSel.append(opt);
        });
      }

      const dates: string[] = m.dates || ['2027-07-01'];
      const opts: Json[] = m.date_options || dates.map((d) => ({ value: d, label: d }));
      availableMonths.clear();
      opts.forEach((d) => {
        const parsed = parseStartMonth(String(d.value || ''));
        if (parsed) availableMonths.add(parsed.display);
      });
      monthPicker?.update({});
      if (startInput && !startInput.value.trim() && dates.length) {
        syncStartMonth(dates[0]);
      }

      const ver = m.manifest?.data_version || m.data_version || '—';
      const setTxt = (sel: string, txt: string) => {
        const el = $(sel);
        if (el) el.textContent = txt;
      };
      setTxt('[data-out="intro-fact"]', `引擎就绪 · CP-SAT 凹边际三方案模型 · ${ver}`);
      applyXinyunFromMeta(m);

      // Restore draft from URL params if any
      const sp = new URLSearchParams(location.search);
      if (sp.get('venue') && presets.some((p) => p.id === sp.get('venue'))) {
        applyLocationPreset(sp.get('venue')!);
      } else {
        drawVenueSelection();
      }
      if (sp.get('budget')) syncBudgetUI(Number(sp.get('budget')));
    } catch {
      const el = $('[data-out="intro-fact"]');
      if (el) el.textContent = '本地服务未连接 · 离线预览';
      setXinyunState('offline', '服务未连接 · 离线');
      if (startInput && !startInput.value.trim()) startInput.value = '2027.07';
      drawVenueSelection();
      syncFilledStates();
    }
  }

  async function refreshXinyunStatus() {
    if (!xinyunPill || xinyunPill.classList.contains('is-checking')) return;
    xinyunPill.classList.add('is-checking');
    setXinyunState('loading', '重新检测中…');
    try {
      const res = await fetch('/api/meta', { cache: 'no-store' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const m = await res.json();
      applyXinyunFromMeta(m);
    } catch {
      setXinyunState('offline', '服务未连接 · 离线');
    } finally {
      window.setTimeout(() => xinyunPill.classList.remove('is-checking'), 320);
    }
  }

  function readForm(): Json {
    const media = [...form!.querySelectorAll<HTMLInputElement>('input[name="media"]:checked')].map((c) => c.value);
    const inc = (lockInc?.value || '').split(/[,，\s]+/).map((s) => s.trim()).filter(Boolean);
    const exc = (lockExc?.value || '').split(/[,，\s]+/).map((s) => s.trim()).filter(Boolean);
    const parsedStart = parseStartMonth(startInput?.value || '');
    const rawBudget = Number(budgetNum?.value || budgetSlider?.value || 300);
    const rawWeeks = Number(weeksInput?.value || 8);
    const req: Json = {
      industry: industrySel?.value || '乐园',
      venue: customVenue ? 'custom' : selectedVenueId,
      venue_confirmed: venueConfirmed,
      budget_wan: Number.isFinite(rawBudget) && rawBudget > 0 ? Math.round(rawBudget) : 300,
      media,
      start_date: parsedStart ? parsedStart.iso : '',
      weeks: Number.isFinite(rawWeeks) ? Math.round(rawWeeks) : 0,
      customer_type: customerSel?.value || 'direct',
      strategy_mode: strategySel?.value || 'balanced',
      locks: { include: inc, exclude: exc },
      brief_text: agentBriefText || chatHistory.filter((h) => h.role === 'user').map((h) => h.content).join('；'),
    };
    if (customVenue) {
      req.custom_venue = customVenue;
    }
    if (currentCompanyProfile) {
      req.company_profile = currentCompanyProfile;
    }
    return req;
  }

  function validateForm(req: Json): boolean {
    if (formError) {
      formError.hidden = true;
      formError.textContent = '';
    }
    const me = $('[data-error="media"]');
    if (me) me.hidden = true;
    if (!req.media || !req.media.length) {
      if (me) {
        me.textContent = '至少选择一种投放媒介（公交车身或地铁出入口）';
        me.hidden = false;
      }
      return false;
    }
    if (!req.start_date) {
      if (formError) {
        formError.textContent = '请输入有效的起始档期月份，例如 2027.01 或 2027.07';
        formError.hidden = false;
      }
      startInput?.focus();
      return false;
    }
    if (!Number.isFinite(req.weeks) || req.weeks < 2) {
      if (formError) {
        formError.textContent = '投放周数最小为 2 周，请重新输入';
        formError.hidden = false;
      }
      weeksInput?.focus();
      return false;
    }
    if (!Number.isFinite(req.budget_wan) || req.budget_wan < 10) {
      if (formError) {
        formError.textContent = '请输入有效的投放预算金额（单位：万）';
        formError.hidden = false;
      }
      budgetNum?.focus();
      return false;
    }
    return true;
  }

  async function onGenerate() {
    // If the user typed a new company/place in #f-venue-query without locating via Agent, locate & research first!
    const typedPlace = venueQuery?.value?.trim() || '';
    const activeName = customVenue ? customVenue.name : (presets.find((p) => p.id === selectedVenueId)?.name || '');
    if (typedPlace && typedPlace !== activeName) {
      await searchVenue();
      if (!venueConfirmed) return;
    }

    const req = readForm();
    if (!validateForm(req)) return;

    btnGenerate!.disabled = true;
    resetStages();
    runStartedAt = Date.now();
    setStage('intake', 'active');
    setStagesProgress(6);
    setLive('正在启动 Agent 管线…');

    const targetLabel = customVenue ? customVenue.name : (presets.find((p) => p.id === req.venue)?.name || req.venue);
    const mediaLabel = (req.media || []).map((m: string) => (m === 'bus' ? '公交车身' : '地铁出入口')).join(' + ');
    const summaryText = `${targetLabel} · ${req.industry} · ${req.budget_wan} 万 · ${req.weeks} 周 · ${mediaLabel}`;
    setModalStatus('running', '已提交：实时红豆库存 + 新云周边覆盖/画像 + 三套确定性策略方案求解中…');
    openRunModal(summaryText);
    if (runNote) {
      runNote.textContent = 'Agent 正在生成三套方案…';
      runNote.hidden = true;
    }

    pushDialog('user', `启动生成：${targetLabel}（${req.industry}）· ${req.budget_wan} 万 · ${req.weeks} 周 · ${req.media.join('+')}`);

    if (liveTimer) window.clearInterval(liveTimer);
    liveTimer = window.setInterval(() => {
      const s = Math.round((Date.now() - runStartedAt) / 1000);
      if (modalElapsed) modalElapsed.textContent = `${s}s`;
    }, 1000);

    let runId: string | null = null;
    try {
      const res = await fetch('/api/proposals', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          request: req,
          brief_text: req.brief_text || `${targetLabel} ${req.industry} ${req.budget_wan}万 ${req.weeks}周`,
          options: { include_elasticity: true, include_routes: true },
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        const errObj = err.error || { code: `HTTP_${res.status}`, message: '提交失败' };
        showRunError(errObj);
        setLive('方案提交失败');
        setModalStatus('error', `${errObj.code || 'ERROR'}：${errObj.message || '提交失败'}`);
        if (liveTimer) { window.clearInterval(liveTimer); liveTimer = null; }
        btnGenerate!.disabled = false;
        return;
      }
      const created = await res.json();
      runId = created.run_id;
    } catch {
      setLive('无法连接运行服务');
      setModalStatus('error', '无法连接本地运行服务（127.0.0.1:8010），请确认后端服务已启动后重试。');
      if (liveTimer) { window.clearInterval(liveTimer); liveTimer = null; }
      btnGenerate!.disabled = false;
      return;
    }

    if (!runId) return;
    const done = await pollRun(runId);
    if (liveTimer) { window.clearInterval(liveTimer); liveTimer = null; }
    if (done === 'done' || done === 'degraded') {
      try { localStorage.setItem('lastRunId', runId!); } catch { /* ignore */ }
      setLive('三套方案已生成，正在打开结果页…');
      setModalStatus('done', '三套差异化方案与可视化图层已全部交付，正在跳转至结果页…');
      const variantParam = req.strategy_mode ? `&variant=${encodeURIComponent(req.strategy_mode)}` : '';
      window.location.href = `/result/overview.html?run=${encodeURIComponent(runId)}${variantParam}`;
    } else if (done === 'needs_input') {
      setLive('需要补充信息');
      setModalStatus('error', 'Agent 需要您补充更多投放信息，请收起弹窗并在下方对话区继续沟通。');
    } else {
      setLive('运行超时或失败');
      setModalStatus('error', '本次方案生成未完成，请检查参数或后端服务日志后重试。');
    }
    btnGenerate!.disabled = false;
  }

  function showRunError(e: Json) {
    if (formError) {
      formError.hidden = false;
      formError.textContent = `${e.code || 'ERROR'}：${e.message || '运行失败'}`;
    }
    setModalStatus('error', `${e.code || 'ERROR'}：${e.message || '运行失败'}`);
    pushDialog('error', `${e.code || 'ERROR'}：${e.message || '运行失败'}`);
  }

  async function pollRun(runId: string): Promise<string> {
    const deadline = Date.now() + 300_000;
    while (Date.now() < deadline) {
      try {
        const res = await fetch(`/api/proposals/${encodeURIComponent(runId)}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        applyStages(data);
        const s = data.status;
        if (s === 'done' || s === 'degraded' || s === 'needs_input' || s === 'failed') {
          if (s === 'failed' && data.error) showRunError(data.error);
          return s;
        }
      } catch { /* keep polling */ }
      await new Promise((r) => setTimeout(r, 500));
    }
    return 'timeout';
  }

  function applyStages(data: Json) {
    const list = data.agent?.stages || data.stages || [];
    const latest: Record<string, string> = {};
    list.forEach((s: Json) => {
      const id = s.id || s.stage;
      if (id) latest[id] = s.status || s.state;
    });
    let doneCount = 0;
    let activeId: string | null = null;
    STAGE_ORDER.forEach((id) => {
      const st = latest[id];
      let state = 'pending';
      if (st === 'done' || st === 'ready' || st === 'partial' || st === 'degraded') state = 'done';
      else if (st === 'active' || st === 'running' || st === 'needs_input') { state = 'active'; if (!activeId) activeId = id; }
      else if (st === 'skipped' || st === 'skip') state = 'skip';
      else if (st === 'failed' || st === 'error') state = 'error';
      setStage(id, state);
      if (state === 'done' || state === 'skip') doneCount += 1;
    });
    if (data.status === 'done' || data.status === 'degraded') {
      setStage('done', 'done');
      doneCount = STAGE_ORDER.length;
      activeId = null;
    } else if (data.status === 'failed') {
      setStage('done', 'error');
    }
    const pct = ((doneCount + (activeId ? 0.5 : 0)) / STAGE_ORDER.length) * 100;
    setStagesProgress(pct);
    const seconds = runStartedAt ? Math.round((Date.now() - runStartedAt) / 1000) : 0;
    if (modalElapsed) modalElapsed.textContent = `${seconds}s`;
    if (data.status === 'done' || data.status === 'degraded') setLive(`三套方案已生成 · 用时 ${seconds}s`);
    else if (data.status === 'failed') setLive('运行失败');
    else if (activeId) setLive(`Agent 正在${STAGE_LABELS[activeId] || activeId}…`);
  }

  // --- Events ---
  budgetSlider?.addEventListener('input', () => {
    syncBudgetUI(Number(budgetSlider.value), 'slider');
  });
  budgetNum?.addEventListener('input', () => {
    const v = Number(budgetNum.value);
    if (Number.isFinite(v) && v > 0) {
      syncBudgetUI(v, 'num');
    } else {
      syncFilledStates();
    }
  });
  budgetNum?.addEventListener('blur', () => {
    const v = Number(budgetNum.value);
    if (budgetNum.value.trim() && Number.isFinite(v) && v > 0) {
      syncBudgetUI(v, 'ext');
    } else {
      syncFilledStates();
    }
  });
  // --- Month-Only Datepicker (air-datepicker, view/minView locked to months) ---
  const MONTH_LOCALE = {
    days: ['周日', '周一', '周二', '周三', '周四', '周五', '周六'],
    daysShort: ['日', '一', '二', '三', '四', '五', '六'],
    daysMin: ['日', '一', '二', '三', '四', '五', '六'],
    months: ['1月', '2月', '3月', '4月', '5月', '6月', '7月', '8月', '9月', '10月', '11月', '12月'],
    monthsShort: ['1月', '2月', '3月', '4月', '5月', '6月', '7月', '8月', '9月', '10月', '11月', '12月'],
    today: '本月',
    clear: '清除',
    dateFormat: 'yyyy.MM',
    timeFormat: 'HH:mm',
    firstDay: 1,
  };
  const availableMonths = new Set<string>();
  let monthPicker: AirDatepicker<HTMLInputElement> | null = null;

  function toMonthDate(raw: string): Date | null {
    const parsed = parseStartMonth(raw);
    if (!parsed) return null;
    const [yr, mo] = parsed.display.split('.').map(Number);
    return new Date(yr, mo - 1, 1);
  }

  function syncStartMonth(raw: string) {
    if (!startInput) return;
    const parsed = parseStartMonth(raw);
    if (!parsed) {
      startInput.value = raw;
      syncFilledStates();
      return;
    }
    startInput.value = parsed.display;
    const d = toMonthDate(parsed.display);
    if (d && monthPicker) {
      monthPicker.selectDate(d, { silent: true });
      monthPicker.setViewDate(d);
    }
    syncFilledStates();
  }

  if (startInput) {
    const initDate = toMonthDate(startInput.value) || new Date(2027, 0, 1);
    monthPicker = new AirDatepicker(startInput, {
      locale: MONTH_LOCALE,
      view: 'months',
      minView: 'months',
      dateFormat: 'yyyy.MM',
      autoClose: true,
      selectedDates: [initDate],
      startDate: initDate,
      minDate: new Date(2024, 0, 1),
      maxDate: new Date(2032, 11, 1),
      classes: 'neu-month-picker',
      position: 'bottom left',
      navTitles: {
        months: 'yyyy 年',
        years: 'yyyy1 – yyyy2',
      },
      onShow: () => startMonthWrap?.classList.add('is-picker-open'),
      onHide: () => startMonthWrap?.classList.remove('is-picker-open'),
      onSelect: ({ formattedDate }) => {
        if (typeof formattedDate === 'string' && formattedDate) {
          startInput.value = formattedDate;
        }
        syncFilledStates();
      },
      onRenderCell: ({ date, cellType }) => {
        if (cellType !== 'month') return;
        const key = `${date.getFullYear()}.${String(date.getMonth() + 1).padStart(2, '0')}`;
        if (availableMonths.has(key)) {
          return {
            classes: 'has-inventory',
            attrs: { title: `${key} 已有实时库存快照` },
          };
        }
        return;
      },
    });

    btnStartPicker?.addEventListener('mousedown', (e) => e.preventDefault());
    btnStartPicker?.addEventListener('click', () => {
      if (!monthPicker) return;
      if (monthPicker.visible) monthPicker.hide();
      else {
        startInput.focus();
        monthPicker.show();
      }
    });
  }

  weeksInput?.addEventListener('blur', () => {
    if (weeksInput.value.trim()) {
      const n = Math.round(Number(weeksInput.value));
      if (Number.isFinite(n)) weeksInput.value = String(Math.max(2, n));
    }
    syncFilledStates();
  });

  // Live filled vs. unfilled Neumorphic state tracking across all form fields
  form!.addEventListener('input', syncFilledStates);
  form!.addEventListener('change', syncFilledStates);
  syncFilledStates();

  btnGenerate?.addEventListener('click', onGenerate);
  btnCloseRunModal?.addEventListener('click', closeRunModal);
  btnModalDismiss?.addEventListener('click', closeRunModal);
  runModalScrim?.addEventListener('click', closeRunModal);
  btnReopenProgress?.addEventListener('click', () => openRunModal());
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && runModal?.getAttribute('data-open') === 'true') {
      closeRunModal();
    }
  });

  // Focus-triggered recommendation dropdown under the target company/brand search input
  const venueCombo = $('#venue-combobox');
  const suggestPop = $('#loc-suggest-pop');
  const presetBtns = [...document.querySelectorAll<HTMLButtonElement>('[data-loc-preset]')];

  const filterSuggestPills = (raw: string) => {
    const q = raw.trim().toLowerCase();
    const isExactSelected = presetBtns.some((b) => b.classList.contains('is-active') && (b.textContent || '').trim().toLowerCase() === q);
    if (!q || isExactSelected) {
      presetBtns.forEach((b) => { b.hidden = false; });
      return;
    }
    let hits = 0;
    presetBtns.forEach((b) => {
      const txt = (b.textContent || '').toLowerCase();
      const match = txt.includes(q);
      b.hidden = !match;
      if (match) hits++;
    });
    if (hits === 0) presetBtns.forEach((b) => { b.hidden = false; });
  };

  const openSuggest = () => {
    if (!suggestPop) return;
    filterSuggestPills(venueQuery?.value || '');
    suggestPop.classList.add('is-open');
    venueQuery?.setAttribute('aria-expanded', 'true');
  };
  const closeSuggest = () => {
    if (!suggestPop) return;
    suggestPop.classList.remove('is-open');
    venueQuery?.setAttribute('aria-expanded', 'false');
  };

  venueQuery?.addEventListener('focus', openSuggest);
  venueQuery?.addEventListener('click', openSuggest);
  venueQuery?.addEventListener('input', () => {
    openSuggest();
    filterSuggestPills(venueQuery.value);
  });
  venueQuery?.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      closeSuggest();
      searchVenue();
    } else if (e.key === 'Escape') {
      closeSuggest();
    }
  });
  btnVenueSearch?.addEventListener('click', () => {
    closeSuggest();
    searchVenue();
  });
  presetBtns.forEach((btn) => {
    btn.addEventListener('mousedown', (e) => e.preventDefault());
    btn.addEventListener('click', () => {
      const id = btn.dataset.locPreset || '';
      if (id) applyLocationPreset(id);
      closeSuggest();
    });
  });
  document.addEventListener('pointerdown', (e) => {
    if (venueCombo && !venueCombo.contains(e.target as Node)) closeSuggest();
  });

  // Agent chat events
  btnChatSend?.addEventListener('click', () => sendConsultMessage(chatInput?.value || ''));
  chatInput?.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      sendConsultMessage(chatInput.value);
    }
  });
  document.querySelectorAll<HTMLButtonElement>('[data-consult-quick]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const txt = btn.dataset.consultQuick || '';
      if (txt) sendConsultMessage(txt);
    });
  });

  // Xinyun session status click-to-recheck
  xinyunPill?.addEventListener('click', refreshXinyunStatus);

  loadMeta();

  // --- Map initialization (live AMap if key available, else dynamic dark SVG StaticMap) ---
  (async () => {
    if (!mapFrame) return;
    const data = await loadMapData();
    mapData = data;
    if (!data) {
      mapFrame.setAttribute('data-mode', 'fallback');
      const n = $('[data-out="map-status"]');
      if (n) n.textContent = '暗色矢量地图';
      drawVenueSelection();
      return;
    }
    const kit = await loadAmap('amap');
    if (!kit) {
      mapFrame.setAttribute('data-mode', 'fallback');
      const n = $('[data-out="map-status"]');
      if (n) n.textContent = '暗色矢量地图';
      drawVenueSelection();
      return;
    }
    mapKit = { AMap: kit.AMap, map: kit.map };
    mapFrame.setAttribute('data-mode', 'live');
    const n = $('[data-out="map-status"]');
    const markLive = () => {
      if (n) n.textContent = '高德在线';
      drawVenueSelection();
    };
    if (n) n.textContent = '高德加载中';
    if (mapFrame.getAttribute('data-map-ready') === 'true') markLive();
    else mapFrame.addEventListener('amap-ready', markLive, { once: true });
    drawVenueSelection();
  })();
}
