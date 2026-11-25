// Input workbench controller:
// - Supports ANY custom Shanghai company/brand/landmark via /api/geocode (backed by xinyun-bigdata) + AMap + presets
// - Dynamically renders the exact selected location & rings on BOTH live AMap AND dark SVG StaticMap fallback
// - Interactive multi-turn Agent consultation via POST /api/agent/consult
// - Submits POST /api/proposals (generating 3 strategy variants + real xinyun coverage/routes/portrait)

import { loadAmap, loadMapData, wgsToGcj } from './amap';

type Json = Record<string, any>;

interface CustomVenue {
  id: string;
  name: string;
  district: string;
  address: string;
  coords: { lng: number; lat: number };
  rings_km: number[];
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
  const startSel = $<HTMLSelectElement>('#f-start');
  const weeksSel = $<HTMLSelectElement>('#f-weeks');
  const customerSel = $<HTMLSelectElement>('#f-customer');
  const budgetInput = $<HTMLInputElement>('#f-budget');
  const budgetVal = $('#budget-val');
  const briefInput = $<HTMLTextAreaElement>('#f-brief');
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
  const mapFrame = $('#input-map');

  let presets: PresetLoc[] = [...DEFAULT_PRESETS];
  let selectedVenueId = 'lego_shanghai';
  let customVenue: CustomVenue | null = null;
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

