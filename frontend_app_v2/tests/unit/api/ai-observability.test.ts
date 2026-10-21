import { describe, expect, it, vi } from 'vitest';
import type { ApiClient } from '@/integrations/api-client';
import { fetchAIObservability, parseAIObservability, AI_OBSERVABILITY_PATH } from '@/api/aiObservability';

/** Sprint F.3 — adapter observability AI (path + parse defensif). */

const RAW = {
  date_from: '2026-10-12T00:00:00+00:00',
  date_to: '2026-10-18T23:59:59+00:00',
  group_by: 'day',
  totals: { requests: 5, cache_hits: 2, cost_usd: 0.005, latency_avg_ms: 120 },
  by_day: [{ date: '2026-10-18', requests: 3, cost_usd: 0.003 }],
  by_tool: [{ tool: 'mcp-analytics', calls: 2, avg_duration_ms: 20 }],
  by_decision_gate: { RULE_HIT: 2, LLM_NEEDED: 3 },
  cache_hit_ratio: 0.4,
  hitl_approval_rate: 0.75,
  top_queries: [{ query_hash: 'abc', count: 2 }],
  computed_at: '2026-10-18T08:00:00+00:00',
  cached: false,
};

describe('Sprint F.3 — adapter observability', () => {
  it('parse aggregate_stats', () => {
    const stats = parseAIObservability(RAW);

    expect(stats?.totals.requests).toBe(5);
    expect(stats?.totals.cost_usd).toBe(0.005);
    expect(stats?.by_day[0]?.date).toBe('2026-10-18');
    expect(stats?.by_tool[0]?.tool).toBe('mcp-analytics');
    expect(stats?.by_decision_gate.RULE_HIT).toBe(2);
    expect(stats?.top_queries[0]?.query_hash).toBe('abc');
  });

  it('parse menolak bentuk asing', () => {
    expect(parseAIObservability(null)).toBeNull();
    expect(parseAIObservability([])).toBeNull();
  });

  it('fetch mengirim date range + _nocache', async () => {
    const get = vi.fn(async () => ({ ok: true, status: 200, data: RAW }));
    const client = { get } as unknown as ApiClient;

    await fetchAIObservability(client, {
      dateFrom: '2026-10-12',
      dateTo: '2026-10-18',
      nocache: true,
    });

    const path = get.mock.calls[0]?.[0] as string;
    expect(path.startsWith(AI_OBSERVABILITY_PATH)).toBe(true);
    expect(path).toContain('date_from=2026-10-12');
    expect(path).toContain('date_to=2026-10-18');
    expect(path).toContain('_nocache=1');
  });
});
