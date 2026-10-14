import { describe, expect, it } from 'vitest';
import {
  buildLineEfficiencyPath,
  fetchLineEfficiency,
  LINE_EFFICIENCY_PATH,
  readLineEfficiencyReport,
} from '@/api/reports';
import { buildReportsWipPath, fetchWip, readWipReport, REPORTS_WIP_PATH } from '@/api/reports';
import { MODE } from '@/api/_adapter';
import type { ApiClient, ApiResponse } from '@/integrations/api-client';

/** F2C.2 — reportsLineEfficiency (B13+G4b) & reportsWIP (B16+G4) REAL. */

const EFF_BODY = {
  rows: [
    {
      wc_code: 'WC-01',
      wc_name: 'Cutting 1',
      bundles_done: 12,
      avg_min_per_bundle: 4.5,
      efficiency_pct: 88,
      label: 'Efisiensi',
      unit: '%',
      trend: [{ date: '2026-10-01', value: 85 }],
      series: [{ x: '2026-10-01', y: 85 }],
    },
  ],
  generated_at: '2026-10-02T10:00:00Z',
  period: { from: '2026-10-01', to: '2026-10-02' },
};

const WIP_BODY = {
  rows: [
    {
      wc_code: 'WC-02',
      wc_name: 'Sewing 1',
      wip_qty: 40,
      queue_depth: 3,
      label: 'WIP',
      unit: 'pcs',
      trend: [{ date: '2026-10-01', value: 38 }],
      series: [{ x: '2026-10-01', y: 38 }],
    },
  ],
  total_wip: 40,
  group_by: 'wc',
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

describe('F2C.2 — reportsLineEfficiency', () => {
  it('MODE reportsLineEfficiency = real; path + period query', async () => {
    expect(MODE['reportsLineEfficiency']).toBe('real');
    expect(LINE_EFFICIENCY_PATH).toBe('/reports/line-efficiency/');
    expect(buildLineEfficiencyPath({ from: '2026-10-01' })).toBe(
      '/reports/line-efficiency/?from=2026-10-01',
    );

    const { client, paths } = stubClient(EFF_BODY);

    await fetchLineEfficiency(client);

    expect(paths).toEqual(['/reports/line-efficiency/']);
  });

  it('label/unit/trend/series DIBACA (field tambahan G4b)', () => {
    const parsed = readLineEfficiencyReport(EFF_BODY);

    expect(parsed?.rows[0]?.label).toBe('Efisiensi');
    expect(parsed?.rows[0]?.unit).toBe('%');
    expect(parsed?.rows[0]?.trend[0]?.value).toBe(85);
    expect(parsed?.rows[0]?.series[0]?.y).toBe(85);
    expect(parsed?.period.from).toBe('2026-10-01');
  });
});

describe('F2C.2 — reportsWIP', () => {
  it('MODE reportsWIP = real; group_by=none → rows []', () => {
    expect(MODE['reportsWIP']).toBe('real');
    expect(REPORTS_WIP_PATH).toBe('/reports/wip/');
    expect(buildReportsWipPath({ groupBy: 'none' })).toBe('/reports/wip/?group_by=none');

    const parsed = readWipReport({ total_wip: 0, group_by: 'none', generated_at: 'x' });

    expect(parsed?.rows).toEqual([]);
    expect(parsed?.total_wip).toBe(0);
  });

  it('baris WC: wip_qty/queue_depth/label/unit', async () => {
    const { client, paths } = stubClient(WIP_BODY);
    const report = await fetchWip(client);

    expect(paths).toEqual(['/reports/wip/']);
    expect(report.rows[0]?.wip_qty).toBe(40);
    expect(report.rows[0]?.queue_depth).toBe(3);
    expect(report.rows[0]?.unit).toBe('pcs');
    expect(report.total_wip).toBe(40);
    expect(readWipReport('rusak')).toBeNull();
  });
});
