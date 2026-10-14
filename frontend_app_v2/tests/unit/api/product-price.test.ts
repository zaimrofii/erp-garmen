import { describe, expect, it } from 'vitest';
import {
  buildPriceHistoryPath,
  fetchProduct,
  fetchProductPriceHistory,
  masterProductPriceHistoryPath,
  masterProductPricePath,
  readMasterProductRow,
  readPriceHistoryPage,
  readPriceHistoryRow,
  toMasterProductPriceBody,
  updateProductPrice,
} from '@/api/masterProducts';
import type { ApiClient, ApiResponse } from '@/integrations/api-client';

/**
 * H3.5 — adapter harga produk (`/api/v1/master/products/<id>/price|price-history/`).
 *
 * Bentuk = PERSIS `django_app/master/services.py::product_row` (menambah
 * `price_updated_at`) + `price_history` (metadata audit `master.update_price`:
 * `source`/`fields`/`before`/`after`), envelope §3.
 */

interface RecordedRequest {
  path: string;
  method: string;
  body?: unknown;
}

const ROW = {
  id: 3,
  code: 'KAIN-COTTON',
  name: 'Kain Cotton',
  category: 'Kain',
  uom_id: null,
  uom_code: null,
  sale_price: 50000,
  cost_price: 30000,
  price_updated_at: '2026-10-12T05:00:00+00:00',
  weight: null,
  image_url: '',
  active: true,
  odoo_id: 89,
  created_at: '2026-10-01T00:00:00+00:00',
  updated_at: null,
};

const HISTORY_ROW = {
  id: 12,
  action: 'master.update_price',
  source: 'price_endpoint',
  fields: ['sale_price', 'cost_price'],
  before: { sale_price: '50000.00', cost_price: '30000.00' },
  after: { sale_price: '61000.00', cost_price: '32000.00' },
  user: 'admin-h35',
  timestamp: '2026-10-12T05:10:00+00:00',
  request_id: 'req-1',
};

function stubClient(data: unknown): { client: ApiClient; requests: RecordedRequest[] } {
  const requests: RecordedRequest[] = [];
  const reply = <T,>(): ApiResponse<T> => ({ ok: true, status: 200, data: data as T });

  const client = {
    get: async <T,>(path: string): Promise<ApiResponse<T>> => {
      requests.push({ path, method: 'GET' });

      return reply<T>();
    },
    post: async <T,>(path: string, body: unknown, options?: unknown): Promise<ApiResponse<T>> => {
      requests.push({ path, method: 'POST', body, options });

      return reply<T>();
    },
    request: async <T,>(
      path: string,
      options?: Record<string, unknown>,
    ): Promise<ApiResponse<T>> => {
      requests.push({ path, method: String(options?.['method'] ?? 'GET'), body: options?.['body'] });

      return reply<T>();
    },
  } as unknown as ApiClient;

  return { client, requests };
}

function failingClient(status: number, message: string): ApiClient {
  const response = <T,>(): ApiResponse<T> => ({
    ok: false,
    status,
    error: { kind: 'http_error', message },
  });

  return {
    get: async <T,>() => response<T>(),
    post: async <T,>() => response<T>(),
    request: async <T,>() => response<T>(),
  } as unknown as ApiClient;
}

