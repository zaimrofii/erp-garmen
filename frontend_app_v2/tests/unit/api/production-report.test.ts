import { describe, expect, it } from 'vitest';
import {
  buildReportsProductionPath,
  fetchProductionReport,
  readProductionReport,
  readStrRecord,
  REPORTS_PRODUCTION_PATH,
  PRODUCTION_GROUP_BY_DEFAULT,
  PRODUCTION_GROUP_BY_VALUES,
} from '@/api/reports';
import { MODE } from '@/api/_adapter';
import type { ApiClient, ApiResponse } from '@/integrations/api-client';

/** H4.6 - reportProduction (GET /reports/production/) REAL: parsing + query + error. */

const BODY = {
  rows: [
    {
      key: '2026-10',
      label: '2026-10',
      output_pcs: 120,
      scrap_pcs: 6,
      scrap_pct: 4.76,
      efficiency_pct: 12.5,
      otd_pct: 80,
      period: '2026-10',
      rework_pcs: 3,
      end_loss_pcs: 1,
      bundle_count: 4,
      wo_count: 2,
    },
    {
      key: 'WC-CUT',
      label: 'Cutting',
      output_pcs: 70,
      scrap_pcs: 4,
      scrap_pct: 5.41,
      efficiency_pct: 9.5,
      otd_pct: null,
      wc_id: 11,
      wc_code: 'WC-CUT',
      wc_name: 'Cutting',
      bundle_count: 2,
    },
  ],
  summary: {
    total_output_pcs: 190,
    total_scrap_pcs: 10,
    total_rework_pcs: 3,
    total_end_loss_pcs: 1,
    scrap_pct: 5,
    avg_efficiency_pct: 11.2,
    otd_pct: 80,
    total_bundles: 6,
    total_work_orders: 3,
  },
  group_by: 'period',
  filters: {
    period: '2026-10',
    date_from: null,
    date_to: null,
    from: null,
    to: null,
    group_by: 'period',
    work_center_id: null,
    line_id: null,
    nocache: false,
    basis: { output: 'bundle_event.ts', scrap: 'scrap_accumulator.created_at' },
    resolved_from: '2026-10-01T00:00:00+07:00',
    resolved_to: '2026-10-31T23:59:59.999999+07:00',
  },
  period: { from: '2026-10-01T00:00:00+07:00', to: '2026-10-31T23:59:59.999999+07:00' },
  generated_at: '2026-10-14T07:00:00+07:00',
  cached: false,
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

function errorClient(status: number, message: string): ApiClient {
  return {
    get: async <T,>(): Promise<ApiResponse<T>> => ({
      ok: false,
      status,
      error: { kind: 'http', message },
    }),
  } as unknown as ApiClient;
}

describe('H4.6 - reportProduction (konstanta & MODE)', () => {
  it('MODE reportProduction = real; path + pilihan group_by dari backend', () => {
    expect(MODE['reportProduction']).toBe('real');
    expect(REPORTS_PRODUCTION_PATH).toBe('/reports/production/');
    expect(PRODUCTION_GROUP_BY_DEFAULT).toBe('period');
    expect(PRODUCTION_GROUP_BY_VALUES).toEqual(['period', 'work_center', 'line']);
  });
});

describe('H4.6 - buildReportsProductionPath', () => {
  it('path polos tanpa filter; `_nocache=1` & alias from/to hanya saat diminta', () => {
    expect(buildReportsProductionPath()).toBe('/reports/production/');
    expect(
      buildReportsProductionPath({ period: null, groupBy: null, workCenterId: null, nocache: false }),
    ).toBe('/reports/production/');
    expect(buildReportsProductionPath({ nocache: true })).toBe('/reports/production/?_nocache=1');
    expect(buildReportsProductionPath({ from: '2026-10-01', to: '2026-10-31' })).toBe(
      '/reports/production/?from=2026-10-01&to=2026-10-31',
    );
  });

  it('mengirim period/group_by/work_center/line', () => {
    expect(
      buildReportsProductionPath({
        period: '2026-10',
        groupBy: 'work_center',
        workCenterId: 11,
        lineId: 5,
      }),
    ).toBe(
      '/reports/production/?period=2026-10&work_center_id=11&line_id=5&group_by=work_center',
    );
  });
});

describe('H4.6 - readProductionReport', () => {
  it('membaca rows/summary/filters/basis/period/cached + otd nullable', () => {
    const parsed = readProductionReport(BODY);

    expect(parsed?.rows).toHaveLength(2);
    expect(parsed?.rows[0]?.period).toBe('2026-10');
    expect(parsed?.rows[0]?.rework_pcs).toBe(3);
    expect(parsed?.rows[0]?.bundle_count).toBe(4);
    expect(parsed?.rows[0]?.wo_count).toBe(2);
    expect(parsed?.rows[0]?.otd_pct).toBe(80);
    expect(parsed?.rows[1]?.wc_code).toBe('WC-CUT');
    expect(parsed?.rows[1]?.otd_pct).toBeNull();
    expect(parsed?.summary.total_output_pcs).toBe(190);
    expect(parsed?.summary.total_rework_pcs).toBe(3);
    expect(parsed?.summary.total_end_loss_pcs).toBe(1);
    expect(parsed?.summary.avg_efficiency_pct).toBe(11.2);
    expect(parsed?.summary).not.toHaveProperty('currency');
    expect(parsed?.filters.basis.output).toBe('bundle_event.ts');
    expect(parsed?.filters.basis.scrap).toBe('scrap_accumulator.created_at');
    expect(parsed?.group_by).toBe('period');
    expect(parsed?.cached).toBe(false);
  });

  it('respons rusak -> null; field hilang -> default aman', () => {
    expect(readProductionReport('rusak')).toBeNull();
    expect(readProductionReport({ summary: {} })).toBeNull();

    const kosong = readProductionReport({ rows: [] });

    expect(kosong?.rows).toEqual([]);
    expect(kosong?.summary.total_output_pcs).toBe(0);
    expect(kosong?.summary.otd_pct).toBe(0);
    expect(kosong?.filters.basis).toEqual({});
    expect(kosong?.group_by).toBe('period');
    expect(kosong?.cached).toBe(false);
  });
});

describe('H4.6 - readStrRecord', () => {
  it('hanya nilai string yang lolos; bukan record -> {}', () => {
    expect(readStrRecord({ a: 'x', b: 1, c: null })).toEqual({ a: 'x' });
    expect(readStrRecord('bukan record')).toEqual({});
    expect(readStrRecord(undefined)).toEqual({});
  });
});

describe('H4.6 - fetchProductionReport', () => {
  it('memakai path default + hasil terparse', async () => {
    const { client, paths } = stubClient(BODY);
    const report = await fetchProductionReport(client);

    expect(paths).toEqual(['/reports/production/']);
    expect(report.rows[0]?.output_pcs).toBe(120);
    expect(report.summary.total_scrap_pcs).toBe(10);
  });

  it('meneruskan query filter ke path', async () => {
    const { client, paths } = stubClient(BODY);

    await fetchProductionReport(client, {
      period: '2026-10',
      groupBy: 'line',
      lineId: 5,
      nocache: true,
    });

    expect(paths).toEqual([
      '/reports/production/?period=2026-10&line_id=5&group_by=line&_nocache=1',
    ]);
  });

  it('HTTP gagal -> melempar pesan backend; bentuk tak dikenal -> pesan kontrak', async () => {
    await expect(fetchProductionReport(errorClient(403, 'Forbidden'))).rejects.toThrow(
      'Forbidden',
    );

    const { client } = stubClient('rusak');
    await expect(fetchProductionReport(client)).rejects.toThrow(
      'Bentuk respons laporan produksi tidak dikenali.',
    );
  });
});
