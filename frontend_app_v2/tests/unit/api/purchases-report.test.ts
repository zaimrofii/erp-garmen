import { describe, expect, it } from 'vitest';
import {
  buildReportsPurchasesPath,
  fetchPurchasesReport,
  readPurchasesReport,
  REPORTS_PURCHASES_PATH,
  PURCHASES_GROUP_BY_DEFAULT,
  PURCHASES_GROUP_BY_VALUES,
  PURCHASES_STATUS_VALUES,
} from '@/api/reports';
import { MODE } from '@/api/_adapter';
import type { ApiClient, ApiResponse } from '@/integrations/api-client';

/** H4.2 - reportPurchases (GET /reports/purchases/) REAL: parsing + query + error. */

const BODY = {
  rows: [
    {
      key: '2026-10',
      label: '2026-10',
      unit: 'IDR',
      value: 1000.5,
      total_qty: 10.5,
      total_amount: 1000.5,
      purchase_count: 2,
      line_count: 3,
      period: '2026-10',
    },
    {
      key: 'SUP-A',
      label: 'PT Alpha',
      unit: 'IDR',
      value: 400,
      total_qty: 4,
      total_amount: 400,
      purchase_count: 1,
      line_count: 1,
      vendor_id: 7,
      vendor_code: 'SUP-A',
      vendor_name: 'PT Alpha',
    },
  ],
  summary: {
    total_qty: 14.5,
    total_amount: 1400.5,
    count_purchases: 3,
    count_lines: 4,
    billed_amount: 1000,
    bill_count: 1,
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
    vendor_id: null,
    product_id: null,
    status: null,
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

describe('H4.2 - reportPurchases (konstanta & MODE)', () => {
  it('MODE reportPurchases = real; path + pilihan group_by/status dari backend', () => {
    expect(MODE['reportPurchases']).toBe('real');
    expect(REPORTS_PURCHASES_PATH).toBe('/reports/purchases/');
    expect(PURCHASES_GROUP_BY_DEFAULT).toBe('period');
    expect(PURCHASES_GROUP_BY_VALUES).toEqual(['period', 'vendor', 'product']);
    expect([...PURCHASES_STATUS_VALUES]).toEqual(['DRAFT', 'CONFIRMED', 'DONE', 'CANCELLED']);
  });
});

describe('H4.2 - buildReportsPurchasesPath', () => {
  it('path polos tanpa filter; _nocache=1 & alias from/to hanya saat diminta', () => {
    expect(buildReportsPurchasesPath()).toBe('/reports/purchases/');
    expect(
      buildReportsPurchasesPath({ period: null, vendorId: null, groupBy: null, nocache: false }),
    ).toBe('/reports/purchases/');
    expect(buildReportsPurchasesPath({ nocache: true })).toBe('/reports/purchases/?_nocache=1');
    expect(buildReportsPurchasesPath({ from: '2026-10-01', to: '2026-10-31' })).toBe(
      '/reports/purchases/?from=2026-10-01&to=2026-10-31',
    );
  });

  it('mengirim period/vendor/product/status/group_by', () => {
    expect(
      buildReportsPurchasesPath({
        period: '2026-10',
        vendorId: 7,
        productId: 9,
        status: 'CONFIRMED',
        groupBy: 'product',
      }),
    ).toBe(
      '/reports/purchases/?period=2026-10&vendor_id=7&product_id=9&status=CONFIRMED&group_by=product',
    );
  });
});

describe('H4.2 - readPurchasesReport', () => {
  it('membaca rows/summary/filters/period/cached', () => {
    const parsed = readPurchasesReport(BODY);

    expect(parsed?.rows).toHaveLength(2);
    expect(parsed?.rows[0]?.period).toBe('2026-10');
    expect(parsed?.rows[0]?.total_qty).toBe(10.5);
    expect(parsed?.rows[1]?.vendor_id).toBe(7);
    expect(parsed?.rows[1]?.vendor_name).toBe('PT Alpha');
    expect(parsed?.rows[1]?.vendor_code).toBe('SUP-A');
    expect(parsed?.summary.billed_amount).toBe(1000);
    expect(parsed?.summary.paid_amount).toBe(500);
    expect(parsed?.summary.count_purchases).toBe(3);
    expect(parsed?.summary.currency).toBe('IDR');
    expect(parsed?.group_by).toBe('period');
    expect(parsed?.filters.status).toBeNull();
    expect(parsed?.filters.resolved_to).toBe('2026-10-31T23:59:59.999999+07:00');
    expect(parsed?.period.from).toBe('2026-10-01T00:00:00+07:00');
    expect(parsed?.cached).toBe(false);
  });

  it('respons rusak -> null; field hilang -> default aman', () => {
    expect(readPurchasesReport('rusak')).toBeNull();
    expect(readPurchasesReport({ summary: {} })).toBeNull();

    const kosong = readPurchasesReport({ rows: [] });

    expect(kosong?.rows).toEqual([]);
    expect(kosong?.summary.total_amount).toBe(0);
    expect(kosong?.summary.currency).toBe('IDR');
    expect(kosong?.group_by).toBe('period');
    expect(kosong?.filters.nocache).toBe(false);
    expect(kosong?.cached).toBe(false);
  });
});

describe('H4.2 - fetchPurchasesReport', () => {
  it('memakai path default + hasil terparse', async () => {
    const { client, paths } = stubClient(BODY);
    const report = await fetchPurchasesReport(client);

    expect(paths).toEqual(['/reports/purchases/']);
    expect(report.rows[0]?.total_amount).toBe(1000.5);
    expect(report.summary.count_purchases).toBe(3);
  });

  it('meneruskan query filter ke path', async () => {
    const { client, paths } = stubClient(BODY);

    await fetchPurchasesReport(client, {
      period: '2026-10',
      vendorId: 7,
      groupBy: 'vendor',
      nocache: true,
    });

    expect(paths).toEqual([
      '/reports/purchases/?period=2026-10&vendor_id=7&group_by=vendor&_nocache=1',
    ]);
  });

  it('HTTP gagal -> melempar pesan backend; bentuk tak dikenal -> pesan kontrak', async () => {
    await expect(fetchPurchasesReport(errorClient(403, 'Forbidden'))).rejects.toThrow('Forbidden');

    const { client } = stubClient('rusak');
    await expect(fetchPurchasesReport(client)).rejects.toThrow(
      'Bentuk respons laporan pembelian tidak dikenali.',
    );
  });
});
