// Result pages: read `?run=` and optional `?variant=` and load the shared run payload.
// Four tabs reuse the same run id and active strategy variant (balanced | max_reach | precision).
// No result page re-solves — numbers come strictly from the persisted run payload.

import type { Plan, ProposalRun } from '../lib/plan';

export type RenderFn = (plan: Plan, run: Partial<ProposalRun>, activeVariant?: string) => void;

const VARIANT_LABELS: Record<string, string> = {
  balanced: '均衡首选',
  max_reach: '全域广度',
  precision: '地标聚焦',
};

export function getRunId(): string | null {
  const p = new URLSearchParams(location.search);
  return p.get('run');
}

export function getVariant(): string | null {
  const p = new URLSearchParams(location.search);
  const v = p.get('variant');
  return v && ['balanced', 'max_reach', 'precision'].includes(v) ? v : null;
}

export function isDemo(): boolean {
  return getRunId() === 'demo';
}

export function buildPdfUrl(runId: string, docKey: string, variant?: string | null): string {
  const enc = encodeURIComponent(runId);
  const base = docKey === 'proposal' ? `/proposals/${enc}.pdf` : `/proposals/${enc}/${docKey}.pdf`;
  return variant && ['balanced', 'max_reach', 'precision'].includes(variant)
    ? `${base}?variant=${encodeURIComponent(variant)}`
    : base;
}

export function navigateVariant(mode: string) {
  const u = new URL(location.href);
  u.searchParams.set('variant', mode);
  location.href = u.toString();
}

function fixtureUrl(): string {
  return '/data/fixtures/plan-lego-500.json';
}

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json() as Promise<T>;
}

/** Load the plan (and selected strategy variant if present) for the current ?run=. */
export async function loadRun(): Promise<{
  plan: Plan;
  run: Partial<ProposalRun>;
  source: 'api' | 'fixture';
  activeVariant: string;
} | null> {
  const runId = getRunId();
  if (!runId) return null;

  if (runId === 'demo') {
    const plan = await fetchJson<Plan>(fixtureUrl()).catch(() => null);
    if (!plan) return null;
    return { plan, run: { run_id: 'demo', status: 'degraded' }, source: 'fixture', activeVariant: 'balanced' };
  }

  let run: any;
  try {
    const res = await fetch(`/api/proposals/${encodeURIComponent(runId)}`);
    if (!res.ok) return null;
    run = await res.json();
  } catch {
    return null;
  }

  if (run.status === 'done' || run.status === 'degraded') {
    const variants = run.variants;
    const requestedVariant = getVariant();
    const defaultVariant = variants?.selected_mode || variants?.default_mode || 'balanced';
    const activeVariant =
      requestedVariant && variants?.plans?.[requestedVariant]
        ? requestedVariant
        : (variants?.plans?.[defaultVariant] ? defaultVariant : 'balanced');
    const chosenPlan: Plan | null =
      (variants?.plans && variants.plans[activeVariant]) || run.plan || null;
    return chosenPlan ? { plan: chosenPlan, run, source: 'api', activeVariant } : null;
  }
  return null;
}

export function setFooterData(plan: Plan) {
  const m = plan.meta || {};
  document.querySelectorAll<HTMLElement>('[data-meta-version]').forEach((el) => (el.textContent = m.data_version || '—'));
  document.querySelectorAll<HTMLElement>('[data-meta-ts]').forEach((el) => (el.textContent = String(m.inventory_ts || '—').replace('T', ' ').slice(0, 16)));
}

export function showEmpty(message?: string) {
  const empty = document.querySelector<HTMLElement>('[data-result-empty]');
  const content = document.querySelector<HTMLElement>('[data-result-content]');
  if (empty) {
    empty.hidden = false;
    const body = empty.querySelector('[data-empty-body]');
    if (body && message) body.textContent = message;
  }
  if (content) content.hidden = true;
}

export function showStatus(status: string) {
  const bar = document.querySelector<HTMLElement>('[data-result-status]');
  if (bar) {
    bar.hidden = false;
    const s = bar.querySelector('[data-status-text]');
    if (s) s.textContent = status === 'failed' ? '运行失败，请返回输入页重试' : status === 'queued' ? '排队中' : status === 'running' ? '运行中，请稍候' : status === 'needs_input' ? '需要补充输入' : status;
  }
  const content = document.querySelector<HTMLElement>('[data-result-content]');
  if (content) content.hidden = true;
}

