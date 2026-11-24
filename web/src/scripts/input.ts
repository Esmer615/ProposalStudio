// Input page: form (GET /api/meta -> options) + agent analyze + proposal run (POST /api/proposals + poll).
// No open multi-turn chat; a bounded one-line brief + structured form + question chips that refill the form.
// Numbers come only from the run payload; this file never computes price/units.

import { loadAmap, loadMapData, wgsToGcj } from './amap';

type Json = any;

const $ = <T extends HTMLElement>(sel: string) => document.querySelector<T>(sel);

const form = $<HTMLElement>('#plan-form');
if (form) {
  const venueSel = $<HTMLSelectElement>('#f-venue');
  const venueQuery = $<HTMLInputElement>('#f-venue-query');
  const btnVenueSearch = $<HTMLButtonElement>('#btn-venue-search');
  const venueNote = $('#venue-search-note');
  const startSel = $<HTMLSelectElement>('#f-start');
  const budgetInput = $<HTMLInputElement>('#f-budget');
  const budgetVal = $('#budget-val');
  const dialog = $('#agent-dialog');
  const btnGenerate = $<HTMLButtonElement>('#btn-generate');
  const formError = $('#form-error');
  const stages = $('#run-stages');
  const stageLive = $('[data-out="stage-live"]');
  const runNote = $('#run-note');
  const mapFrame = $<HTMLElement>('#input-map');

  // --- map state (labels + custom place search) ---
  let mapKit: { AMap: any; map: any } | null = null;
  let mapData: { metro: any[]; poi: any[]; venues: any[] } | null = null;
  let mapOverlays: any[] = [];
  let selectedVenueId = 'lego_shanghai';
  let customVenue: { name: string; lng: number; lat: number; rings_km: number[] } | null = null;

  // --- defaults (fall back to hard-coded matches the handoff) ---
  const FALLBACK_VENUES = [
    { id: 'lego_shanghai', name: '上海乐高乐园度假区' },
    { id: 'disney_shanghai', name: '上海迪士尼度假区' },
    { id: 'haichang_shanghai', name: '上海海昌海洋公园' },
  ];
  const FALLBACK_DATES = [
    { value: '2027-07-01', label: '2027 暑期（7–8 月）' },
    { value: '2027-06-01', label: '2027 端午/初夏（6 月）' },
    { value: '2027-09-01', label: '2027 开学季（9 月）' },
    { value: '2027-10-01', label: '2027 国庆（10 月）' },
  ];

  function fillVenues(items: Json[]) {
    if (!venueSel) return;
    venueSel.replaceChildren();
    items.forEach((v) => {
      const o = document.createElement('option');
      o.value = v.id;
      o.textContent = v.name;
      venueSel.append(o);
    });
  }
  function fillDates(items: Json[]) {
    if (!startSel) return;
    startSel.replaceChildren();
    items.forEach((d) => {
      const o = document.createElement('option');
      o.value = d.value;
      o.textContent = d.label;
      startSel.append(o);
    });
  }

  async function loadMeta() {
    try {
      const res = await fetch('/api/meta');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const meta = await res.json();
      const venues = Array.isArray(meta.venues) && meta.venues.length ? meta.venues : FALLBACK_VENUES;
      const dates = Array.isArray(meta.date_options) && meta.date_options.length ? meta.date_options : FALLBACK_DATES;
      fillVenues(venues);
      fillDates(dates);
      // Start from the server's default request (乐高 / 500 万 / 2027-07-01 / 8 周 / 直客),
      // not from whichever option happens to sort first.
      const def = meta.default_request || {};
      const pick = (sel: HTMLSelectElement | null, value: unknown) => {
        if (!sel || value == null) return;
        const v = String(value);
        if ([...sel.options].some((o) => o.value === v)) sel.value = v;
      };
      pick(venueSel, def.venue);
      selectedVenueId = venueSel?.value || 'lego_shanghai';
      drawVenueSelection();
      pick(startSel, def.start_date);
      pick($<HTMLSelectElement>('#f-weeks'), def.weeks);
      pick($<HTMLSelectElement>('#f-customer'), def.customer_type);
      if (budgetInput && def.budget_wan != null) {
        budgetInput.value = String(def.budget_wan);
        if (budgetVal) budgetVal.textContent = String(def.budget_wan);
      }
      if (meta.budget_range?.min) budgetInput!.min = String(meta.budget_range.min);
      if (meta.budget_range?.max) budgetInput!.max = String(meta.budget_range.max);
      // data status from /api/meta's manifest; the covered months are the snapshot files' starts.
      const mf = meta.manifest || {};
      const monthList = (Array.isArray(mf.files) ? mf.files : [])
        .map((f: Json) => String(f.start || '').slice(0, 7))
        .filter(Boolean);
      const fromFiles = [...new Set(monthList)].sort();
      const fromPeriod = [...new Set(String(mf.inventory_period || '').match(/\d{4}-\d{2}/g) || [])].sort();
      setStatus({
        version: mf.data_version || meta.data_version || '—',
        ts: mf.inventory_ts || mf.fetched_at || '—',
        months: fromFiles.length ? fromFiles : fromPeriod,
      });
    } catch {
      fillVenues(FALLBACK_VENUES);
      fillDates(FALLBACK_DATES);
      setStatus({ version: '—', ts: '—', months: [] });
      setXinyun('offline');
    }
  }

  function setStatus(s: { version: string; ts: string; months: string[] | null }) {
    const v = $('[data-out="data-version"]');
    const v2 = $('[data-out="data-version-2"]');
    const ts = $('[data-out="inventory-ts"]');
    const months = $('[data-out="inventory-months"]');
    const fact = $('[data-out="intro-fact"]');
    const monthOf = (m: string) => String(m).slice(0, 7);
    const monthsList = Array.isArray(s.months) ? s.months.map(monthOf) : [];
    const years = [...new Set(monthsList.map((m) => m.slice(0, 4)))];
    const monthText = monthsList.length
      ? years.length === 1
        ? `${years[0]}-${monthsList.map((m) => m.slice(5, 7)).join(' / ')}`
        : monthsList.join(' / ')
      : '';
    const tsText = String(s.ts || '—').replace('T', ' ').slice(0, 16);
    if (v) v.textContent = s.version;
    if (v2) v2.textContent = s.version;
    if (ts) ts.textContent = tsText;
    if (months) months.textContent = monthText || '—';
    if (fact) {
      fact.textContent = `${monthText || '2027 年可售快照'} · 红豆库存 + 公开 POI · 数据版本 ${s.version || '—'} · 库存时间 ${tsText}`;
    }
    document.querySelectorAll<HTMLElement>('[data-meta-version]').forEach((el) => { el.textContent = s.version || '—'; });
    document.querySelectorAll<HTMLElement>('[data-meta-ts]').forEach((el) => { el.textContent = tsText; });
  }

  function setXinyun(state: 'maybe' | 'offline' | 'active') {
    const st = $('[data-out="xinyun-status"]');
    const note = $('[data-out="xinyun-note"]');
    if (!st) return;
    if (state === 'active') {
      st.textContent = '已登录（补充图层可用）';
      st.className = 'chip chip--accent';
    } else if (state === 'maybe') {
      st.textContent = '2023-05 · 未登录';
      st.className = 'chip chip--warn';
    } else {
      st.textContent = '未连接';
      st.className = 'chip chip--quiet';
    }
  }

  // --- validation (per 契约 §1) ---
  function validate(): { ok: boolean; errors: Record<string, string> } {
    const errors: Record<string, string> = {};
    const media = [...form!.querySelectorAll<HTMLInputElement>('input[name="media"]')].filter((c) => c.checked);
    if (media.length === 0) errors.media = '至少选择一种媒介';
    const budget = Number(budgetInput!.value);
    if (Number.isNaN(budget) || budget < 100 || budget > 500) errors.budget = '预算需在 100–500 万之间';
    if (!startSel!.value) errors.start = '请选择档期';
    return { ok: Object.keys(errors).length === 0, errors };
  }

  function showErrors(errors: Record<string, string>) {
    form!.querySelectorAll<HTMLElement>('[data-error]').forEach((el) => {
      const k = el.dataset.error!;
      const msg = errors[k] || '';
      el.textContent = msg;
      el.hidden = !msg;
      if (k === 'media') {
        const inp = form!.querySelector<HTMLInputElement>('#f-media-group input');
        if (inp) inp.setAttribute('aria-invalid', msg ? 'true' : 'false');
      }
    });
  }

  // --- agent dialog ---
  function pushDialog(kind: 'user' | 'agent' | 'error', body: string | Node) {
    if (!dialog) return;
    const el = document.createElement('div');
    el.className = `msg msg--${kind === 'error' ? 'error' : kind}`;
    if (typeof body === 'string') {
      el.textContent = body;
    } else {
      el.append(body);
    }
    dialog.append(el);
    dialog.scrollTop = dialog.scrollHeight;
  }

  function focusField(name: string | undefined) {
    if (!name) return;
    const map: Record<string, string> = {
      venue: '#f-venue',
      budget_wan: '#f-budget',
      budget: '#f-budget',
      media: '#f-media-group',
      start_date: '#f-start',
      weeks: '#f-weeks',
      customer_type: '#f-customer',
    };
    const s = map[name] || map[name.replace('request.', '')] || '';
    if (s) document.querySelector<HTMLElement>(s)?.focus();
  }

  function collectRequest(): Json {
    const media = [...form!.querySelectorAll<HTMLInputElement>('input[name="media"]')].filter((c) => c.checked).map((c) => c.value);
    const include = $<HTMLInputElement>('#f-lock-include')?.value;
    const exclude = $<HTMLInputElement>('#f-lock-exclude')?.value;
    const split = (s?: string) => (s ? s.split(/[,，]/).map((x) => x.trim()).filter(Boolean) : []);
    return {
      industry: '乐园',
      venue: venueSel!.value,
      budget_wan: Number(budgetInput!.value),
      media,
      start_date: startSel!.value,
      weeks: Number($<HTMLSelectElement>('#f-weeks')!.value),
      customer_type: $<HTMLSelectElement>('#f-customer')!.value,
      locks: { include: split(include), exclude: split(exclude) },
      brief_text: $<HTMLTextAreaElement>('#f-brief')?.value?.trim() || null,
    };
  }

  // --- run stage timeline ---
  const STAGE_ORDER = ['intake', 'data_inventory', 'data_bigdata', 'engine', 'data_routes', 'visualize', 'narrative', 'done'];
  const STAGE_LABELS: Record<string, string> = {
    intake: '解析需求',
    data_inventory: '实时取数',
    data_bigdata: '补充数据',
    engine: '求解',
    data_routes: '线路几何',
    visualize: '可视化',
    narrative: '解释',
    done: '完成',
  };
  let runStartedAt = 0;
  let liveTimer: number | null = null;

  function setStage(id: string, state: string) {
    const el = stages?.querySelector<HTMLElement>(`[data-stage="${id}"]`);
    if (el) el.dataset.state = state;
  }
  function setStagesProgress(pct: number) {
    if (stages) stages.style.setProperty('--stage-progress', `${Math.max(0, Math.min(100, pct))}%`);
  }
  function setLive(text: string) {
    if (stageLive) stageLive.textContent = text;
  }
  function resetStages() {
    STAGE_ORDER.forEach((s) => setStage(s, 'pending'));
    setStagesProgress(0);
    setLive('等待生成');
    if (liveTimer) { window.clearInterval(liveTimer); liveTimer = null; }
  }
  function startLiveTimer() {
    if (liveTimer) window.clearInterval(liveTimer);
    liveTimer = window.setInterval(() => {
      if (!runStartedAt) return;
      const seconds = Math.round((Date.now() - runStartedAt) / 1000);
      const active = STAGE_ORDER.find((id) => stages?.querySelector<HTMLElement>(`[data-stage="${id}"]`)?.dataset.state === 'active');
      if (active) setLive(`Agent 正在${STAGE_LABELS[active] || active}… · 已用 ${seconds}s`);
    }, 500);
  }

  async function onGenerate() {
    resetStages();
    const { ok, errors } = validate();
    showErrors(errors);
    if (!ok) {
      runNote!.textContent = '请先修正表单校验错误';
      return;
    }
    if (!btnGenerate) return;
    btnGenerate.disabled = true;
    runStartedAt = Date.now();
    startLiveTimer();
    runNote!.textContent = '启动运行…';
    setStage('intake', 'active');
    setLive('Agent 正在解析需求… · 已用 0s');
    pushDialog('agent', '已启动：后台会强制实时拉取红豆与新云数据，取数约需 1–2 分钟，请稍候。');

    const brief = $<HTMLTextAreaElement>('#f-brief')?.value?.trim() || '';
    const body = {
      brief_text: brief,
      request: collectRequest(),
      options: { data_mode: 'auto', include_elasticity: true, include_plan_artifacts: true, allow_defaults: false },
    };

    let runId: string | null = null;
    try {
      const res = await fetch('/api/proposals', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (res.status === 404 || res.status === 501) {
        runNote!.textContent = '运行服务尚未就绪（后端并行实现中）；可先看演示方案';
        setLive('运行服务未就绪');
        offerDemo();
        if (liveTimer) { window.clearInterval(liveTimer); liveTimer = null; }
        return;
      }
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        const e = err.error || {};
        showRunError(e);
        setLive('运行启动失败');
        if (liveTimer) { window.clearInterval(liveTimer); liveTimer = null; }
        btnGenerate.disabled = false;
        return;
      }
      const created = await res.json();
      runId = created.run_id;
    } catch {
      runNote!.textContent = '无法连接运行服务；可先看演示方案';
      setLive('无法连接运行服务');
      if (liveTimer) { window.clearInterval(liveTimer); liveTimer = null; }
      offerDemo();
      btnGenerate.disabled = false;
      return;
    }

    if (!runId) return;

    // poll
    const done = await pollRun(runId);
    if (liveTimer) { window.clearInterval(liveTimer); liveTimer = null; }
    if (done === 'done' || done === 'degraded') {
      try { localStorage.setItem('lastRunId', runId!); } catch { /* private mode */ }
      setLive('方案已生成，正在打开结果页…');
      runNote!.textContent = '方案已生成，正在跳转…';
      window.location.href = `/result/overview.html?run=${encodeURIComponent(runId)}`;
    } else if (done === 'needs_input') {
      setLive('需要补充信息');
      runNote!.textContent = '需要补充信息（见上方 Agent 提示），请调整后重试';
    } else {
      setLive('运行超时或未完成');
      runNote!.textContent = '运行超时或未完成，请稍后重试';
    }
    btnGenerate.disabled = false;
  }

  function offerDemo() {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'btn btn--secondary';
    b.style.marginLeft = '12px';
    b.textContent = '查看演示方案';
    b.addEventListener('click', () => {
      window.location.href = '/result/overview.html?run=demo';
    });
    btnGenerate!.after(b);
  }

  function showRunError(e: Json) {
    if (formError) {
      const code = e.code || 'INTERNAL';
      const msg = e.message || '运行失败';
      const sug = e.suggestions && e.suggestions.length ? `建议：${e.suggestions.join('；')}` : '';
      formError.textContent = `${code}：${msg}${sug ? '。' + sug : ''}`;
    }
  }

  async function pollRun(runId: string): Promise<string> {
    // 强制实时取数约 1–2 分钟；给足余量，避免状态条提前超时。
    const deadline = Date.now() + 300_000;
    while (Date.now() < deadline) {
      try {
        const res = await fetch(`/api/proposals/${encodeURIComponent(runId)}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        applyStages(data);
        const s = data.status;
        if (s === 'done' || s === 'degraded' || s === 'needs_input' || s === 'failed') {
          if (s === 'needs_input' && data.agent?.questions) renderOnRunQuestions(data.agent.questions);
          return s;
        }
      } catch {
        // keep polling; the run may not be ready yet
      }
      await sleep(500);
    }
    return 'timeout';
  }

  function applyStages(data: Json) {
    // 后端进度在 agent.stages；顶层 stages 仅兼容旧响应。
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
    if (data.status === 'done' || data.status === 'degraded') setLive(`方案已生成 · 用时 ${seconds}s`);
    else if (data.status === 'failed') setLive('运行失败');
    else if (data.status === 'needs_input') setLive('需要补充信息');
    else if (activeId) setLive(`Agent 正在${STAGE_LABELS[activeId] || activeId}… · 已用 ${seconds}s`);
  }

  function renderOnRunQuestions(questions: Json[]) {
    if (!questions?.length) return;
    const wrap = document.createElement('div');
    const head = document.createElement('div');
    head.className = 'msg__head';
    head.textContent = '运行需要补充';
    const ql = document.createElement('div');
    ql.style.display = 'grid';
    ql.style.gap = '6px';
    questions.forEach((q: any) => {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'q-chip';
      b.textContent = q.question || q.message || JSON.stringify(q);
      b.addEventListener('click', () => focusField(q.field));
      ql.append(b);
    });
    wrap.append(head, ql);
    pushDialog('agent', wrap);
  }

  function sleep(ms: number) { return new Promise((r) => setTimeout(r, ms)); }

  // --- map labels + custom place query ---
  function escapeHtml(s: string): string {
    return String(s).replace(/[<>&"]/g, (c) => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;', '"': '&quot;' }[c] || c));
  }
  function showVenueNote(msg: string) {
    if (!venueNote) return;
    venueNote.textContent = msg;
    venueNote.hidden = !msg;
  }
  function distanceKm(a: [number, number], b: [number, number]): number {
    const R = 6371;
    const dLat = (b[1] - a[1]) * Math.PI / 180;
    const dLng = (b[0] - a[0]) * Math.PI / 180;
    const la1 = a[1] * Math.PI / 180;
    const la2 = b[1] * Math.PI / 180;
    const h = Math.sin(dLat / 2) ** 2 + Math.cos(la1) * Math.cos(la2) * Math.sin(dLng / 2) ** 2;
    return 2 * R * Math.asin(Math.min(1, Math.sqrt(h)));
  }

  function drawVenueSelection() {
    if (!mapKit || !mapData) return;
    const { AMap, map } = mapKit;
    if (mapOverlays.length) mapOverlays.forEach((overlay) => map.remove(overlay));
    mapOverlays = [];
    const add = (overlay: any) => { map.add(overlay); mapOverlays.push(overlay); };

    let center: [number, number] | null = null;
    let rings: number[] = [6, 20, 50];
    let selectedName = '';
    if (customVenue) {
      center = [customVenue.lng, customVenue.lat];
      rings = customVenue.rings_km;
      selectedName = customVenue.name;
    } else {
      const v = mapData.venues.find((x: any) => x.id === selectedVenueId) || mapData.venues[0];
      if (v?.coords?.lng) {
        center = wgsToGcj(Number(v.coords.lng), Number(v.coords.lat));
        rings = v.rings_km || [6, 20, 50];
        selectedName = v.name;
      }
    }
    if (!center) return;
    const origin = center;

    // rings for the selected venue / custom place only (not all three at once)
    rings.slice(0, 2).forEach((km: number) => {
      add(new AMap.Circle({ center: origin, radius: Number(km) * 1000, strokeColor: '#d4a36a', strokeOpacity: 0.55, strokeWeight: 1.4, strokeStyle: 'dashed', fillOpacity: 0 }));
    });

    // venue markers always carry a name label; the selected one is highlighted
    for (const v of mapData.venues) {
      if (!v.coords?.lng) continue;
      const c = wgsToGcj(Number(v.coords.lng), Number(v.coords.lat));
      const isSel = !customVenue && v.id === selectedVenueId;
      const content = `<div class="amap-venue-marker${isSel ? ' is-selected' : ''}"><i class="amap-pin amap-pin--venue"></i><span class="amap-venue">${escapeHtml(v.name)}</span></div>`;
      add(new AMap.Marker({ position: c, content, offset: new AMap.Pixel(-8, -8), zIndex: isSel ? 130 : 110 }));
    }
    if (customVenue) {
      const content = `<div class="amap-venue-marker is-selected"><i class="amap-pin amap-pin--venue"></i><span class="amap-venue">${escapeHtml(customVenue.name)}<em>自定义</em></span></div>`;
      add(new AMap.Marker({ position: origin, content, offset: new AMap.Pixel(-8, -8), zIndex: 140 }));
    }

    // nearest metro exits get tiny dots + names so the legend is meaningful
    const nearby = mapData.metro
      .filter((m: any) => Number.isFinite(Number(m.lng)) && Number.isFinite(Number(m.lat)))
      .map((m: any) => ({ m, d: distanceKm(origin, [Number(m.lng), Number(m.lat)]) }))
      .filter((x: any) => x.d <= 50)
      .sort((a: any, b: any) => a.d - b.d)
      .slice(0, 8);
    nearby.forEach(({ m }: any) => {
      const c = wgsToGcj(Number(m.lng), Number(m.lat));
      const name = `${m.line || ''} ${m.exit || m.name || ''}`.trim();
      const content = `<div class="amap-point-marker"><i class="amap-pin amap-pin--metro"></i><span class="amap-point-label">${escapeHtml(name)}</span></div>`;
      add(new AMap.Marker({ position: c, content, offset: new AMap.Pixel(-5, -5), zIndex: 100 }));
    });

    // Keep the target venue centered so its name label never falls outside the frame.
    try { map.setZoomAndCenter(11, origin); } catch { /* map may not be ready */ }
    const note = $('[data-map-note]');
    if (note) note.textContent = customVenue
      ? `自定义地点 · ${customVenue.name} · 6/20km 圈层`
      : `高德在线 · ${selectedName} · 6/20km 圈层`;
  }

  function applyCustomPlace(name: string, lng: number, lat: number) {
    customVenue = { name, lng, lat, rings_km: [6, 20, 50] };
    drawVenueSelection();
    showVenueNote(`地图已定位：${name}。方案将按左侧所选预设场馆生成。`);
    pushDialog('agent', `已在地图上定位「${name}」。自定义地点仅用于地图定位预览；生成方案继续使用左侧所选预设场馆。`);
  }

  function searchVenue() {
    const q = venueQuery?.value?.trim() || '';
    if (!q) { showVenueNote('请输入地点名称'); return; }
    const AMap = mapKit?.AMap;
    if (!AMap?.PlaceSearch && !AMap?.Geocoder) {
      showVenueNote('地图未加载或无高德 Key，暂时无法查询地点');
      return;
    }
    showVenueNote('查询中…');
    const fallbackGeocode = () => {
      if (!AMap?.Geocoder) { showVenueNote('未找到该地点，换个关键词试试'); return; }
      const geocoder = new AMap.Geocoder({ city: '上海市', citylimit: false });
      geocoder.getLocation(q, (status: string, result: any) => {
        const g = result?.geocodes?.[0];
        if (status === 'complete' && g?.location) {
          applyCustomPlace(g.formattedAddress || q, Number(g.location.getLng()), Number(g.location.getLat()));
        } else {
          showVenueNote('未找到该地点，换个关键词试试');
        }
      });
    };
    if (!AMap?.PlaceSearch) { fallbackGeocode(); return; }
    const place = new AMap.PlaceSearch({ city: '上海市', citylimit: false, pageSize: 5 });
    place.search(q, (status: string, result: any) => {
      const poi = result?.poiList?.pois?.[0];
      if (status === 'complete' && poi?.location) {
        applyCustomPlace(poi.name || q, Number(poi.location.getLng()), Number(poi.location.getLat()));
      } else {
        fallbackGeocode();
      }
    });
  }

  // --- events ---
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
  venueSel?.addEventListener('change', () => {
    selectedVenueId = venueSel.value;
    customVenue = null;
    showVenueNote('');
    drawVenueSelection();
  });

  loadMeta();

  // --- map (venue preview + rings + labels + POI + metro) ---
  (async () => {
    if (!mapFrame) return;
    const data = await loadMapData();
    if (!data) {
      mapFrame.setAttribute('data-mode', 'fallback');
      const n = $('[data-out="map-status"]');
      if (n) n.textContent = '静态图层';
      const note = $('[data-map-note]');
      if (note) note.textContent = '静态图层预览';
      return;
    }
    mapData = data;
    const kit = await loadAmap('amap');
    if (!kit) {
      mapFrame.setAttribute('data-mode', 'fallback');
      const n = $('[data-out="map-status"]');
      if (n) n.textContent = '无高德 Key · 静态图层';
      const note = $('[data-map-note]');
      if (note) note.textContent = '静态图层预览（无高德 Key）';
      return;
    }
    mapKit = { AMap: kit.AMap, map: kit.map };
    mapFrame.setAttribute('data-mode', 'live');
    const n = $('[data-out="map-status"]');
    const note = $('[data-map-note]');
    const markLive = () => {
      if (n) n.textContent = '高德在线';
      drawVenueSelection();
    };
    if (n) n.textContent = '高德加载中';
    if (note) note.textContent = '高德加载中 · 静态预览';
    if (mapFrame.getAttribute('data-map-ready') === 'true') markLive();
    else mapFrame.addEventListener('amap-ready', markLive, { once: true });
    const { AMap, map } = kit;
    // POI heat (optional)
    try {
      const heat = new AMap.HeatMap(map, { radius: 24, opacity: [0, 0.55], gradient: { 0.35: 'rgba(46,91,68,0)', 0.7: 'rgba(46,91,68,.2)', 1: 'rgba(46,91,68,.5)' } });
      heat.setDataSet({ data: data.poi.map((p: any) => { const [lng, lat] = wgsToGcj(Number(p.lng), Number(p.lat)); return [lng, lat, 1]; }), max: 2 });
    } catch { /* heatmap optional */ }
    drawVenueSelection();
    setXinyun('maybe');
  })();
}
