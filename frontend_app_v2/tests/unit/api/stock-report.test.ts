import { describe, expect, it } from 'vitest';
import {
  buildReportsStockPath,
  fetchStockReport,
  readStockReport,
  REPORTS_STOCK_PATH,
  STOCK_GROUP_BY_DEFAULT,
  STOCK_GROUP_BY_VALUES,
} from '@/api/reports';
import { MODE } from '@/api/_adapter';
import type { ApiClient, ApiResponse } from '@/integrations/api-client';

/** H4.3 - reportStock (GET /reports/stock/) REAL: parsing + query + error. */

const BODY = {
  rows: [
    {
      key: 'KAIN',
      label: 'Kain',
      unit: 'unit',
      product_id: 3,
      product_code: 'KAIN',
      product_name: 'Kain',
      uom_code: 'PCS',
      total_qty: 40.5,
      reserved_qty: 5,
      available_qty: 35.5,
      locations_count: 2,
    },
    {
      key: 'WH/STOK',
      label: 'Stok Utama',
      unit: 'unit',
      location_id: 8,
      location_code: 'WH/STOK',
      location_name: 'Stok Utama',
      location_odoo_id: 8,
      total_qty: 30.3,
      reserved_qty: 5.1,
      available_qty: 25.2,
      products_count: 3,
    },
  ],
  summary: {
    total_qty: 40.5,
    reserved_qty: 5.1,
    available_qty: 35.4,
    product_count: 3,
    location_count: 2,
    quant_count: 4,
    unmapped_product_count: 1,
    unmapped_qty: 7,
  },
  group_by: 'product',
  filters: {
    group_by: 'product',
    location_id: null,
    product_id: null,
    search: null,
    only_nonzero: false,
    nocache: false,
    source: 'odoo',
  },
  generated_at: '2026-10-13T07:00:00+07:00',
  cached: false,
  source: 'odoo',
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

describe('H4.3 - reportStock (konstanta & MODE)', () => {
  it('MODE reportStock = real; path + pilihan group_by dari backend', () => {
    expect(MODE['reportStock']).toBe('real');
    expect(REPORTS_STOCK_PATH).toBe('/reports/stock/');
    expect(STOCK_GROUP_BY_DEFAULT).toBe('product');
    expect(STOCK_GROUP_BY_VALUES).toEqual(['product', 'location']);
  });
});

describe('H4.3 - buildReportsStockPath', () => {
  it('path polos tanpa filter (snapshot TANPA param rentang)', () => {
    expect(buildReportsStockPath()).toBe('/reports/stock/');
    expect(
      buildReportsStockPath({ locationId: null, productId: null, search: null, groupBy: null }),
    ).toBe('/reports/stock/');
    expect(buildReportsStockPath({ nocache: true })).toBe('/reports/stock/?_nocache=1');
    expect(buildReportsStockPath({ onlyNonzero: false })).toBe('/reports/stock/');
  });

  it('mengirim location/product/search/group_by/only_nonzero', () => {
    expect(
      buildReportsStockPath({
        locationId: 8,
        productId: 3,
        search: 'kain',
        groupBy: 'location',
        onlyNonzero: true,
      }),
    ).toBe(
      '/reports/stock/?location_id=8&product_id=3&search=kain&group_by=location&only_nonzero=1',
    );
  });
});

describe('H4.3 - readStockReport', () => {
  it('membaca rows/summary/filters/source/cached', () => {
    const parsed = readStockReport(BODY);

    expect(parsed?.rows).toHaveLength(2);
    expect(parsed?.rows[0]?.product_id).toBe(3);
    expect(parsed?.rows[0]?.uom_code).toBe('PCS');
    expect(parsed?.rows[0]?.locations_count).toBe(2);
    expect(parsed?.rows[1]?.location_id).toBe(8);
    expect(parsed?.rows[1]?.products_count).toBe(3);
    expect(parsed?.summary.unmapped_product_count).toBe(1);
    expect(parsed?.summary.unmapped_qty).toBe(7);
    expect(parsed?.summary).not.toHaveProperty('currency');
    expect(parsed?.group_by).toBe('product');
    expect(parsed?.filters.source).toBe('odoo');
    expect(parsed?.filters.only_nonzero).toBe(false);
    expect(parsed?.source).toBe('odoo');
    expect(parsed?.cached).toBe(false);
  });

  it('respons rusak -> null; field hilang -> default aman', () => {
    expect(readStockReport('rusak')).toBeNull();
    expect(readStockReport({ summary: {} })).toBeNull();

    const kosong = readStockReport({ rows: [] });

    expect(kosong?.rows).toEqual([]);
    expect(kosong?.summary.total_qty).toBe(0);
    expect(kosong?.group_by).toBe('product');
    expect(kosong?.filters.source).toBe('odoo');
    expect(kosong?.source).toBe('odoo');
    expect(kosong?.cached).toBe(false);
  });
});

describe('H4.3 - fetchStockReport', () => {
  it('memakai path default + hasil terparse', async () => {
    const { client, paths } = stubClient(BODY);
    const report = await fetchStockReport(client);

    expect(paths).toEqual(['/reports/stock/']);
    expect(report.rows[0]?.available_qty).toBe(35.5);
    expect(report.summary.location_count).toBe(2);
  });

  it('meneruskan query filter ke path', async () => {
    const { client, paths } = stubClient(BODY);

    await fetchStockReport(client, {
      locationId: 8,
      groupBy: 'location',
      onlyNonzero: true,
      nocache: true,
    });

    expect(paths).toEqual([
      '/reports/stock/?location_id=8&group_by=location&only_nonzero=1&_nocache=1',
    ]);
  });

  it('HTTP gagal -> melempar pesan backend; bentuk tak dikenal -> pesan kontrak', async () => {
    await expect(fetchStockReport(errorClient(403, 'Forbidden'))).rejects.toThrow('Forbidden');

    const { client } = stubClient('rusak');
    await expect(fetchStockReport(client)).rejects.toThrow(
      'Bentuk respons laporan stok tidak dikenali.',
    );
  });
});