export async function initResult(render: RenderFn) {
  const content = document.querySelector<HTMLElement>('[data-result-content]');
  if (!content) return;
  const loaded = await loadRun();
  if (!loaded) {
    const runId = getRunId();
    showEmpty(runId ? `方案 ${runId} 未生成或运行服务未就绪。请返回输入页重新生成。` : undefined);
    return;
  }
  const { plan, run, source, activeVariant } = loaded;
  content.hidden = false;
  setFooterData(plan);
  renderStatus(plan, run, source, activeVariant);
  render(plan, run, activeVariant);
}

function formatYm(val: unknown): string {
  const s = String(val || '').trim();
  const m = s.match(/^(\d{4})-?(\d{2})/);
  return m ? `${m[1]}-${m[2]}` : s;
}

function formatMonthRange(months: unknown): string {
  if (!Array.isArray(months) || !months.length) return '';
  const clean = Array.from(new Set(months.map(formatYm).filter(Boolean))).sort();
  if (!clean.length) return '';
  return clean.length === 1 ? clean[0] : `${clean[0]} 至 ${clean[clean.length - 1]}`;
}

function translateReasonZh(reason: unknown, dataMonth = '2023-05'): string {
  const code = String(reason || '').trim();
  const map: Record<string, string> = {
    NOT_FOUND: `新云 ${dataMonth} 平台库查无此线`,
    MANUAL_LOGIN_REQUIRED: '新云会话未登录或已过期',
    SESSION_EXPIRED: '新云会话已过期',
    BIGDATA_UNAVAILABLE: '新云接口拉取失败',
    BATCH_UNAVAILABLE: '新云批量轨迹接口超时或失败',
    PORTRAIT_UNAVAILABLE: '新云人群画像接口拉取失败',
    PARTIAL_ROUTES: `部分线路在新云 ${dataMonth} 库查无轨迹`,
  };
  return map[code] || code || '外部数据源返回异常';
}

function deriveInventoryRange(inv: any, plan: Plan): string {
  const fromInv = formatMonthRange(inv?.months);
  if (fromInv) return fromInv;
  const start = formatYm(plan?.schedule?.start_date || plan?.inputs?.start_date);
  const end = formatYm(plan?.schedule?.end_date);
  if (start && end) return start === end ? start : `${start} 至 ${end}`;
  return start || '—';
}

