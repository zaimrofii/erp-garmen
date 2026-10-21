import { describe, expect, it } from 'vitest';
import {
  fetchAnalyticsHealth,
  fetchAnalyticsMetric,
  fetchAnalyticsMetrics,
} from '@/api/analytics';
import { MODE } from '@/api/_adapter';
import type { ApiClient } from '@/integrations/api-client';

/** Sprint C.1 — adapter analytics REAL: parsing shape CONTRACT §2–§3. */

const BODY_ENABLED = {
  rows: [
    { key: 'garment.scrap_rate', label: 'Scrap Rate', unit: '%', value: 3.42 },
    { key: 'garment.lead_time', label: 'Lead Time', unit: 'jam', value: null },
  ],
  summary: { metric_count: 2 },
  group_by: 'period',
  filters: { echo: { period: '2026-10' }, resolved_from: '2026-10-01T00:00:00+07:00', resolved_to: '2026-10-31T23:59:59+07:00' },
  period: { from: '2026-10-01T00:00:00+07:00', to: '2026-10-31T23:59:59+07:00' },
  generated_at: '2026-10-18T05:10:00+07:00',
  cached: false,
  enabled: true,
  disabled_reason: null,
  historical_data_available: true,
};

const BODY_DISABLED = {
  rows: [],
  summary: {},
  group_by: null,
  filters: { echo: {}, resolved_from: null, resolved_to: null },
  period: { from: null, to: null },
  generated_at: '2026-10-18T05:12:00+07:00',
  cached: false,
  enabled: false,
  disabled_reason: 'analytics_disabled',
  historical_data_available: true,
};

const BODY_METRIC = {
  ...BODY_ENABLED,
  rows: [
    { key: '2026-10-10', label: '2026-10-10', value: 10.0, numerator: 1, denominator: 10 },
  ],
  summary: {
    metadata: {
      metric_id: 'garment.scrap_rate',
      label: 'Scrap Rate',
      unit: '%',
      granularity: 'day',
      source_models: ['garment.ScrapAccumulator', 'garment.BundleEvent'],
      formula_version: '1.0',
      null_policy: 'denominator_zero_returns_null',
    },
    value: 10.0,
  },
};

const BODY_HEALTH = {
  ok: true,
  enabled: false,
  disabled_reason: 'analytics_disabled',
  registry: { metrics_registered: 3, metrics_active: 3 },
  listeners: { subscribed: 4 },
  stream: { connected: null, backend: 'redis' },
  storage: { snapshots_total: 1280, last_snapshot_at: null, historical_data_available: true },
  toggle: { checked_at: '2026-10-18T05:12:00+07:00', source: 'service_layer' },
  generated_at: '2026-10-18T05:12:00+07:00',
};

function clientReturning(body: unknown, paths: string[] = []): ApiClient {
  return {
    get: async (path: string) => {
      paths.push(path);
      return { ok: true, status: 200, data: body };
    },
  } as unknown as ApiClient;
}

describe('analytics adapter (C.1)', () => {
  it('fetchAnalyticsMetrics parse enabled=true', async () => {
    const result = await fetchAnalyticsMetrics(clientReturning(BODY_ENABLED), 'garment');

    expect(result.enabled).toBe(true);
    if (result.enabled) {
      expect(result.rows).toHaveLength(2);
      expect(result.rows[1]?.value).toBeNull();
      expect(result.group_by).toBe('period');
      expect(result.historical_data_available).toBe(true);
    }
  });

  it('fetchAnalyticsMetrics parse enabled=false (DisabledAnalyticsResponse)', async () => {
    const result = await fetchAnalyticsMetrics(clientReturning(BODY_DISABLED), 'garment');

    expect(result.enabled).toBe(false);
    expect(result.disabled_reason).toBe('analytics_disabled');
    expect(result.rows).toEqual([]);
    expect(result.group_by).toBeNull();
  });

  it('fetchAnalyticsMetric parse metadata + rows', async () => {
    const result = await fetchAnalyticsMetric(clientReturning(BODY_METRIC), 'garment.scrap_rate');

    expect(result.enabled).toBe(true);
    const metadata = result.summary['metadata'] as Record<string, unknown>;
    expect(metadata['formula_version']).toBe('1.0');
    expect(result.rows[0]?.numerator).toBe(1);
    expect(result.rows[0]?.denominator).toBe(10);
  });

  it('fetchAnalyticsHealth parse shape §3.3', async () => {
    const health = await fetchAnalyticsHealth(clientReturning(BODY_HEALTH));

    expect(health.registry.metrics_registered).toBe(3);
    expect(health.listeners.subscribed).toBe(4);
    expect(health.stream.connected).toBeNull();
    expect(health.storage.historical_data_available).toBe(true);
  });

  it('metrics mengirim query params (period/group_by/granularity/wc/line/_nocache)', async () => {
    const paths: string[] = [];
    await fetchAnalyticsMetrics(clientReturning(BODY_ENABLED, paths), 'garment', {
      period: '2026-10',
      groupBy: 'work_center',
      granularity: 'day',
      workCenterId: 12,
      lineId: 5,
      nocache: true,
    });

    expect(paths[0]).toBe(
      '/analytics/metrics/garment/?period=2026-10&group_by=work_center&granularity=day&work_center_id=12&line_id=5&_nocache=1',
    );
  });

  it('metric meng-encode metric_id + nocache', async () => {
    const paths: string[] = [];
    await fetchAnalyticsMetric(clientReturning(BODY_METRIC, paths), 'garment.scrap_rate', {
      nocache: true,
    });

    expect(paths[0]).toBe('/analytics/metric/garment.scrap_rate/?_nocache=1');
  });

  it('bentuk respons rusak → throw', async () => {
    await expect(
      fetchAnalyticsMetrics(clientReturning({ rows: 'bukan-array' }), 'garment'),
    ).rejects.toThrow('tidak dikenali');
  });

  it('MODE analytics = real', () => {
    expect(MODE['analyticsMetrics']).toBe('real');
    expect(MODE['analyticsMetric']).toBe('real');
    expect(MODE['analyticsHealth']).toBe('real');
  });
});
