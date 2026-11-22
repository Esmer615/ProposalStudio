// Shared formatters. These are pure: no price/units math — the run payload owns every number.

export const nf = new Intl.NumberFormat('zh-CN');

export function fmtInt(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return '—';
  return nf.format(Math.round(n));
}

export function fmtWan(n: number | null | undefined, digits = 0): string {
  if (n == null || Number.isNaN(n)) return '—';
  return nf.format(Number(n.toFixed(digits)));
}

export function fmtPct(n: number | null | undefined, digits = 1): string {
  if (n == null || Number.isNaN(n)) return '—';
  return `${Number(n.toFixed(digits))}%`;
}

// A pct that may arrive as a decimal (0.82) or a string ("82.0%").
export function pctReadable(v: number | string | null | undefined, digits = 1): string {
  if (v == null) return '—';
  if (typeof v === 'string') {
    const n = parseFloat(v);
    return Number.isFinite(n) ? `${n.toFixed(digits)}%` : v;
  }
  const n = Number(v);
  if (Number.isNaN(n)) return '—';
  // 0..1 decimal -> percent; otherwise already percent-ish
  return n > 0 && n <= 1 ? `${(n * 100).toFixed(digits)}%` : `${n.toFixed(digits)}%`;
}

export function fmtMoney(n: number | null | undefined, digits = 2): string {
  if (n == null || Number.isNaN(n)) return '—';
  return `${Number(n.toFixed(digits))} 万`;
}

export function ratioPct(n: number | null | undefined, digits = 1): string {
  if (n == null || Number.isNaN(n)) return '—';
  return `${(n * 100).toFixed(digits)}%`;
}

export function shortName(name: string | null | undefined): string {
  return String(name ?? '').replace(/站 · /, ' · ');
}

// ISO timestamp -> "YYYY-MM-DD HH:mm" (assumes +08:00 strings; strips secondary TZ if present).
export function fmtTs(ts: string | null | undefined): string {
  if (!ts) return '—';
  const s = String(ts).replace(/Z$/, '').replace(/\.\d+/, '');
  if (s.length >= 16) return s.slice(0, 16).replace('T', ' ');
  return s;
}

export function fmtDate(ts: string | null | undefined): string {
  if (!ts) return '—';
  return String(ts).slice(0, 10);
}

export function fmtDateRange(start: string | null | undefined, end: string | null | undefined): string {
  if (!start && !end) return '—';
  return `${fmtDate(start)} → ${fmtDate(end)}`;
}