function synthesizeDataDelivery(plan: Plan, run: Partial<ProposalRun>, source: 'api' | 'fixture'): {
  acquired: string[];
  failures: string[];
} {
  if (source === 'fixture') {
    const rng = deriveInventoryRange(null, plan);
    return {
      acquired: [`本地演示样本数据（${rng} 档期）`],
      failures: [],
    };
  }

  const data = (run.data as any) || {};
  const report = data.report;
  if (report && (Array.isArray(report.acquired) || Array.isArray(report.failures))) {
    const acquired: string[] = (report.acquired || []).map((x: any) => String(x || '').trim()).filter(Boolean);
    const failures: string[] = (report.failures || [])
      .map((f: any) => (typeof f === 'string' ? f : String(f?.detail || '').trim()))
      .filter(Boolean);
    return { acquired, failures };
  }

  // Fallback synthesis for persisted runs created before data.report was introduced
  const acquired: string[] = [];
  const failures: string[] = [];
  const inv = data.inventory;
  const bd = data.bigdata;
  const routes = data.routes;
  const portrait = data.portrait;

  const invRange = deriveInventoryRange(inv, plan);
  if (inv) {
    if (inv.status === 'done') {
      acquired.push(`红豆实时库存（${invRange}）`);
    } else {
      const err = String(inv.snapshot?.summary || inv.snapshot?.error || '实时拉取失败').trim();
      failures.push(`红豆实时库存（${invRange}）拉取失败：${err}，已回退本地快照`);
    }
  }

  const bdMonth = formatYm(bd?.data_month || '202305') || '2023-05';
  if (bd) {
    const covOk = bd.coverage?.status === 'ready' || bd.coverage?.ok;
    const poiOk = bd.poi?.status === 'ready' || bd.poi?.ok;
    const covTotal = Number(bd.coverage?.summary?.total ?? ((bd.coverage?.summary?.bus || 0) + (bd.coverage?.summary?.metro || 0)));
    const poiTotal = Number(bd.poi?.total ?? 0);
    if (covOk && poiOk) {
      acquired.push(`新云 ${bdMonth} 周边覆盖（${covTotal} 条）/ POI（${poiTotal} 个）`);
    } else {
      if (covOk) acquired.push(`新云 ${bdMonth} 周边覆盖（${covTotal} 条）`);
      if (poiOk) acquired.push(`新云 ${bdMonth} 周边 POI（${poiTotal} 个）`);
      if (bd.status === 'skipped' || bd.reason === 'MANUAL_LOGIN_REQUIRED') {
        failures.push(`新云 ${bdMonth} 周边覆盖与 POI 未获取（新云会话未登录或已过期）`);
      } else {
        if (!covOk) failures.push(`新云 ${bdMonth} 周边覆盖未获取（${translateReasonZh(bd.coverage?.reason || bd.reason, bdMonth)}）`);
        if (!poiOk) failures.push(`新云 ${bdMonth} 周边 POI 未获取（${translateReasonZh(bd.poi?.reason || bd.reason, bdMonth)}）`);
      }
    }
  }

  if (routes) {
    const rMonth = formatYm(routes.data_month || '202305') || '2023-05';
    const missList: any[] = Array.isArray(routes.missing) ? routes.missing : [];
    const req = Number(routes.summary?.requested || 0);
    const resolvedTotal = req > 0 ? Math.max(0, req - missList.length) : Number(routes.summary?.resolved || 0);
    if (resolvedTotal > 0) {
      acquired.push(`线路真实轨迹（${resolvedTotal}/${req || resolvedTotal} 条）`);
    }
    if (missList.length > 0) {
      const names = missList.map((m: any) => String(m?.line || m?.requested || '').trim()).filter(Boolean);
      const rZh = translateReasonZh(missList[0]?.reason || routes.reason, rMonth);
      const shown = names.slice(0, 6).join('、') + (names.length > 6 ? ` 等 ${names.length} 条` : '');
      failures.push(`未获取到轨迹（${names.length || missList.length} 条）：${shown || '未知线路'}（${rZh}，已按区县示意）`);
    }
  }

  if (portrait) {
    const pMonth = formatYm(portrait.data_month || '202305') || '2023-05';
    const matchedLen = Array.isArray(portrait.matched) ? portrait.matched.length : 0;
    if (matchedLen > 0) {
      acquired.push(`人群画像（${matchedLen} 条）`);
    } else if (portrait.reason && portrait.reason !== 'NO_LINES') {
      failures.push(`新云 ${pMonth} 人群画像未获取（${translateReasonZh(portrait.reason, pMonth)}）`);
    }
  }

  return { acquired, failures };
}

