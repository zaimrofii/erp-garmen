import { describe, expect, it, vi } from 'vitest';
import {
  buildOrderReadinessPath,
  buildOrderRecomputePath,
  getOrderReadiness,
  ORDER_READINESS_PATH,
  postRecomputeReadiness,
  readOrderReadiness,
  readReadinessLine,
  readRecomputeResult,
  READINESS_STATUSES,
} from '@/api/readiness';
import { createApiClient, type ApiClient, type ApiResponse } from '@/integrations/api-client';

/** F2/2.9b — adapter readiness BARU: `GET /garmen/orders/{id}/readiness/` (IsAuthenticated). */

/** Bentuk PERSIS kontrak §5.4 (`integrations/erp_sync/api.py::OrderReadinessView._line_payload`). */
const LIVE_BODY = {
  order_id: 1,
  lines: [
    {
      order_line_id: 1,
      product_code: 'TS-DEMO-001',
      required_qty: 20,
      received_qty: 15,
      shortage_qty: 5,
      status: 'PARTIAL',
      expected_date: '2026-10-15',
      last_computed_at: '2026-10-08T02:00:00Z',
      vendor_bill_status: 'DRAFT',
      vendor_bill_ids: [8],
      vendor_bill_amount: 1500000,
    },
    {
      order_line_id: 2,
      product_code: null,
      required_qty: null,
      received_qty: null,
      shortage_qty: null,
      status: null,
      expected_date: null,
      last_computed_at: null,
      vendor_bill_status: null,
      vendor_bill_ids: null,
      vendor_bill_amount: null,
    },
  ],
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

describe('F2 — readiness (real) path', () => {
  it('path TETAP di `orders` (id Order, bukan OrderLine) — pengecualian F1/D7', () => {
    expect(ORDER_READINESS_PATH).toBe('/garmen/orders/');
    expect(buildOrderReadinessPath(16)).toBe('/garmen/orders/16/readiness/');
  });

  it('getOrderReadiness memakai path itu apa adanya', async () => {
    const { client, paths } = stubClient(LIVE_BODY);

    await getOrderReadiness(client, 16);

    expect(paths).toEqual(['/garmen/orders/16/readiness/']);
  });
});

describe('F2 — readiness (real) shape', () => {
  it('respons kontrak §5.4 → OrderReadiness (nilai null dipertahankan)', async () => {
    const { client } = stubClient(LIVE_BODY);

    const readiness = await getOrderReadiness(client, 1);

    expect(readiness).toEqual(LIVE_BODY);
    expect(readiness.lines[1]?.status).toBeNull();
  });

  it('baris tanpa `order_line_id` dibuang; urutan baris valid tetap', () => {
    expect(readReadinessLine({ product_code: 'X' })).toBeNull();
    expect(readReadinessLine({ order_line_id: '1' })).toBeNull();
    expect(readReadinessLine(null)).toBeNull();

    const parsed = readOrderReadiness({
      order_id: 3,
      lines: [{ order_line_id: 7, status: 'READY' }, 'rusak', { order_line_id: 8 }],
    });

    expect(parsed?.order_id).toBe(3);
    expect(parsed?.lines.map((line) => line.order_line_id)).toEqual([7, 8]);
    expect(parsed?.lines[1]?.status).toBeNull();
  });

  it('envelope tidak dikenali → null (dibedakan dari "kosong")', () => {
    expect(readOrderReadiness(null)).toBeNull();
    expect(readOrderReadiness({ lines: [] })).toBeNull();
    expect(readOrderReadiness({ order_id: 1, lines: 'bukan-array' })).toBeNull();
    expect(readOrderReadiness({ order_id: 1, lines: [] })).toEqual({ order_id: 1, lines: [] });
  });

  it('daftar status kesiapan', () => {
    expect([...READINESS_STATUSES]).toEqual(['WAITING', 'PARTIAL', 'READY']);
  });
});

describe('F2 — readiness (real) penanganan gagal (403 anon / 404 order / bentuk salah)', () => {
  it('403 (IsAuthenticated) → melempar pesan backend', async () => {
    const client = {
      get: async <T,>(): Promise<ApiResponse<T>> => ({
        ok: false,
        status: 403,
        error: { kind: 'http_error', message: 'Detail: Autentikasi diperlukan.' },
      }),
    } as unknown as ApiClient;

    await expect(getOrderReadiness(client, 1)).rejects.toThrow(/Autentikasi/);
  });

  it('404 order tidak ada → melempar pesan backend', async () => {
    const client = {
      get: async <T,>(): Promise<ApiResponse<T>> => ({
        ok: false,
        status: 404,
        error: { kind: 'http_error', message: 'Order 999 tidak ditemukan.' },
      }),
    } as unknown as ApiClient;

    await expect(getOrderReadiness(client, 999)).rejects.toThrow(/tidak ditemukan/);
  });

  it('bentuk respons tak dikenali → melempar pesan jelas', async () => {
    const { client } = stubClient('bukan-object');

    await expect(getOrderReadiness(client, 1)).rejects.toThrow(/tidak dikenali/);
  });
});

/* --------------------------------------------------------------------------
   F8 — recompute manual (§5.5). Path memakai `orders/{orderId}` juga.
   -------------------------------------------------------------------------- */

const RECOMPUTE_BODY = { processed: 5, waiting: 1, partial: 2, ready: 2, errors: 0 };

describe('F8 — buildOrderRecomputePath', () => {
  it('/garmen/orders/{orderId}/recompute-readiness/ (id ORDER, bukan OrderLine)', () => {
    expect(buildOrderRecomputePath(16)).toBe('/garmen/orders/16/recompute-readiness/');
    expect(buildOrderRecomputePath('3')).toBe('/garmen/orders/3/recompute-readiness/');
  });
});

describe('F8 — readRecomputeResult', () => {
  it('bentuk backend {processed,waiting,partial,ready,errors} → counter', () => {
    expect(readRecomputeResult(RECOMPUTE_BODY)).toEqual({
      ok: true,
      queued: 5,
      processed: 5,
      waiting: 1,
      partial: 2,
      ready: 2,
      errors: 0,
    });
  });

  it('bentuk docs {ok,queued} tetap diterima (queued dipakai apa adanya)', () => {
    expect(readRecomputeResult({ ok: true, queued: 3 })?.queued).toBe(3);
  });

  it('bentuk tak dikenal → null', () => {
    expect(readRecomputeResult(null)).toBeNull();
    expect(readRecomputeResult('ok')).toBeNull();
    expect(readRecomputeResult({})).toBeNull();
    expect(readRecomputeResult({ detail: 'x' })).toBeNull();
  });
});

describe('F8 — postRecomputeReadiness', () => {
  it('POST path recompute + body {} + counter', async () => {
    const calls: { path: string; body: unknown }[] = [];
    const client = {
      post: async <T,>(path: string, body: unknown): Promise<ApiResponse<T>> => {
        calls.push({ path, body });

        return { ok: true, status: 200, data: RECOMPUTE_BODY as T };
      },
    } as unknown as ApiClient;

    const result = await postRecomputeReadiness(client, 16);

    expect(calls).toEqual([{ path: '/garmen/orders/16/recompute-readiness/', body: {} }]);
    expect(result.queued).toBe(5);
  });

  it('URL penuh + credentials + POST lewat api-client', async () => {
    const calls: { url: string; init: RequestInit }[] = [];

    vi.stubGlobal(
      'fetch',
      vi.fn((url: RequestInfo | URL, init?: RequestInit) => {
        calls.push({ url: String(url), init: init ?? {} });

        return Promise.resolve(
          new Response(JSON.stringify(RECOMPUTE_BODY), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          }),
        );
      }),
    );

    try {
      const client = createApiClient({ baseUrl: 'http://localhost:8000/api/v1' });
      await postRecomputeReadiness(client, 1);

      expect(calls[0]?.url).toBe('http://localhost:8000/api/v1/garmen/orders/1/recompute-readiness/');
      expect(calls[0]?.init.method).toBe('POST');
      expect(calls[0]?.init.credentials).toBe('include');
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it('403 (perlu session) → melempar pesan', async () => {
    const client = {
      post: async <T,>(): Promise<ApiResponse<T>> => ({
        ok: false,
        status: 403,
        error: { kind: 'http_error', message: 'HTTP 403' },
      }),
    } as unknown as ApiClient;

    await expect(postRecomputeReadiness(client, 1)).rejects.toThrow(/403/);
  });

  it('bentuk respons tak dikenali → melempar pesan jelas', async () => {
    const client = {
      post: async <T,>(): Promise<ApiResponse<T>> => ({ ok: true, status: 200, data: {} as T }),
    } as unknown as ApiClient;

    await expect(postRecomputeReadiness(client, 1)).rejects.toThrow(/tidak dikenali/);
  });
});
