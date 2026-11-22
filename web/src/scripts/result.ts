// Result pages: read `?run=` and load one shared plan. Four tabs reuse the same run id;
// no result page re-solves — numbers come only from the run payload.
// Fallback: ?run=demo or a network/service failure loads the frozen lego-500 fixture (static demo only).

import type { Plan, ProposalRun } from '../lib/plan';

export type RenderFn = (plan: Plan, run: Partial<ProposalRun>) => void;

export function getRunId(): string | null {
  const p = new URLSearchParams(location.search);
  return p.get('run');
}

export function isDemo(): boolean {
  return getRunId() === 'demo';
}

function fixtureUrl(runId: string | null): string {
  // Only lego-500 exists as a complete fixture; everything else fails back to it.
  return '/data/fixtures/plan-lego-500.json';
}

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json() as Promise<T>;
}

/** Load the plan for the current ?run=. Resolves null on no-run/404 (caller shows empty state). */
export async function loadRun(): Promise<{ plan: Plan; run: Partial<ProposalRun>; source: 'api' | 'fixture' } | null> {
  const runId = getRunId();
  if (!runId) return null;

  if (runId === 'demo') {
    const plan = await fetchJson<Plan>(fixtureUrl(runId)).catch(() => null);
    if (!plan) return null;
    return { plan, run: { run_id: 'demo', status: 'degraded' }, source: 'fixture' };
  }

  let run: ProposalRun;
  try {
    const res = await fetch(`/api/proposals/${encodeURIComponent(runId)}`);
    if (!res.ok) return null; // real run id that 404s -> empty state, never a wrong fixture
    run = await res.json();
  } catch {
    return null; // endpoint unreachable -> empty state (handoff: 无服务时结果页显示清晰空态)
  }

  if (run.status === 'done' || run.status === 'degraded') {
    return run.plan ? { plan: run.plan, run, source: 'api' } : null;
  }
  // queued / running / needs_input / failed -> no plan to render on a result page.
  return null;
}

/** Update the footer data version/timestamp from the loaded plan. */
export function setFooterData(plan: Plan) {
  const m = plan.meta || {};
  const set = (sel: string, v: string) => {
    const el = document.querySelector(sel);
    if (el) el.textContent = v;
  };
  // footer inputs are plain <span class="mono"> — match by position via data attrs if present
  document.querySelectorAll<HTMLElement>('[data-meta-version]').forEach((el) => (el.textContent = m.data_version || '—'));
  document.querySelectorAll<HTMLElement>('[data-meta-ts]').forEach((el) => (el.textContent = String(m.inventory_ts || '—').replace('T', ' ').slice(0, 16)));
}

/** Show the empty state and hide the content root (no run / not found). */
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

/** Show a simple status bar (queued/running/failed) and hide content. */
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
  const { plan, run, source } = loaded;
  content.hidden = false;
  setFooterData(plan);

  // status bar header
  renderStatus(plan, run, source);
  render(plan, run);
}

export function renderStatus(plan: Plan, run: Partial<ProposalRun>, source: 'api' | 'fixture') {
  const m = plan.meta || {};
  const set = (sel: string, v: string) => document.querySelectorAll<HTMLElement>(sel).forEach((el) => (el.textContent = v));
  set('[data-run-id]', run.run_id || '—');
  set('[data-run-status]', source === 'fixture' ? '降级（离线演示）' : (run.status === 'degraded' ? '降级' : '完成'));
  set('[data-solver]', m.solver || '—');
  set('[data-data-version]', m.data_version || '—');
  set('[data-inventory-ts]', String(m.inventory_ts || '—').replace('T', ' ').slice(0, 16));

  // Data-source status (红豆 inventory + 新云/xinyun supplement), straight from run.data.
  // Degraded/skipped must be shown as "补充数据不可用" and must NOT block the plan.
  const inv = (run.data as any)?.inventory;
  const bd = (run.data as any)?.bigdata;
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
    const skipped = bdState === 'skipped' || bdState === 'degraded';
    bdChip.textContent = `新云补充 · ${skipped ? '不可用' : bd?.data_month ? String(bd.data_month).slice(0, 7) : bdState}`;
    bdChip.className = 'chip mono ' + (skipped ? 'chip--quiet' : 'chip--accent');
    if (bd?.reason) bdChip.title = bd.reason; // e.g. MANUAL_LOGIN_REQUIRED
  }

  const degradedFlag = document.querySelector<HTMLElement>('[data-degraded-flag]');
  const isDegraded = source === 'fixture' || run.status === 'degraded';
  if (degradedFlag) degradedFlag.hidden = !isDegraded;
  const body = document.querySelector<HTMLElement>('[data-result-status-bar]');
  if (body) {
    body.className = 'statusbar' + (isDegraded ? ' statusbar--warn' : '');
  }
}
