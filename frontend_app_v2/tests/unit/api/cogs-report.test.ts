import { describe, expect, it } from 'vitest';
import {
  buildReportsCogsPath,
  fetchCogsReport,
  readCogsReport,
  REPORTS_COGS_PATH,
  COGS_GROUP_BY_DEFAULT,
  COGS_GROUP_BY_VALUES,
  COGS_ORDER_TYPES,
} from '@/api/reports';
import { MODE } from '@/api/_adapter';
import type { ApiClient, ApiResponse } from '@/integrations/api-client';

/** H4.4 - reportCogs (GET /reports/cogs/) REAL: parsing + query + error. */

const BODY = {
  rows: [
    {
      key: '2026-10',
      label: '2026-10',
      sales_amount: 1000.5,
      cogs_amount: 400.2,
      gross_profit: 600.3,
      gross_margin_pct: 60,
      order_count: 2,
      line_count: 3,
      qty_total: 10,
      has_missing_cost: false,
      missing_cost_reason: null,
      period: '2026-10',
    },
    {
      key: 'CUST-A',
      label: 'PT Alpha',
      sales_amount: 1000,
      cogs_amount: 0,
      gross_profit: 1000,
      gross_margin_pct: 100,
      order_count: 1,
      line_count: 1,
      qty_total: 5,
      has_missing_cost: true,
      missing_cost_reason: 'no_cost',
      customer_id: 7,
      customer_code: 'CUST-A',
      customer_name: 'PT Alpha',
    },
  ],
  summary: {
    total_sales: 2000.5,
    total_cogs: 400.2,
    total_gross_profit: 1600.3,
    gross_margin_pct: 79.99,
    order_count: 3,
    line_count: 4,
    qty_total: 15,
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
    customer_id: null,
    product_id: null,
    order_type: null,
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

describe('H4.4 - reportCogs (konstanta & MODE)', () => {
  it('MODE reportCogs = real; path + pilihan group_by/order_type dari backend', () => {
    expect(MODE['reportCogs']).toBe('real');
    expect(REPORTS_COGS_PATH).toBe('/reports/cogs/');
    expect(COGS_GROUP_BY_DEFAULT).toBe('period');
    expect(COGS_GROUP_BY_VALUES).toEqual(['period', 'customer', 'product']);
    expect([...COGS_ORDER_TYPES]).toEqual(['EXPORT', 'CUSTOM', 'BRAND']);
  });
});

describe('H4.4 - buildReportsCogsPath', () => {
  it('path polos tanpa filter; `_nocache=1` & alias from/to hanya saat diminta', () => {
    expect(buildReportsCogsPath()).toBe('/reports/cogs/');
    expect(
      buildReportsCogsPath({ period: null, customerId: null, groupBy: null, nocache: false }),
    ).toBe('/reports/cogs/');
    expect(buildReportsCogsPath({ nocache: true })).toBe('/reports/cogs/?_nocache=1');
    expect(buildReportsCogsPath({ from: '2026-10-01', to: '2026-10-31' })).toBe(
      '/reports/cogs/?from=2026-10-01&to=2026-10-31',
    );
  });

  it('mengirim period/customer/product/order_type/group_by', () => {
    expect(
      buildReportsCogsPath({
        period: '2026-10',
        customerId: 7,
        productId: 9,
        orderType: 'CUSTOM',
        groupBy: 'product',
      }),
    ).toBe(
      '/reports/cogs/?period=2026-10&customer_id=7&product_id=9&order_type=CUSTOM&group_by=product',
    );
  });
});

describe('H4.4 - readCogsReport', () => {
  it('membaca rows/summary/filters/period/cached + reason COGS hilang', () => {
    const parsed = readCogsReport(BODY);

    expect(parsed?.rows).toHaveLength(2);
    expect(parsed?.rows[0]?.period).toBe('2026-10');
    expect(parsed?.rows[0]?.gross_margin_pct).toBe(60);
    expect(parsed?.rows[0]?.has_missing_cost).toBe(false);
    expect(parsed?.rows[0]?.missing_cost_reason).toBeNull();
    expect(parsed?.rows[1]?.customer_id).toBe(7);
    expect(parsed?.rows[1]?.customer_name).toBe('PT Alpha');
    expect(parsed?.rows[1]?.has_missing_cost).toBe(true);
    expect(parsed?.rows[1]?.missing_cost_reason).toBe('no_cost');
    expect(parsed?.summary.total_cogs).toBe(400.2);
    expect(parsed?.summary.rows_with_missing_cost).toBe(1);
    expect(parsed?.summary.currency).toBe('IDR');
    expect(parsed?.group_by).toBe('period');
    expect(parsed?.filters.resolved_to).toBe('2026-10-31T23:59:59.999999+07:00');
    expect(parsed?.period.from).toBe('2026-10-01T00:00:00+07:00');
    expect(parsed?.cached).toBe(false);
  });

  it('respons rusak -> null; field hilang -> default aman', () => {
    expect(readCogsReport('rusak')).toBeNull();
    expect(readCogsReport({ summary: {} })).toBeNull();

    const kosong = readCogsReport({ rows: [] });

    expect(kosong?.rows).toEqual([]);
    expect(kosong?.summary.total_sales).toBe(0);
    expect(kosong?.summary.rows_with_missing_cost).toBe(0);
    expect(kosong?.summary.currency).toBe('IDR');
    expect(kosong?.group_by).toBe('period');
    expect(kosong?.cached).toBe(false);
  });
});

describe('H4.4 - fetchCogsReport', () => {
  it('memakai path default + hasil terparse', async () => {
    const { client, paths } = stubClient(BODY);
    const report = await fetchCogsReport(client);

    expect(paths).toEqual(['/reports/cogs/']);
    expect(report.rows[0]?.gross_profit).toBe(600.3);
    expect(report.summary.total_gross_profit).toBe(1600.3);
  });

  it('meneruskan query filter ke path', async () => {
    const { client, paths } = stubClient(BODY);

    await fetchCogsReport(client, {
      period: '2026-10',
      customerId: 7,
      groupBy: 'customer',
      nocache: true,
    });

    expect(paths).toEqual([
      '/reports/cogs/?period=2026-10&customer_id=7&group_by=customer&_nocache=1',
    ]);
  });

  it('HTTP gagal -> melempar pesan backend; bentuk tak dikenal -> pesan kontrak', async () => {
    await expect(fetchCogsReport(errorClient(403, 'Forbidden'))).rejects.toThrow('Forbidden');

    const { client } = stubClient('rusak');
    await expect(fetchCogsReport(client)).rejects.toThrow(
      'Bentuk respons laporan HPP tidak dikenali.',
    );
  });
});
