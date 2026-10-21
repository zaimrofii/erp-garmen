// Tipe observability AI (Sprint F.3) — kontrak dashboard ADMIN/OWNER.

export interface AIObservabilityTotals {
  requests: number;
  tokens_prompt: number;
  tokens_completion: number;
  cost_usd: number;
  cache_hits: number;
  hitl_required: number;
  hitl_approved: number;
  hitl_rejected: number;
  latency_avg_ms: number;
}

export interface AIObservabilityDay {
  date: string;
  requests: number;
  cost_usd: number;
  latency_avg_ms: number;
}

export interface AIObservabilityTool {
  tool: string;
  calls: number;
  avg_duration_ms: number;
}

export interface AIObservabilityQuery {
  query_hash: string;
  count: number;
}

export interface AIObservabilityStats {
  date_from: string;
  date_to: string;
  group_by: string;
  totals: AIObservabilityTotals;
  by_day: AIObservabilityDay[];
  by_tool: AIObservabilityTool[];
  by_decision_gate: Record<string, number>;
  cache_hit_ratio: number;
  hitl_approval_rate: number;
  top_queries: AIObservabilityQuery[];
  computed_at: string;
  cached: boolean;
}

export interface AIObservabilityParams {
  dateFrom: string;
  dateTo: string;
  nocache?: boolean;
}
