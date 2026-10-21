/** Tipe toggle analytics (Sprint C.2) — docs/analytics/TOGGLE-CONTRACT.md §2–§3. */

export interface AnalyticsConfig {
  enabled: boolean;
  enabled_domains: string[];
  enabled_metrics: string[];
  data_readiness_acknowledged_at: string | null;
  enabled_by: number | null;
  enabled_at: string | null;
  disabled_reason: string;
  historical_data_available: boolean;
  updated_at: string;
}

export interface ReadinessResponse {
  ready: boolean;
  blockers: string[];
  soft_blockers: string[];
  checked_at: string;
  thresholds: Record<string, number>;
  counts: Record<string, number>;
}

export interface EnableWarning {
  code: string;
  message: string;
}

export interface EnableResponse extends AnalyticsConfig {
  readiness: ReadinessResponse;
  warnings: EnableWarning[];
}

export interface AnalyticsConfigUpdate {
  enabled_domains: string[];
  enabled_metrics: string[];
}
