import { describe, expect, it, vi } from 'vitest';
import {
  getProductAudit,
  PRODUCT_AUDIT_PATH,
  readAuditProduct,
  readAuditProductGroup,
  readProductAudit,
} from '@/api/audit';
import { MODE } from '@/api/_adapter';
import { createApiClient, type ApiClient, type ApiResponse } from '@/integrations/api-client';

/**
 * F9/9.0 — adapter audit BARU: `GET /audit/products-missing-odoo-id/` (§6.1).
 *
 * Bentuk respons di bawah = PERSIS backend (`ProductAuditView.get` → `ProductAuditService.audit`):
 * `{count, products[], used_in_open_bundles: {count, limit, products[]}}`.
 * docs §6.1 (`{missing[], used_in_open_bundles: [{product_code, bundle_count}], count}`) USANG.
 */

const LIVE_BODY = {
  count: 2,
  products: [
    { id: 1, code: 'TS-DEMO-001', name: 'Kaos Demo' },
    { id: 2, code: 'KAIN-30S', name: 'Kain 30S' },
  ],
  used_in_open_bundles: {
    count: 1,
    limit: 100,
    products: [{ id: 1, code: 'TS-DEMO-001', name: 'Kaos Demo' }],
  },
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

describe('F9 — MODE & path audit', () => {
  it('MODE audit = real (endpoint §6.1 ADA)', () => {
    expect(MODE['audit']).toBe('real');
  });

  it('path relatif terhadap VITE_API_BASE_URL', async () => {
    expect(PRODUCT_AUDIT_PATH).toBe('/audit/products-missing-odoo-id/');

    const { client, paths } = stubClient(LIVE_BODY);

    await getProductAudit(client);

    expect(paths).toEqual(['/audit/products-missing-odoo-id/']);
  });
});

describe('F9 — readProductAudit', () => {
  it('respons backend → ProductAudit (products + used_in_open_bundles.count)', async () => {
    const { client } = stubClient(LIVE_BODY);

    const audit = await getProductAudit(client);

    expect(audit.count).toBe(2);
    expect(audit.products.map((product) => product.code)).toEqual(['TS-DEMO-001', 'KAIN-30S']);
    expect(audit.used_in_open_bundles.count).toBe(1);
    expect(audit.used_in_open_bundles.limit).toBe(100);
    expect(audit.used_in_open_bundles.products[0]?.id).toBe(1);
  });

  it('docs §6.1 (`missing` + array di used_in_open_bundles) tetap diterima', () => {
    const parsed = readProductAudit({
      count: 1,
      missing: [{ id: 5, code: 'X', name: 'Produk X' }],
      used_in_open_bundles: [{ product_code: 'X', bundle_count: 18 }],
    });

    expect(parsed?.count).toBe(1);
    expect(parsed?.products).toHaveLength(1);
    expect(parsed?.used_in_open_bundles.count).toBe(1);
    expect(parsed?.used_in_open_bundles.products).toEqual([]);
  });

  it('produk tanpa id angka dibuang; group tanpa products → []', () => {
    expect(readAuditProduct({ code: 'X' })).toBeNull();
    expect(readAuditProduct({ id: '1', code: 'X' })).toBeNull();
    expect(readAuditProduct(null)).toBeNull();
    expect(readAuditProductGroup(undefined)).toBeNull();

    const parsed = readProductAudit({ count: 3, products: [{ id: 1 }], used_in_open_bundles: {} });

    expect(parsed?.products).toEqual([{ id: 1, code: '', name: '' }]);
    expect(parsed?.used_in_open_bundles).toEqual({ count: 0, limit: null, products: [] });
  });

  it('envelope tak dikenal → null (tanpa daftar produk sama sekali)', () => {
    expect(readProductAudit(null)).toBeNull();
    expect(readProductAudit({ count: 0 })).toBeNull();
    expect(readProductAudit({ products: 'bukan-array' })).toBeNull();
  });
});

describe('F9 — error HTTP & jalur api-client', () => {
  it('403 (perlu session) → melempar pesan', async () => {
    const client = {
      get: async <T,>(): Promise<ApiResponse<T>> => ({
        ok: false,
        status: 403,
        error: { kind: 'http_error', message: 'HTTP 403' },
      }),
    } as unknown as ApiClient;

    await expect(getProductAudit(client)).rejects.toThrow(/403/);
  });

  it('bentuk respons tak dikenali → melempar pesan jelas', async () => {
    const client = {
      get: async <T,>(): Promise<ApiResponse<T>> => ({ ok: true, status: 200, data: [] as T }),
    } as unknown as ApiClient;

    await expect(getProductAudit(client)).rejects.toThrow(/tidak dikenali/);
  });

  it('URL penuh + credentials lewat api-client', async () => {
    const calls: { url: string; init: RequestInit }[] = [];

    vi.stubGlobal(
      'fetch',
      vi.fn((url: RequestInfo | URL, init?: RequestInit) => {
        calls.push({ url: String(url), init: init ?? {} });

        return Promise.resolve(
          new Response(JSON.stringify(LIVE_BODY), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          }),
        );
      }),
    );

    try {
      const client = createApiClient({ baseUrl: 'http://localhost:8000/api/v1' });
      await getProductAudit(client);

      expect(calls[0]?.url).toBe('http://localhost:8000/api/v1/audit/products-missing-odoo-id/');
      expect(calls[0]?.init.credentials).toBe('include');
    } finally {
      vi.unstubAllGlobals();
    }
  });
});
