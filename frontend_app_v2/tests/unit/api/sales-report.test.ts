import { describe, expect, it } from 'vitest';
import {
  buildReportsSalesPath,
  fetchSalesReport,
  readSalesReport,
  REPORTS_SALES_PATH,
  SALES_GROUP_BY_DEFAULT,
  SALES_GROUP_BY_VALUES,
  SALES_ORDER_TYPES,
} from '@/api/reports';
import { MODE } from '@/api/_adapter';
import type { ApiClient, ApiResponse } from '@/integrations/api-client';

/** H4.1 — `reportsSales` (GET /reports/sales/) REAL: parsing + query + error. */

const BODY = {
  rows: [
    {
      key: '2026-10',
      label: '2026-10',
      unit: 'IDR',
      value: 1000.5,
      total_qty: 10,
      total_amount: 1000.5,
      order_count: 2,
      line_count: 3,
      period: '2026-10',
    },
    {
      key: 'CUST-A',
      label: 'PT Alpha',
      unit: 'IDR',
      value: 400,
      total_qty: 4,
      total_amount: 400,
      order_count: 1,
      line_count: 1,
      customer_id: 7,
      customer_code: 'CUST-A',
      customer_name: 'PT Alpha',
    },
  ],
  summary: {
    total_qty: 14,
    total_amount: 1400.5,
    count_orders: 3,
    count_lines: 4,
    invoiced_amount: 1000,
    invoice_count: 1,
    paid_amount: 500,
    payment_count: 2,
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

describe('H4.1 — reportsSales (konstanta & MODE)', () => {
  it('MODE reportSales = real; path + pilihan group_by/order_type dari backend', () => {
    expect(MODE['reportSales']).toBe('real');
    expect(REPORTS_SALES_PATH).toBe('/reports/sales/');
    expect(SALES_GROUP_BY_DEFAULT).toBe('period');
    expect(SALES_GROUP_BY_VALUES).toEqual(['period', 'customer', 'product']);
    expect([...SALES_ORDER_TYPES]).toEqual(['EXPORT', 'CUSTOM', 'BRAND']);
  });
});

describe('H4.1 — buildReportsSalesPath', () => {
  it('path polos tanpa filter; `_nocache=1` & alias from/to hanya saat diminta', () => {
    expect(buildReportsSalesPath()).toBe('/reports/sales/');
    expect(
      buildReportsSalesPath({ period: null, customerId: null, groupBy: null, nocache: false }),
    ).toBe('/reports/sales/');
    expect(buildReportsSalesPath({ nocache: true })).toBe('/reports/sales/?_nocache=1');
    expect(buildReportsSalesPath({ from: '2026-10-01', to: '2026-10-31' })).toBe(
      '/reports/sales/?from=2026-10-01&to=2026-10-31',
    );
  });

  it('mengirim period/customer/product/order_type/group_by', () => {
    expect(
      buildReportsSalesPath({
        period: '2026-10',
        customerId: 7,
        productId: 9,
        orderType: 'CUSTOM',
        groupBy: 'product',
      }),
    ).toBe(
      '/reports/sales/?period=2026-10&customer_id=7&product_id=9&order_type=CUSTOM&group_by=product',
    );
  });
});

describe('H4.1 — readSalesReport', () => {
  it('membaca rows/summary/filters/period/cached', () => {
    const parsed = readSalesReport(BODY);

    expect(parsed?.rows).toHaveLength(2);
    expect(parsed?.rows[0]?.period).toBe('2026-10');
    expect(parsed?.rows[1]?.customer_id).toBe(7);
    expect(parsed?.rows[1]?.customer_name).toBe('PT Alpha');
    expect(parsed?.rows[1]?.customer_code).toBe('CUST-A');
    expect(parsed?.summary.invoiced_amount).toBe(1000);
    expect(parsed?.summary.paid_amount).toBe(500);
    expect(parsed?.summary.currency).toBe('IDR');
    expect(parsed?.group_by).toBe('period');
    expect(parsed?.filters.period).toBe('2026-10');
    expect(parsed?.filters.resolved_to).toBe('2026-10-31T23:59:59.999999+07:00');
    expect(parsed?.period.from).toBe('2026-10-01T00:00:00+07:00');
    expect(parsed?.cached).toBe(false);
  });

  it('respons rusak → null; field hilang → default aman', () => {
    expect(readSalesReport('rusak')).toBeNull();
    expect(readSalesReport({ summary: {} })).toBeNull();

    const kosong = readSalesReport({ rows: [] });

    expect(kosong?.rows).toEqual([]);
    expect(kosong?.summary.total_amount).toBe(0);
    expect(kosong?.summary.currency).toBe('IDR');
    expect(kosong?.group_by).toBe('period');
    expect(kosong?.filters.nocache).toBe(false);
    expect(kosong?.cached).toBe(false);
  });
});

describe('H4.1 — fetchSalesReport', () => {
  it('memakai path default + hasil terparse', async () => {
    const { client, paths } = stubClient(BODY);
    const report = await fetchSalesReport(client);

    expect(paths).toEqual(['/reports/sales/']);
    expect(report.rows[0]?.total_amount).toBe(1000.5);
    expect(report.summary.count_orders).toBe(3);
  });

  it('meneruskan query filter ke path', async () => {
    const { client, paths } = stubClient(BODY);

    await fetchSalesReport(client, {
      period: '2026-10',
      customerId: 7,
      groupBy: 'customer',
      nocache: true,
    });

    expect(paths).toEqual([
      '/reports/sales/?period=2026-10&customer_id=7&group_by=customer&_nocache=1',
    ]);
  });

  it('HTTP gagal → melempar pesan backend; bentuk tak dikenal → pesan kontrak', async () => {
    await expect(fetchSalesReport(errorClient(403, 'Forbidden'))).rejects.toThrow('Forbidden');

    const { client } = stubClient('rusak');
    await expect(fetchSalesReport(client)).rejects.toThrow(
      'Bentuk respons laporan penjualan tidak dikenali.',
    );
  });
});