export function renderStatus(plan: Plan, run: Partial<ProposalRun>, source: 'api' | 'fixture', activeVariant = 'balanced') {
  const m = plan.meta || {};
  const set = (sel: string, v: string) => document.querySelectorAll<HTMLElement>(sel).forEach((el) => (el.textContent = v));
  const runId = run.run_id || getRunId() || '—';
  // 状态栏绝不再显示“降级”：方案已生成一律显示“已完成”（离线样本显示“离线演示”）
  set('[data-run-status]', source === 'fixture' ? '离线演示' : '已完成');
  set('[data-solver]', `${m.solver || 'CP-SAT'} · ${VARIANT_LABELS[activeVariant] || activeVariant}`);

  // Keep all tab links synced with activeVariant
  if (runId && runId !== '—') {
    document.querySelectorAll<HTMLAnchorElement>('[data-tab]').forEach((a) => {
      const u = new URL(a.href, location.origin);
      u.searchParams.set('run', runId);
      if (activeVariant) u.searchParams.set('variant', activeVariant);
      a.href = u.toString();
    });
  }

  // Render header variant switcher (segmented control on sub-tabs)
  const variants = (run as any)?.variants;
  const hasMultiVariants = Boolean(variants?.comparison?.length > 1);
  const pillBox = document.querySelector<HTMLElement>('[data-variant-pills]');
  if (pillBox && hasMultiVariants) {
    pillBox.hidden = false;
    pillBox.replaceChildren();
    variants.comparison.forEach((v: any) => {
      const btn = document.createElement('button');
      btn.type = 'button';
      const isAct = v.mode === activeVariant;
      btn.className = 'variant-seg__btn' + (isAct ? ' is-active' : '');
      btn.setAttribute('aria-pressed', String(isAct));
      btn.textContent = v.short || VARIANT_LABELS[v.mode] || v.mode;
      btn.title = v.tagline || '';
      btn.addEventListener('click', () => {
        if (v.mode !== activeVariant) navigateVariant(v.mode);
      });
      pillBox.append(btn);
    });
  }

  // Honest data-source period chips (explicitly stating exact time period of each dataset)
  const inv = (run.data as any)?.inventory;
  const bd = (run.data as any)?.bigdata;
  const invChip = document.querySelector<HTMLElement>('[data-src-inventory]');
  const bdChip = document.querySelector<HTMLElement>('[data-src-bigdata]');
  const invRange = deriveInventoryRange(inv, plan);
  if (invChip) {
    const invLiveOk = inv?.status === 'done' && inv?.mode === 'live';
    const invFailed = inv && inv.status !== 'done';
    const labelPrefix = source === 'fixture' ? '样本库存' : (invLiveOk ? '红豆实时库存' : '红豆本地快照');
    invChip.textContent = `${labelPrefix} · ${invRange} 档期`;
    invChip.className = 'chip mono ' + (invFailed ? 'chip--warn' : invLiveOk ? 'chip--ok' : 'chip--quiet');
    invChip.title = `红豆库存数据区间：${invRange}（${invLiveOk ? '本次任务实时拉取' : '本地可用快照'}）`;
  }
  if (bdChip) {
    const bdState = bd?.status ?? '—';
    const skipped = bdState === 'skipped' || bd?.reason === 'MANUAL_LOGIN_REQUIRED';
    const bdMonth = formatYm(bd?.data_month || '202305') || '2023-05';
    bdChip.textContent = source === 'fixture'
      ? `新云实测 · ${bdMonth} 期（样本）`
      : skipped
        ? '新云大数据 · 未登录（未拉取）'
        : `新云实测数据 · ${bdMonth} 期`;
    bdChip.className = 'chip mono ' + (skipped ? 'chip--quiet' : 'chip--accent');
    bdChip.title = skipped
      ? '新云大数据会话未登录，未能拉取周边覆盖、POI 与线路轨迹'
      : `新云传媒大数据平台统计期：${bdMonth}（周边覆盖 / POI / 线路轨迹 / 人群画像）`;
  }

  // Transparent data delivery row: always list acquired data; if any failed after retries, list exact missing line/reason
  const deliveryRow = document.querySelector<HTMLElement>('[data-delivery-row]');
  const acquiredFlag = document.querySelector<HTMLElement>('[data-acquired-flag]');
  const failureFlag = document.querySelector<HTMLElement>('[data-failure-flag]');
  const { acquired, failures } = synthesizeDataDelivery(plan, run, source);

  if (acquiredFlag) {
    if (acquired.length > 0) {
      acquiredFlag.hidden = false;
      const prefix = failures.length === 0 ? '已完整获取：' : '已获取：';
      acquiredFlag.textContent = `${prefix}${acquired.join(' · ')}`;
      acquiredFlag.title = acquired.join('\n');
    } else {
      acquiredFlag.hidden = true;
    }
  }
  if (failureFlag) {
    if (failures.length > 0) {
      failureFlag.hidden = false;
      failureFlag.textContent = failures.join('；');
      failureFlag.title = failures.join('\n');
    } else {
      failureFlag.hidden = true;
    }
  }
  if (deliveryRow) {
    deliveryRow.hidden = acquired.length === 0 && failures.length === 0;
  }

  const body = document.querySelector<HTMLElement>('[data-result-status-bar]');
  if (body) {
    body.className = 'statusbar' + (failures.length > 0 ? ' statusbar--partial' : '');
  }
}
