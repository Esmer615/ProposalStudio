// Type + selector helpers for a proposal run payload. Pure selectors; no price/unit math.

export type PlanItem = {
  id: string;
  kind: 'bus' | 'metro';
  name: string;
  line?: string | null;
  company?: string | null;
  station?: string | null;
  exit?: string | null;
  district?: string | null;
  level?: string | null;
  media_type?: string | null;
  units?: number;
  free_count?: number;
  unit_price_wan?: number;
  months?: number;
  gross_wan?: number;
  discount?: number;
  net_wan?: number;
  production_wan?: number;
  agency_fee_wan?: number;
  total_wan?: number;
  gift?: boolean;
  score?: number;
  score_breakdown?: Record<string, number>;
  reasons?: string[];
  evidence?: { type: string; text: string; source: string }[];
  alternatives?: { id: string; name: string; reason: string }[];
  geo?: {
    type?: string;
    coords?: { lng: number; lat: number };
    path?: unknown;
    district?: string;
    confidence?: string;
  };
  poi_hits?: { id: string; name: string; type: string; weight?: number; distance_m?: number; lng?: number; lat?: number; district?: string; source?: string; confidence?: string }[];
  poi_count?: number;
  hypothesis_refs?: string[];
  locked?: boolean;
  status?: string;
};

export type Plan = {
  meta: Record<string, any>;
  inputs: Record<string, any>;
  hypothesis?: { fields: { id: string; label: string; value: string }[]; one_liner?: string; assumptions?: string[] };
  strategy?: Record<string, any>;
  venue?: Record<string, any>;
  plan?: {
    bus: PlanItem[];
    metro: PlanItem[];
    summary?: Record<string, any>;
  };
  effects?: Record<string, any>;
  elasticity?: { unit?: string; points?: any[]; knee_budget_wan?: number | null; note?: string };
  quote?: Record<string, any>;
  schedule?: Record<string, any>;
  coverage?: Record<string, any>;
  validation?: Record<string, any>;
  explanations?: Record<string, any>;
  workflow?: Record<string, any>;
};

// The shape served by GET /api/proposals/{id}.
export type ProposalRun = {
  run_id: string;
  status: 'queued' | 'running' | 'needs_input' | 'done' | 'degraded' | 'failed';
  created_at?: string;
  inputs?: Record<string, any>;
  brief?: any;
  agent?: Record<string, any>;
  data?: Record<string, any>;
  plan?: Plan;
  stages?: any[];
  warnings?: any[];
  error?: Record<string, any>;
};

export function planItems(plan: Plan | null | undefined): PlanItem[] {
  if (!plan?.plan) return [];
  return [...(plan.plan.metro ?? []), ...(plan.plan.bus ?? [])];
}

export function metroItems(plan: Plan | null | undefined): PlanItem[] {
  return plan?.plan?.metro ?? [];
}

export function busItems(plan: Plan | null | undefined): PlanItem[] {
  return plan?.plan?.bus ?? [];
}

export function selectedMetro(plan: Plan | null | undefined): PlanItem[] {
  return (plan?.plan?.metro ?? []).filter((m) => m.geo?.coords?.lng != null && m.geo?.coords?.lat != null);
}

export function totalUnits(plan: Plan | null | undefined): number {
  const s = plan?.plan?.summary;
  return (s?.bus_units ?? 0) + (s?.metro_units ?? 0);
}

export const VENUES = [
  { id: 'lego_shanghai', label: '乐高', full: '上海乐高乐园度假区' },
  { id: 'disney_shanghai', label: '迪士尼', full: '上海迪士尼度假区' },
  { id: 'haichang_shanghai', label: '海昌', full: '上海海昌海洋公园' },
] as const;

export function venueLabel(id: string | null | undefined): string {
  return VENUES.find((v) => v.id === id)?.full ?? (id ?? '—');
}

export function customerLabel(id: string | null | undefined): string {
  return id === '4a' ? '4A 代理' : id === 'direct' ? '直客' : (id ?? '—');
}
