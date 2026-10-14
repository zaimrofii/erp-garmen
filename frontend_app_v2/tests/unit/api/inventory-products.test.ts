import { describe, expect, it } from 'vitest';
import {
  buildInventoryProductsPath,
  fetchProducts,
  INVENTORY_PRODUCTS_PATH,
  readProductPage,
  readProductRow,
} from '@/api/inventory';
import { MODE } from '@/api/_adapter';
import type { ApiClient, ApiResponse } from '@/integrations/api-client';

/**
 * F2c.1 — adapter REAL produk inventory (`GET /api/v1/inventory/products/`, B7).
 * Bentuk = PERSIS `monitoring.InventoryProductsView`: envelope
 * `{rows, total_count, has_more, next_cursor}`; baris `{id, code, name, odoo_id, stock_qty}`.
 * Field `type`/`uom` sudah dibuang (tidak ada di backend).
 */

const LIVE_BODY = {
  rows: [
    { id: 1, code: 'TS-001', name: 'Kaos Polos', odoo_id: 101, stock_qty: 150 },
    { id: 2, code: 'TS-002', name: 'Kaos Polos L', odoo_id: null, stock_qty: 0 },
  ],
  total_count: 2,
  has_more: false,
  next_cursor: null,
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

describe('F2c.1 — MODE & path inventory products', () => {
  it('MODE inventoryProducts = real (endpoint B7 ADA)', () => {
    expect(MODE['inventoryProducts']).toBe('real');
  });

  it('path default + query q/limit/cursor', async () => {
    expect(INVENTORY_PRODUCTS_PATH).toBe('/inventory/products/');
    expect(buildInventoryProductsPath()).toBe('/inventory/products/');
    expect(buildInventoryProductsPath({ q: 'kaos' })).toBe('/inventory/products/?q=kaos');
    expect(buildInventoryProductsPath({ limit: 20, cursor: 40 })).toBe(
      '/inventory/products/?limit=20&cursor=40',
    );
    expect(buildInventoryProductsPath({ q: '   ' })).toBe('/inventory/products/');

    const { client, paths } = stubClient(LIVE_BODY);

    await fetchProducts(client, { q: 'kaos' });

    expect(paths).toEqual(['/inventory/products/?q=kaos']);
  });
});

describe('F2c.1 — readProductPage', () => {
  it('respons backend → daftar ProductRow', async () => {
    const { client } = stubClient(LIVE_BODY);

    const rows = await fetchProducts(client);

    expect(rows).toHaveLength(2);
    expect(rows[0]).toEqual({ id: 1, code: 'TS-001', name: 'Kaos Polos', odoo_id: 101, stock_qty: 150 });
    expect(rows[1]?.odoo_id).toBeNull();
    expect(rows[1]?.stock_qty).toBe(0);
  });

  it('baris tanpa id dibuang; envelope has_more diterima', () => {
    const page = readProductPage({
      rows: [{ id: 3, code: 'X' }, { code: 'rusak' }, 'x'],
      total_count: 9,
      has_more: true,
      next_cursor: 2,
    });

    expect(page?.rows).toHaveLength(1);
    expect(page?.has_more).toBe(true);
    expect(page?.next_cursor).toBe(2);
    expect(readProductRow({ id: '5' })).toBeNull();
  });

  it('envelope tak dikenal → null', () => {
    expect(readProductPage(null)).toBeNull();
    expect(readProductPage({ rows: 'bukan-array' })).toBeNull();
  });
});

describe('F2c.1 — error inventory products', () => {
  it('403 (perlu session) → melempar pesan', async () => {
    const client = {
      get: async <T,>(): Promise<ApiResponse<T>> => ({
        ok: false,
        status: 403,
        error: { kind: 'http_error', message: 'HTTP 403' },
      }),
    } as unknown as ApiClient;

    await expect(fetchProducts(client)).rejects.toThrow(/403/);
  });

  it('bentuk respons tak dikenali → melempar pesan jelas', async () => {
    const { client } = stubClient({ ok: true });

    await expect(fetchProducts(client)).rejects.toThrow(/tidak dikenali/);
  });
});