  function setStage(id: string, state: string) {
    const el = stagesEl?.querySelector<HTMLElement>(`[data-stage="${id}"]`);
    if (el) el.setAttribute('data-state', state);
  }
  function setStagesProgress(pct: number) {
    if (stagesEl) stagesEl.style.setProperty('--stage-progress', `${Math.max(0, Math.min(100, pct))}%`);
  }
  function setLive(text: string) {
    if (stageLive) stageLive.textContent = text;
  }
  function resetStages() {
    STAGE_ORDER.forEach((s) => setStage(s, 'pending'));
    setStagesProgress(0);
    setLive('等待启动');
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
      const nm = customVenue ? customVenue.name : (presets.find((x) => x.id === selectedVenueId)?.name || '目标地点');
      cardTitle.textContent = `目标定位与辐射圈 · ${nm}`;
    }
    // Sync preset pill highlight
    document.querySelectorAll<HTMLButtonElement>('[data-loc-preset]').forEach((b) => {
      const pid = b.dataset.locPreset || '';
      const active = customVenue ? customVenue.id === pid : selectedVenueId === pid;
      b.classList.toggle('is-active', active);
    });
  }

  function syncBudgetUI(val: number) {
    if (!budgetInput) return;
    budgetInput.value = String(val);
    if (budgetVal) budgetVal.textContent = String(val);
    document.querySelectorAll<HTMLButtonElement>('[data-budget-preset]').forEach((b) => {
      b.classList.toggle('is-active', b.dataset.budgetPreset === String(val));
    });
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
      c.setAttribute('stroke', '#d4a36a');
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
    pin.setAttribute('fill', '#e7c08e');
    pin.setAttribute('stroke', '#0a0c12');
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
    sub.setAttribute('fill', '#d4a36a');
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

    active.rings.slice(0, 2).forEach((km: number, idx: number) => {
      add(new AMap.Circle({
        center: origin,
        radius: Number(km) * 1000,
        strokeColor: '#d4a36a',
        strokeOpacity: idx === 0 ? 0.65 : 0.35,
        strokeWeight: idx === 0 ? 1.8 : 1.2,
        strokeStyle: 'dashed',
        fillColor: '#d4a36a',
        fillOpacity: idx === 0 ? 0.06 : 0,
      }));
    });

    const content = `<div class="amap-venue-marker is-selected"><i class="amap-pin amap-pin--venue"></i><span class="amap-venue">${escapeHtml(active.name)}${active.isCustom ? '<em>自定义</em>' : ''}</span></div>`;
    add(new AMap.Marker({ position: origin, content, offset: new AMap.Pixel(-8, -8), zIndex: 140 }));

    // Highlight nearest metro stations around active selected place
    const nearby = (mapData.metro || [])
      .filter((m: any) => Number.isFinite(Number(m.lng)) && Number.isFinite(Number(m.lat)))
      .map((m: any) => ({ m, d: distanceKm(origin, wgsToGcj(Number(m.lng), Number(m.lat))) }))
      .filter((x: any) => x.d <= 15)
      .sort((a: any, b: any) => a.d - b.d)
      .slice(0, 10);
    nearby.forEach(({ m }: any) => {
      const c = wgsToGcj(Number(m.lng), Number(m.lat));
      const nm = `${m.line || ''} ${m.exit || m.name || ''}`.trim();
      const mc = `<div class="amap-point-marker"><i class="amap-pin amap-pin--metro"></i><span class="amap-point-label">${escapeHtml(nm)}</span></div>`;
      add(new AMap.Marker({ position: c, content: mc, offset: new AMap.Pixel(-5, -5), zIndex: 100 }));
    });

    try {
      map.setZoomAndCenter(active.isCustom ? 12 : 11, origin);
    } catch { /* map not ready */ }
    const note = $('[data-map-note]');
    if (note) {
      note.textContent = `高德在线 · ${active.name}（${active.district || '上海'}） · ${active.rings.slice(0, 2).join('/')}km 圈层`;
    }
  }

  function applyLocationPreset(id: string) {
    const p = presets.find((x) => x.id === id);
    if (!p) return;
    if (p.preset) {
      selectedVenueId = p.id;
      customVenue = null;
      if (venueSel) venueSel.value = p.id;
    } else {
      selectedVenueId = 'custom';
      customVenue = {
        id: p.id,
        name: p.name,
        district: p.district,
        address: `上海市${p.district}${p.name}`,
        coords: { lng: p.coords.lng, lat: p.coords.lat },
        rings_km: [3, 8, 20],
      };
    }
    if (venueQuery) venueQuery.value = p.name;
    if (industrySel && p.industry) industrySel.value = p.industry;
    showVenueNote(`已选定「${p.name}」（${p.district} · ${p.industry}），地图已同步聚焦`);
    drawVenueSelection();
  }

  function applyCustomPlace(name: string, lng: number, lat: number, district = '', address = '', source = '') {
    selectedVenueId = 'custom';
    customVenue = {
      id: 'custom',
      name,
      district: district || '上海市',
      address: address || name,
      coords: { lng, lat },
      rings_km: [3, 8, 20],
    };
    if (venueQuery) venueQuery.value = name;
    drawVenueSelection();
    showVenueNote(`已锁定自定义地点「${name}」（${district || '上海'}，${lng.toFixed(4)}, ${lat.toFixed(4)}）${source ? ' · ' + source : ''}`);
  }

  async function searchVenue() {
    const q = venueQuery?.value?.trim() || '';
    if (!q) {
      showVenueNote('请输入公司名称、品牌或上海地点');
      return;
    }
    // Check exact preset match first
    const hitPreset = presets.find((p) => p.name === q || p.name.includes(q));
    if (hitPreset && q.length >= 2) {
      applyLocationPreset(hitPreset.id);
      return;
    }

    showVenueNote('正在通过新云地理编码定位…');
    // 1) Try backend /api/geocode (xinyun-bigdata /nearby/geocode + cache + Shanghai landmark fallback)
    try {
      const res = await fetch(`/api/geocode?q=${encodeURIComponent(q)}`);
      if (res.ok) {
        const g = await res.json();
        if (g.ok && Number.isFinite(Number(g.lng)) && Number.isFinite(Number(g.lat))) {
          applyCustomPlace(q, Number(g.lng), Number(g.lat), g.district || '', g.address || q, g.source || '');
          return;
        }
      }
    } catch { /* fallback to AMap JS if available */ }

    // 2) Fallback to AMap JS PlaceSearch if loaded
    const AMap = mapKit?.AMap;
    if (AMap?.PlaceSearch) {
      const place = new AMap.PlaceSearch({ city: '上海市', citylimit: false, pageSize: 5 });
      place.search(q, (status: string, result: any) => {
        const poi = result?.poiList?.pois?.[0];
        if (status === 'complete' && poi?.location) {
          applyCustomPlace(poi.name || q, Number(poi.location.getLng()), Number(poi.location.getLat()), poi.adname || '', poi.address || q, '高德 PlaceSearch');
        } else {
          showVenueNote('未找到该地点，换个上海地标/商圈词试试');
        }
      });
      return;
    }
    showVenueNote('未找到该地点，请检查关键词或确认本地服务运行中');
  }

  // --- Dialog helpers ---
  function pushDialog(role: 'user' | 'agent' | 'error', content: string | HTMLElement) {
    if (!dialog) return;
    const el = document.createElement('div');
    el.className = `msg msg--${role}`;
    if (typeof content === 'string') {
      el.textContent = content;
    } else {
      el.append(content);
    }
    dialog.append(el);
    dialog.scrollTop = dialog.scrollHeight;
  }

  function applyDraftFromAgent(draft: Json, geocoded?: Json) {
    if (!draft) return;
    if (draft.custom_venue && draft.custom_venue.name && draft.custom_venue.coords) {
      applyCustomPlace(
        draft.custom_venue.name,
        Number(draft.custom_venue.coords.lng),
        Number(draft.custom_venue.coords.lat),
        draft.custom_venue.district || geocoded?.district || '',
        draft.custom_venue.address || draft.custom_venue.name,
        geocoded?.source || 'Agent 定位',
      );
    } else if (draft.venue && presets.some((p) => p.id === draft.venue)) {
      applyLocationPreset(draft.venue);
    }
    if (draft.industry && industrySel) {
      const hasOpt = [...industrySel.options].some((o) => o.value === draft.industry);
      if (hasOpt) industrySel.value = draft.industry;
    }
    if (draft.strategy_mode && strategySel) strategySel.value = draft.strategy_mode;
    if (draft.budget_wan) syncBudgetUI(Number(draft.budget_wan));
    if (draft.weeks && weeksSel) weeksSel.value = String(draft.weeks);
    if (draft.start_date && startSel) {
      const hasOpt = [...startSel.options].some((o) => o.value === draft.start_date);
      if (hasOpt) startSel.value = draft.start_date;
    }
    if (draft.customer_type && customerSel) customerSel.value = draft.customer_type;
    if (Array.isArray(draft.media) && draft.media.length) {
      form!.querySelectorAll<HTMLInputElement>('input[name="media"]').forEach((c) => {
        c.checked = draft.media.includes(c.value);
      });
    }
    if (draft.brief_text && briefInput) briefInput.value = draft.brief_text;
  }

  async function sendConsultMessage(text: string) {
    const msg = text.trim();
    if (!msg) return;
    pushDialog('user', msg);
    chatHistory.push({ role: 'user', content: msg });
    if (chatInput) chatInput.value = '';
    if (btnChatSend) btnChatSend.disabled = true;

    try {
      const draft = readForm();
      const res = await fetch('/api/agent/consult', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: msg, draft, history: chatHistory.slice(-6) }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      if (data.draft) applyDraftFromAgent(data.draft, data.geocoded);

      const wrap = document.createElement('div');
      const head = document.createElement('div');
      head.className = 'msg__head';
      head.textContent = data.ready_to_run ? 'FLAIR AGENT · 需求已齐备' : 'FLAIR AGENT · 需求澄清';
      const body = document.createElement('div');
      body.style.whiteSpace = 'pre-line';
      body.textContent = String(data.reply || '').replace(/\*\*/g, '');
      wrap.append(head, body);

      const suggs: Json[] = data.suggestions || [];
      if (suggs.length) {
        const chips = document.createElement('div');
        chips.className = 'agent-chips';
        chips.style.marginTop = '8px';
        suggs.forEach((s) => {
          const b = document.createElement('button');
          b.type = 'button';
          b.className = s.action === 'generate' ? 'q-chip q-chip--primary' : 'q-chip';
          b.textContent = s.label || s.send_text || '';
          b.addEventListener('click', () => {
            if (s.action === 'generate') onGenerate();
            else if (s.send_text) sendConsultMessage(s.send_text);
          });
          chips.append(b);
        });
        wrap.append(chips);
      }
      pushDialog('agent', wrap);
      chatHistory.push({ role: 'assistant', content: data.reply || '' });
    } catch {
      pushDialog('error', '无法连接 Agent 顾问接口，请确认本地服务（127.0.0.1:8010）运行正常。');
    } finally {
      if (btnChatSend) btnChatSend.disabled = false;
    }
  }

  // --- Load /api/meta ---
  async function loadMeta() {
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
      if (startSel) {
        startSel.replaceChildren();
        const opts: Json[] = m.date_options || dates.map((d) => ({ value: d, label: d }));
        opts.forEach((d) => {
          const opt = document.createElement('option');
          opt.value = d.value;
          opt.textContent = d.label || d.value;
          startSel.append(opt);
        });
      }

      const ver = m.manifest?.data_version || m.data_version || '—';
      const ts = String(m.manifest?.fetched_at || m.inventory_ts || '—').replace('T', ' ').slice(0, 16);
      const months = (m.manifest?.files || []).map((f: any) => String(f.start || '').slice(0, 7)).filter(Boolean);
      const uniqMonths = [...new Set(months)];

      const setTxt = (sel: string, txt: string) => {
        const el = $(sel);
        if (el) el.textContent = txt;
      };
      setTxt('[data-out="data-version"]', ver);
      setTxt('[data-out="inventory-ts"]', ts);
      setTxt('[data-out="inventory-months"]', uniqMonths.length ? uniqMonths.join(' / ') : '2027 暑期');
      setTxt('[data-out="intro-fact"]', `引擎就绪 · CP-SAT 凹边际三方案模型 · ${ver}`);

      const xy = m.xinyun_session || {};
      const xyEl = $('[data-out="xinyun-status"]');
      if (xyEl) {
        if (xy.authenticated) {
          xyEl.textContent = '已登录 · 2023-05 实时就绪';
          xyEl.style.color = 'var(--emerald)';
        } else {
          xyEl.textContent = '未登录 · 自动降级';
          xyEl.style.color = 'var(--warn)';
        }
      }

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
      if (startSel && !startSel.options.length) {
        const opt = document.createElement('option');
        opt.value = '2027-07-01';
        opt.textContent = '2027 暑期（7–8 月）';
        startSel.append(opt);
      }
      drawVenueSelection();
    }
  }

  function readForm(): Json {
    const media = [...form!.querySelectorAll<HTMLInputElement>('input[name="media"]:checked')].map((c) => c.value);
    const inc = (lockInc?.value || '').split(/[,，\s]+/).map((s) => s.trim()).filter(Boolean);
    const exc = (lockExc?.value || '').split(/[,，\s]+/).map((s) => s.trim()).filter(Boolean);
    const req: Json = {
      industry: industrySel?.value || '乐园',
      venue: customVenue ? 'custom' : selectedVenueId,
      budget_wan: Number(budgetInput?.value || 300),
      media,
      start_date: startSel?.value || '2027-07-01',
      weeks: Number(weeksSel?.value || 8),
      customer_type: customerSel?.value || 'direct',
      strategy_mode: strategySel?.value || 'balanced',
      locks: { include: inc, exclude: exc },
      brief_text: briefInput?.value?.trim() || '',
    };
    if (customVenue) {
      req.custom_venue = customVenue;
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
    return true;
  }

  async function onGenerate() {
    // If the user typed a new company/place in #f-venue-query without clicking 定位, geocode it first!
    const typedPlace = venueQuery?.value?.trim() || '';
    const activeName = customVenue ? customVenue.name : (presets.find((p) => p.id === selectedVenueId)?.name || '');
    if (typedPlace && typedPlace !== activeName) {
      await searchVenue();
    }

    const req = readForm();
    if (!validateForm(req)) return;

    btnGenerate!.disabled = true;
    resetStages();
    runStartedAt = Date.now();
    setStage('intake', 'active');
    setStagesProgress(6);
    setLive('正在启动 Agent 管线…');
    runNote!.textContent = '已提交：实时红豆库存 + 新云周边覆盖/画像 + 三套确定性策略方案求解中…';

    const targetLabel = customVenue ? customVenue.name : (presets.find((p) => p.id === req.venue)?.name || req.venue);
    pushDialog('user', `启动生成：${targetLabel}（${req.industry}）· ${req.budget_wan} 万 · ${req.weeks} 周 · ${req.media.join('+')}`);

    if (liveTimer) window.clearInterval(liveTimer);
    liveTimer = window.setInterval(() => {
      const s = Math.round((Date.now() - runStartedAt) / 1000);
      if (stageLive && !stageLive.textContent?.includes('已生成')) {
        stageLive.textContent = `${stageLive.textContent?.split(' · 已用')[0] || '运行中'} · 已用 ${s}s`;
      }
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
        showRunError(err.error || { code: `HTTP_${res.status}`, message: '提交失败' });
        if (liveTimer) { window.clearInterval(liveTimer); liveTimer = null; }
        btnGenerate!.disabled = false;
        return;
      }
      const created = await res.json();
      runId = created.run_id;
    } catch {
      runNote!.textContent = '无法连接运行服务；可先查看演示方案';
      setLive('无法连接运行服务');
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
      runNote!.textContent = '方案已生成，正在跳转…';
      const variantParam = req.strategy_mode ? `&variant=${encodeURIComponent(req.strategy_mode)}` : '';
      window.location.href = `/result/overview.html?run=${encodeURIComponent(runId)}${variantParam}`;
    } else if (done === 'needs_input') {
      setLive('需要补充信息');
      runNote!.textContent = '需要补充信息（见上方 Agent 提示）';
    } else {
      setLive('运行超时或失败');
      runNote!.textContent = '运行未完成，请检查参数后重试';
    }
    btnGenerate!.disabled = false;
  }

  function showRunError(e: Json) {
    if (formError) {
      formError.hidden = false;
      formError.textContent = `${e.code || 'ERROR'}：${e.message || '运行失败'}`;
    }
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
      if (st === 'done' || st === 'ready' || st === 'degraded') state = 'done';
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
    if (data.status === 'done' || data.status === 'degraded') setLive(`三套方案已生成 · 用时 ${seconds}s`);
    else if (data.status === 'failed') setLive('运行失败');
    else if (activeId) setLive(`Agent 正在${STAGE_LABELS[activeId] || activeId}… · 已用 ${seconds}s`);
  }

  // --- Events ---
  budgetInput?.addEventListener('input', () => {
    if (budgetVal) budgetVal.textContent = budgetInput.value;
  });
  btnGenerate?.addEventListener('click', onGenerate);
  btnVenueSearch?.addEventListener('click', () => searchVenue());
  venueQuery?.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      searchVenue();
    }
  });
  document.querySelectorAll<HTMLButtonElement>('[data-loc-preset]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const id = btn.dataset.locPreset || '';
      if (id) applyLocationPreset(id);
    });
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
