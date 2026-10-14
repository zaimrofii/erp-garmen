import { describe, expect, it } from 'vitest';
import {
  buildReportsPnlPath,
  fetchPnlReport,
  readPnlReport,
  readStrList,
  REPORTS_PNL_PATH,
  PNL_GROUP_BY_DEFAULT,
  PNL_GROUP_BY_VALUES,
} from '@/api/reports';
import { MODE } from '@/api/_adapter';
import type { ApiClient, ApiResponse } from '@/integrations/api-client';

/** H4.5 - reportPnl (GET /reports/pnl/) REAL: parsing + query + error. */

const BODY = {
  rows: [
    {
      key: '2026-10',
      label: '2026-10',
      revenue: 1000.5,
      cogs: 400.2,
      gross_profit: 600.3,
      gross_margin_pct: 60,
      opex: 150.5,
      net_profit: 449.8,
      net_margin_pct: 44.96,
      order_count: 2,
      line_count: 3,
      has_missing_cost: false,
      missing_cost_reason: null,
      period: '2026-10',
    },
    {
      key: '2026-Q4',
      label: '2026-Q4',
      revenue: 2000,
      cogs: 800,
      gross_profit: 1200,
      gross_margin_pct: 60,
      opex: null,
      net_profit: 1200,
      net_margin_pct: 60,
      order_count: 1,
      line_count: 1,
      has_missing_cost: true,
      missing_cost_reason: 'no_product',
      quarter: '2026-Q4',
    },
  ],
  summary: {
    revenue: 3000.5,
    cogs: 1200.2,
    gross_profit: 1800.3,
    gross_margin_pct: 60,
    opex: 150.5,
    net_profit: 1649.8,
    net_margin_pct: 54.98,
    opex_source: 'journal_entry',
    opex_account_types: ['expense', 'expense_depreciation', 'expense_direct_cost'],
    opex_states: ['CONFIRMED', 'SENT', 'DONE'],
    order_count: 3,
    line_count: 4,
    rows_with_missing_cost: 1,
    currency: 'IDR',
  },
  group_by: 'period',
  filters: {
    period: '2026-10',
    date_from: null,
    date_to: null,
    from: null,
    to: null,
    group_by: 'period',
    nocache: false,
    resolved_from: '2026-10-01T00:00:00+07:00',
    resolved_to: '2026-10-31T23:59:59.999999+07:00',
  },
  period: { from: '2026-10-01T00:00:00+07:00', to: '2026-10-31T23:59:59.999999+07:00' },
  generated_at: '2026-10-13T07:00:00+07:00',
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

describe('H4.5 - reportPnl (konstanta & MODE)', () => {
  it('MODE reportPnl = real; path + pilihan group_by dari backend', () => {
    expect(MODE['reportPnl']).toBe('real');
    expect(REPORTS_PNL_PATH).toBe('/reports/pnl/');
    expect(PNL_GROUP_BY_DEFAULT).toBe('period');
    expect(PNL_GROUP_BY_VALUES).toEqual(['period', 'quarter']);
  });
});

describe('H4.5 - buildReportsPnlPath', () => {
  it('path polos tanpa filter; `_nocache=1` & alias from/to hanya saat diminta', () => {
    expect(buildReportsPnlPath()).toBe('/reports/pnl/');
    expect(buildReportsPnlPath({ period: null, groupBy: null, nocache: false })).toBe(
      '/reports/pnl/',
    );
    expect(buildReportsPnlPath({ nocache: true })).toBe('/reports/pnl/?_nocache=1');
    expect(buildReportsPnlPath({ from: '2026-10-01', to: '2026-10-31' })).toBe(
      '/reports/pnl/?from=2026-10-01&to=2026-10-31',
    );
  });

  it('mengirim period + group_by', () => {
    expect(buildReportsPnlPath({ period: '2026-10', groupBy: 'quarter' })).toBe(
      '/reports/pnl/?period=2026-10&group_by=quarter',
    );
  });
});

describe('H4.5 - readPnlReport', () => {
  it('membaca rows/summary/filters/period/cached + opex nullable + metadata opex', () => {
    const parsed = readPnlReport(BODY);

    expect(parsed?.rows).toHaveLength(2);
    expect(parsed?.rows[0]?.period).toBe('2026-10');
    expect(parsed?.rows[0]?.opex).toBe(150.5);
    expect(parsed?.rows[0]?.net_profit).toBe(449.8);
    expect(parsed?.rows[1]?.quarter).toBe('2026-Q4');
    expect(parsed?.rows[1]?.opex).toBeNull();
    expect(parsed?.rows[1]?.missing_cost_reason).toBe('no_product');
    expect(parsed?.summary.opex_source).toBe('journal_entry');
    expect(parsed?.summary.opex_account_types).toEqual([
      'expense',
      'expense_depreciation',
      'expense_direct_cost',
    ]);
    expect(parsed?.summary.opex_states).toEqual(['CONFIRMED', 'SENT', 'DONE']);
    expect(parsed?.summary.net_profit).toBe(1649.8);
    expect(parsed?.summary.currency).toBe('IDR');
    expect(parsed?.group_by).toBe('period');
    expect(parsed?.filters.resolved_to).toBe('2026-10-31T23:59:59.999999+07:00');
    expect(parsed?.cached).toBe(false);
  });

  it('respons rusak -> null; field hilang -> default aman (opex null)', () => {
    expect(readPnlReport('rusak')).toBeNull();
    expect(readPnlReport({ summary: {} })).toBeNull();

    const kosong = readPnlReport({ rows: [] });

    expect(kosong?.rows).toEqual([]);
    expect(kosong?.summary.revenue).toBe(0);
    expect(kosong?.summary.opex).toBeNull();
    expect(kosong?.summary.opex_source).toBe('unavailable');
    expect(kosong?.summary.opex_account_types).toEqual([]);
    expect(kosong?.summary.currency).toBe('IDR');
    expect(kosong?.group_by).toBe('period');
    expect(kosong?.cached).toBe(false);
  });
});

describe('H4.5 - readStrList', () => {
  it('hanya string yang lolos; bukan array -> []', () => {
    expect(readStrList(['a', 1, null, 'b'])).toEqual(['a', 'b']);
    expect(readStrList('bukan array')).toEqual([]);
    expect(readStrList(undefined)).toEqual([]);
  });
});

describe('H4.5 - fetchPnlReport', () => {
  it('memakai path default + hasil terparse', async () => {
    const { client, paths } = stubClient(BODY);
    const report = await fetchPnlReport(client);

    expect(paths).toEqual(['/reports/pnl/']);
    expect(report.rows[0]?.gross_profit).toBe(600.3);
    expect(report.summary.net_margin_pct).toBe(54.98);
  });

  it('meneruskan query filter ke path', async () => {
    const { client, paths } = stubClient(BODY);

    await fetchPnlReport(client, { period: '2026-10', groupBy: 'quarter', nocache: true });

    expect(paths).toEqual(['/reports/pnl/?period=2026-10&group_by=quarter&_nocache=1']);
  });

  it('HTTP gagal -> melempar pesan backend; bentuk tak dikenal -> pesan kontrak', async () => {
    await expect(fetchPnlReport(errorClient(403, 'Forbidden'))).rejects.toThrow('Forbidden');

    const { client } = stubClient('rusak');
    await expect(fetchPnlReport(client)).rejects.toThrow(
      'Bentuk respons laporan laba-rugi tidak dikenali.',
    );
  });
});
