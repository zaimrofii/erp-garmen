import { describe, expect, it } from 'vitest';
import {
  buildMasterProductsPath,
  createProduct,
  deleteProduct,
  fetchProduct,
  fetchProducts,
  MASTER_PRODUCTS_PATH,
  readMasterProductPage,
  readMasterProductRow,
  readMasterProductSaved,
  toMasterProductBody,
  updateProduct,
} from '@/api/masterProducts';
import { MODE } from '@/api/_adapter';
import type { ApiClient, ApiResponse } from '@/integrations/api-client';
import type { MasterProductInput, MasterProductRow } from '@/types/master-product';

/**
 * H1.1 — adapter master produk (`/api/v1/master/products/`).
 *
 * Bentuk = PERSIS `django_app/master/services.py::product_row`:
 * `{id, code, name, category, uom_id, uom_code, sale_price, cost_price, weight,
 *  image_url, active, odoo_id, created_at, updated_at}` + `{sync_record_id, task_id,
 *  queued}` pada POST/PUT. `active` = nama publik `Product.is_active`.
 */

const ROW: MasterProductRow = {
  id: 7,
  code: 'TS-001',
  name: 'Kaos Polos',
  category: 'Atasan',
  uom_id: 3,
  uom_code: 'PCS',
  sale_price: 15000.5,
  cost_price: 9000,
  weight: 0.25,
  image_url: 'https://cdn.klien.com/kaos.png',
  active: true,
  odoo_id: null,
  // H3.5 — field aditif `price_updated_at` (null = harga belum pernah diubah).
  price_updated_at: null,
  created_at: '2026-10-10T10:00:00+07:00',
  updated_at: '2026-10-10T10:00:00+07:00',
};

const LIVE_BODY = {
  rows: [ROW, { ...ROW, id: 8, code: 'TS-002', active: false, odoo_id: 101 }],
  total_count: 2,
  has_more: false,
  next_cursor: null,
};

const SAVED_BODY = { ...ROW, sync_record_id: 42, task_id: 'task-master-1', queued: true };

const INPUT: MasterProductInput = {
  code: ' TS-003 ',
  name: ' Kaos Baru ',
  category: ' Atasan ',
  uom_id: 3,
  sale_price: 12000,
  cost_price: 8000,
  weight: null,
  image_url: ' https://cdn.klien.com/baru.png ',
  active: true,
};

interface RecordedRequest {
  path: string;
  method: string;
  body?: unknown;
}

interface Stub {
  client: ApiClient;
  requests: RecordedRequest[];
}

