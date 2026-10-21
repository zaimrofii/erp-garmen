/** Tipe analytics (Sprint C.1) — kontrak docs/analytics/CONTRACT.md §2–§3. */

export type AnalyticsGroupBy = 'period' | 'work_center' | 'line';

export interface AnalyticsFilters {
  echo: Record<string, unknown>;
  resolved_from: string | null;
  resolved_to: string | null;
}

export interface AnalyticsPeriod {
  from: string | null;
  to: string | null;
}

/** Satu baris metrik (domain listing atau rows metrik). */
export interface AnalyticsMetricRow {
  key: string;
  label: string;
  unit: string;
  value: number | null;
  numerator?: number;
  denominator?: number;
  p50?: number | null;
  p90?: number | null;
  n_bundles?: number;
  incomplete_pairs?: number;
}

export interface AnalyticsMetricMetadata {
  metric_id: string;
  label: string;
  unit: string;
  granularity: string;
  source_models: string[];
  formula_version: string;
  null_policy: string;
}

/** Response saat analytics AKTIF (shape §2). */
export interface AnalyticsResponse {
  rows: AnalyticsMetricRow[];
  summary: Record<string, unknown>;
  group_by: AnalyticsGroupBy | null;
  filters: AnalyticsFilters;
  period: AnalyticsPeriod;
  generated_at: string;
  cached: boolean;
  enabled: true;
  disabled_reason: null;
  historical_data_available: boolean;
}

/** Response saat analytics OFF (shape §2.2) — HTTP 200, bukan 503. */
export interface DisabledAnalyticsResponse {
  rows: [];
  summary: Record<string, never>;
  group_by: null;
  filters: AnalyticsFilters;
  period: AnalyticsPeriod;
  generated_at: string;
  cached: boolean;
  enabled: false;
  disabled_reason: string;
  historical_data_available: boolean;
}

export type AnalyticsResult = AnalyticsResponse | DisabledAnalyticsResponse;

export interface AnalyticsHealth {
  ok: boolean;
  enabled: boolean;
  disabled_reason: string | null;
  registry: { metrics_registered: number; metrics_active: number };
  listeners: { subscribed: number };
  stream: { connected: boolean | null; backend: string };
  storage: {
    snapshots_total: number;
    last_snapshot_at: string | null;
    historical_data_available: boolean;
  };
  toggle: { checked_at: string; source: string };
  generated_at: string;
}
