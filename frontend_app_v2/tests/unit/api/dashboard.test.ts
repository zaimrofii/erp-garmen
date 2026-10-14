import { describe, expect, it } from 'vitest';
import { DASHBOARD_SUMMARY_PATH, fetchDashboardSummary, readDashboardSummary } from '@/api/dashboard';
import { MODE } from '@/api/_adapter';
import type { ApiClient, ApiResponse } from '@/integrations/api-client';

/** F2C.2 — dashboard REAL (`GET /api/v1/dashboard/summary/`, B1 + G1). */

const LIVE_BODY = {
  bundles: { draft: 1, cutting: 2, sewing: 3, qc: 4, done: 5 },
  wip_qty: 15,
  fg_qty: 5,
  orders: { open: 3, overdue: 1 },
  scrap_qty_today: 2,
  alerts: [{ code: 'WC-02', message: 'Antrean panjang', severity: 'warning' }],
  line_efficiency: { pct: 87.5, delta: 1.5 },
  trend: [
    { date: '2026-10-01', wip: 12, fg: 3 },
    { date: '2026-10-02', wip: 15, fg: 5 },
  ],
  generated_at: '2026-10-02T10:00:00Z',
};

function stubClient(data: unknown): { client: ApiClient; paths: string[] } {
  const paths: string[] = [];
  const client = {
    get: async <T,>(path: string): Promise<ApiResponse<T>> => {
      paths.push(path);
      return { ok: true, status: 200, data: data as T };
    },
  } as unknown as ApiClient;

  return { client, paths };
}

describe('F2C.2 — dashboard', () => {
  it('MODE dashboard = real; path tetap', () => {
    expect(MODE['dashboard']).toBe('real');
    expect(DASHBOARD_SUMMARY_PATH).toBe('/dashboard/summary/');
  });

  it('readDashboardSummary menjaga nested shape (line_efficiency/trend/alerts)', () => {
    const parsed = readDashboardSummary(LIVE_BODY);

    expect(parsed?.wip_qty).toBe(15);
    expect(parsed?.bundles.done).toBe(5);
    expect(parsed?.orders.overdue).toBe(1);
    expect(parsed?.line_efficiency.pct).toBe(87.5);
    expect(parsed?.line_efficiency.delta).toBe(1.5);
    expect(parsed?.trend).toHaveLength(2);
    expect(parsed?.trend[1]?.fg).toBe(5);
    expect(parsed?.alerts[0]?.code).toBe('WC-02');
  });

  it('respons rusak → null; fetch melempar', async () => {
    expect(readDashboardSummary('bukan-objek')).toBeNull();
    expect(readDashboardSummary(null)).toBeNull();

    const { client, paths } = stubClient('rusak');

    await expect(fetchDashboardSummary(client)).rejects.toThrow(
      'Bentuk respons ringkasan dashboard tidak dikenali.',
    );
    expect(paths).toEqual(['/dashboard/summary/']);
  });
});
