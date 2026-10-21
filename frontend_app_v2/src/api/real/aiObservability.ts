// REAL — observability AI (Sprint F.3.4). Endpoint: /api/v1/ai/observability/
import type { ApiClient } from '@/integrations/api-client';
import type {
  AIObservabilityDay,
  AIObservabilityParams,
  AIObservabilityQuery,
  AIObservabilityStats,
  AIObservabilityTool,
  AIObservabilityTotals,
} from '@/types/ai-observability';
import { buildQueryPath, getParsed, isRecord, readNum, readStr } from './_shape';

export const AI_OBSERVABILITY_PATH = '/ai/observability/';

function readTotals(raw: unknown): AIObservabilityTotals {
  const data = isRecord(raw) ? raw : {};
  return {
    requests: readNum(data['requests']),
    tokens_prompt: readNum(data['tokens_prompt']),
    tokens_completion: readNum(data['tokens_completion']),
    cost_usd: readNum(data['cost_usd']),
    cache_hits: readNum(data['cache_hits']),
    hitl_required: readNum(data['hitl_required']),
    hitl_approved: readNum(data['hitl_approved']),
    hitl_rejected: readNum(data['hitl_rejected']),
    latency_avg_ms: readNum(data['latency_avg_ms']),
  };
}

export function parseAIObservability(raw: unknown): AIObservabilityStats | null {
  if (!isRecord(raw)) return null;

  const byDay: AIObservabilityDay[] = Array.isArray(raw['by_day'])
    ? raw['by_day'].filter(isRecord).map((row) => ({
        date: readStr(row['date']),
        requests: readNum(row['requests']),
        cost_usd: readNum(row['cost_usd']),
        latency_avg_ms: readNum(row['latency_avg_ms']),
      }))
    : [];

  const byTool: AIObservabilityTool[] = Array.isArray(raw['by_tool'])
    ? raw['by_tool'].filter(isRecord).map((row) => ({
        tool: readStr(row['tool']),
        calls: readNum(row['calls']),
        avg_duration_ms: readNum(row['avg_duration_ms']),
      }))
    : [];

  const topQueries: AIObservabilityQuery[] = Array.isArray(raw['top_queries'])
    ? raw['top_queries'].filter(isRecord).map((row) => ({
        query_hash: readStr(row['query_hash']),
        count: readNum(row['count']),
      }))
    : [];

  const gateRaw = isRecord(raw['by_decision_gate']) ? raw['by_decision_gate'] : {};
  const byDecisionGate: Record<string, number> = {};
  for (const [key, value] of Object.entries(gateRaw)) {
    if (typeof value === 'number') byDecisionGate[key] = value;
  }

  return {
    date_from: readStr(raw['date_from']),
    date_to: readStr(raw['date_to']),
    group_by: readStr(raw['group_by']) || 'day',
    totals: readTotals(raw['totals']),
    by_day: byDay,
    by_tool: byTool,
    by_decision_gate: byDecisionGate,
    cache_hit_ratio: readNum(raw['cache_hit_ratio']),
    hitl_approval_rate: readNum(raw['hitl_approval_rate']),
    top_queries: topQueries,
    computed_at: readStr(raw['computed_at']),
    cached: raw['cached'] === true,
  };
}

export async function fetchAIObservability(
  client: ApiClient,
  params: AIObservabilityParams,
): Promise<AIObservabilityStats> {
  const path = buildQueryPath(AI_OBSERVABILITY_PATH, {
    date_from: params.dateFrom,
    date_to: params.dateTo,
    _nocache: params.nocache ? 1 : null,
  });

  return getParsed(client, path, parseAIObservability, 'observability AI');
}