describe('H3.5 — path & reader PURE harga produk', () => {
  it('path harga & riwayat sesuai endpoint backend', () => {
    expect(masterProductPricePath(3)).toBe('/master/products/3/price/');
    expect(masterProductPriceHistoryPath(3)).toBe('/master/products/3/price-history/');
    expect(buildPriceHistoryPath(3)).toBe('/master/products/3/price-history/');
    expect(buildPriceHistoryPath(3, { limit: 20, cursor: 0 })).toBe(
      '/master/products/3/price-history/?limit=20&cursor=0',
    );
  });

  it('readMasterProductRow membaca price_updated_at (null aman)', () => {
    const row = readMasterProductRow(ROW);
    const tanpa = readMasterProductRow({ ...ROW, price_updated_at: null });

    expect(row?.price_updated_at).toBe('2026-10-12T05:00:00+00:00');
    expect(tanpa?.price_updated_at).toBeNull();
    expect(row?.sale_price).toBe(50000);
  });

  it('readPriceHistoryRow membaca diff (before/after/fields/source)', () => {
    const row = readPriceHistoryRow(HISTORY_ROW);

    expect(row).not.toBeNull();
    expect(row?.action).toBe('master.update_price');
    expect(row?.source).toBe('price_endpoint');
    expect(row?.fields).toEqual(['sale_price', 'cost_price']);
    expect(row?.before).toEqual({ sale_price: '50000.00', cost_price: '30000.00' });
    expect(row?.after).toEqual({ sale_price: '61000.00', cost_price: '32000.00' });
    expect(row?.user).toBe('admin-h35');
  });

  it('readPriceHistoryRow defensif: tanpa id / metadata aneh', () => {
    expect(readPriceHistoryRow({ action: 'master.update_price' })).toBeNull();
    expect(readPriceHistoryRow(null)).toBeNull();

    const aneh = readPriceHistoryRow({ id: 5, fields: 'bukan-array', before: null, after: 7 });
    expect(aneh?.fields).toEqual([]);
    expect(aneh?.before).toEqual({});
    expect(aneh?.after).toEqual({});
  });

  it('readPriceHistoryPage membaca envelope §3', () => {
    const page = readPriceHistoryPage({
      rows: [HISTORY_ROW],
      total_count: 1,
      has_more: false,
      next_cursor: null,
    });

    expect(page?.total_count).toBe(1);
    expect(page?.has_more).toBe(false);
    expect(page?.rows[0]?.id).toBe(12);

    expect(readPriceHistoryPage({ rows: 'bukan-array' })).toBeNull();
  });

  it('toMasterProductPriceBody hanya mengirim field yang diberikan', () => {
    expect(toMasterProductPriceBody({ sale_price: 1000 })).toEqual({ sale_price: 1000 });
    expect(toMasterProductPriceBody({ cost_price: 0 })).toEqual({ cost_price: 0 });
    expect(toMasterProductPriceBody({ sale_price: 1, cost_price: 2 })).toEqual({
      sale_price: 1,
      cost_price: 2,
    });
    expect(toMasterProductPriceBody({})).toEqual({});
  });

  it('updateProductPrice memakai PUT ke endpoint harga', async () => {
    const { client, requests } = stubClient(ROW);

    const saved = await updateProductPrice(client, 3, { sale_price: 61000 });

    expect(requests[0]?.path).toBe('/master/products/3/price/');
    expect(requests[0]?.method).toBe('PUT');
    expect(requests[0]?.body).toEqual({ sale_price: 61000 });
    expect(saved.sale_price).toBe(50000);
  });

  it('fetchProductPriceHistory memakai GET + limit/cursor', async () => {
    const { client, requests } = stubClient({
      rows: [HISTORY_ROW],
      total_count: 1,
      has_more: false,
      next_cursor: null,
    });

    const page = await fetchProductPriceHistory(client, 3, { limit: 20, cursor: 20 });

    expect(requests[0]?.path).toBe('/master/products/3/price-history/?limit=20&cursor=20');
    expect(requests[0]?.method).toBe('GET');
    expect(page.rows[0]?.source).toBe('price_endpoint');
  });

  it('fetchProduct tidak berubah (H1.1 tetap jalan) & error diteruskan', async () => {
    const { client, requests } = stubClient(ROW);

    const product = await fetchProduct(client, 3);

    expect(requests[0]?.path).toBe('/master/products/3/');
    expect(product.price_updated_at).toBe('2026-10-12T05:00:00+00:00');

    const gagal = failingClient(400, 'Field \'sale_price\' tidak boleh negatif.');
    await expect(updateProductPrice(gagal, 3, { sale_price: -1 })).rejects.toThrow(/negatif/);
  });
});
