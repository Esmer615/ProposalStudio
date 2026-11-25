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

export function renderStatus(plan: Plan, run: Partial<ProposalRun>, source: 'api' | 'fixture', activeVariant = 'balanced') {
  const m = plan.meta || {};
  const set = (sel: string, v: string) => document.querySelectorAll<HTMLElement>(sel).forEach((el) => (el.textContent = v));
  const runId = run.run_id || getRunId() || '—';
  set('[data-run-id]', runId);
  set('[data-run-status]', source === 'fixture' ? '降级（离线演示）' : (run.status === 'degraded' ? '降级' : '完成'));
  set('[data-solver]', `${m.solver || 'CP-SAT'} · ${VARIANT_LABELS[activeVariant] || activeVariant}`);
  set('[data-data-version]', m.data_version || '—');
  set('[data-inventory-ts]', String(m.inventory_ts || '—').replace('T', ' ').slice(0, 16));

  // Keep all tab links + header PDF links synced with activeVariant
  if (runId && runId !== '—') {
    document.querySelectorAll<HTMLAnchorElement>('[data-tab]').forEach((a) => {
      const u = new URL(a.href, location.origin);
      u.searchParams.set('run', runId);
      if (activeVariant) u.searchParams.set('variant', activeVariant);
      a.href = u.toString();
    });
    document.querySelectorAll<HTMLAnchorElement>('[data-hdr-doc]').forEach((a) => {
      const key = a.dataset.hdrDoc || '';
      if (key) a.href = buildPdfUrl(runId, key, activeVariant);
    });
  }

  // Render header variant switcher pills when run has multiple strategy plans
  const variants = (run as any)?.variants;
  const pillBox = document.querySelector<HTMLElement>('[data-variant-pills]');
  if (pillBox && variants?.comparison?.length > 1) {
    pillBox.hidden = false;
    pillBox.replaceChildren();
    variants.comparison.forEach((v: any) => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'variant-pill' + (v.mode === activeVariant ? ' is-active' : '');
      btn.textContent = v.short || VARIANT_LABELS[v.mode] || v.mode;
      btn.title = v.tagline || '';
      btn.addEventListener('click', () => {
        if (v.mode !== activeVariant) navigateVariant(v.mode);
      });
      pillBox.append(btn);
    });
  }

  // Data-source status chips
  const inv = (run.data as any)?.inventory;
  const bd = (run.data as any)?.bigdata;
  const portrait = (run.data as any)?.portrait;
  const invChip = document.querySelector<HTMLElement>('[data-src-inventory]');
  const bdChip = document.querySelector<HTMLElement>('[data-src-bigdata]');
  if (invChip) {
    const invState = inv?.status ?? '—';
    const invMonth = inv?.months && inv.months.length ? String(inv.months[0]).slice(0, 7) : '';
    invChip.textContent = `红豆快照 · ${invMonth || invState}`;
    invChip.className = 'chip mono ' + (invState === 'degraded' || invState === 'down' ? 'chip--warn' : 'chip--quiet');
  }
  if (bdChip) {
    const bdState = bd?.status ?? '—';
    const skipped = bdState === 'skipped';
    const hasPortrait = portrait?.status === 'ready';
    bdChip.textContent = skipped
      ? '新云大数据 · 未登录'
      : `新云实测 · ${bd?.data_month ? String(bd.data_month).slice(0, 7) : '2023-05'}${hasPortrait ? ' +画像' : ''}`;
    bdChip.className = 'chip mono ' + (skipped ? 'chip--quiet' : 'chip--accent');
    if (bd?.reason) bdChip.title = bd.reason;
  }

  const degradedFlag = document.querySelector<HTMLElement>('[data-degraded-flag]');
  const isDegraded = source === 'fixture' || run.status === 'degraded';
  if (degradedFlag) degradedFlag.hidden = !isDegraded;
  const body = document.querySelector<HTMLElement>('[data-result-status-bar]');
  if (body) {
    body.className = 'statusbar' + (isDegraded ? ' statusbar--warn' : '');
  }
}