function stubClient(data: unknown): Stub {
  const requests: RecordedRequest[] = [];
  const reply = <T,>(): ApiResponse<T> => ({ ok: true, status: 200, data: data as T });

  const client = {
    get: async <T,>(path: string): Promise<ApiResponse<T>> => {
      requests.push({ path, method: 'GET' });

      return reply<T>();
    },
    post: async <T,>(path: string, body: unknown): Promise<ApiResponse<T>> => {
      requests.push({ path, method: 'POST', body });

      return reply<T>();
    },
    request: async <T,>(
      path: string,
      options?: { method?: 'GET' | 'POST' | 'PUT' | 'DELETE'; body?: unknown },
    ): Promise<ApiResponse<T>> => {
      requests.push({ path, method: options?.method ?? 'GET', body: options?.body });

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
    request: async <T,>(): Promise<ApiResponse<T>> => response<T>(),
    get: async <T,>(): Promise<ApiResponse<T>> => response<T>(),
    post: async <T,>(): Promise<ApiResponse<T>> => response<T>(),
  } as unknown as ApiClient;
}

describe('H1.1 — MODE & path master produk', () => {
  it('MODE.masterProducts = real (endpoint H1.1 ADA di backend)', () => {
    expect(MODE['masterProducts']).toBe('real');
    expect(MASTER_PRODUCTS_PATH).toBe('/master/products/');
  });

  it('buildMasterProductsPath: default tanpa query, param terisi saja yang dikirim', () => {
    expect(buildMasterProductsPath()).toBe('/master/products/');
    expect(buildMasterProductsPath({ search: 'kaos' })).toBe('/master/products/?search=kaos');
    expect(buildMasterProductsPath({ category: 'Atasan', active: true })).toBe(
      '/master/products/?category=Atasan&active=true',
    );
    expect(buildMasterProductsPath({ active: false })).toBe('/master/products/?active=false');
    expect(buildMasterProductsPath({ limit: 20, cursor: 40, active: null })).toBe(
      '/master/products/?limit=20&cursor=40',
    );
  });

  it('fetchProducts memanggil path terfilter & mengembalikan envelope ListPage', async () => {
    const { client, requests } = stubClient(LIVE_BODY);

    const page = await fetchProducts(client, { search: 'kaos', active: true, limit: 50 });

    expect(requests).toEqual([
      { path: '/master/products/?search=kaos&active=true&limit=50', method: 'GET' },
    ]);
    expect(page.rows).toHaveLength(2);
    expect(page.total_count).toBe(2);
    expect(page.has_more).toBe(false);
    expect(page.next_cursor).toBeNull();
    expect(page.rows[0]).toEqual(ROW);
    expect(page.rows[1]?.odoo_id).toBe(101);
    expect(page.rows[1]?.active).toBe(false);
  });
});

describe('H1.1 — reader baris & page', () => {
  it('readMasterProductRow: baris rusak (tanpa id angka) dibuang', () => {
    expect(readMasterProductRow({ code: 'X' })).toBeNull();
    expect(readMasterProductRow({ id: '7' })).toBeNull();
    expect(readMasterProductRow(null)).toBeNull();
    expect(readMasterProductRow({ id: 1, code: 'X', sale_price: 'gratis' })?.sale_price).toBe(0);
  });

  it('readMasterProductPage: envelope tak dikenal → null', () => {
    expect(readMasterProductPage(null)).toBeNull();
    expect(readMasterProductPage({ rows: 'bukan-array' })).toBeNull();
    expect(readMasterProductPage(LIVE_BODY)?.rows).toHaveLength(2);
  });

  it('readMasterProductSaved: menyertakan sync_record_id/task_id/queued', () => {
    expect(readMasterProductSaved(SAVED_BODY)).toEqual({
      ...ROW,
      sync_record_id: 42,
      task_id: 'task-master-1',
      queued: true,
    });
    expect(readMasterProductSaved({ id: 1, queued: 'yes' })?.queued).toBe(false);
  });

  it('toMasterProductBody: trim teks, `active` & `uom_id` apa adanya', () => {
    expect(toMasterProductBody(INPUT)).toEqual({
      code: 'TS-003',
      name: 'Kaos Baru',
      category: 'Atasan',
      uom_id: 3,
      sale_price: 12000,
      cost_price: 8000,
      weight: null,
      image_url: 'https://cdn.klien.com/baru.png',
      active: true,
    });
  });
});

describe('H1.1 — detail & tulis (POST/PUT/DELETE)', () => {
  it('fetchProduct memanggil `/master/products/<id>/` dan melempar pesan backend saat 404', async () => {
    const { client, requests } = stubClient(ROW);

    expect(await fetchProduct(client, 7)).toEqual(ROW);
    expect(requests).toEqual([{ path: '/master/products/7/', method: 'GET' }]);

    await expect(fetchProduct(failingClient(404, 'Produk 9 tidak ditemukan.'), 9)).rejects.toThrow(
      /tidak ditemukan/,
    );
  });

  it('createProduct: POST body tervalidasi + parse jawaban saved', async () => {
    const { client, requests } = stubClient(SAVED_BODY);

    const saved = await createProduct(client, INPUT);

    expect(requests).toEqual([
      { path: '/master/products/', method: 'POST', body: toMasterProductBody(INPUT) },
    ]);
    expect(saved.id).toBe(7);
    expect(saved.sync_record_id).toBe(42);
    expect(saved.task_id).toBe('task-master-1');
    expect(saved.queued).toBe(true);
  });

  it('createProduct 400 (kode duplikat) → melempar pesan backend', async () => {
    await expect(
      createProduct(failingClient(400, "Kode produk 'TS-003' sudah dipakai produk lain."), INPUT),
    ).rejects.toThrow(/sudah dipakai/);
  });

  it('updateProduct: PUT ke `/master/products/<id>/`', async () => {
    const { client, requests } = stubClient({ ...SAVED_BODY, name: 'Kaos Baru' });

    const saved = await updateProduct(client, 7, INPUT);

    expect(requests).toEqual([
      { path: '/master/products/7/', method: 'PUT', body: toMasterProductBody(INPUT) },
    ]);
    expect(saved.name).toBe('Kaos Baru');
  });

  it('deleteProduct: DELETE (soft delete di backend) & melempar saat gagal', async () => {
    const { client, requests } = stubClient({ id: 7, active: false, deleted: true });

    await deleteProduct(client, 7);
    expect(requests).toEqual([{ path: '/master/products/7/', method: 'DELETE', body: undefined }]);

    await expect(deleteProduct(failingClient(403, 'HTTP 403'), 7)).rejects.toThrow(/403/);
  });

  it('bentuk respons simpan tak dikenali → melempar pesan jelas', async () => {
    const { client } = stubClient({ ok: true });

    await expect(createProduct(client, INPUT)).rejects.toThrow(/tidak dikenali/);
  });
});

