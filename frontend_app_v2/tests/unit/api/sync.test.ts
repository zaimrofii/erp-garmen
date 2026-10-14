import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  postSyncMaster,
  postSyncOdoo,
  postSyncScrap,
  SYNC_MASTER_ENTITIES,
  SYNC_MASTER_PATH,
  SYNC_ODOO_PATH,
  SYNC_SCRAP_PATH,
  SYNC_STAGES,
  SYNC_STAGE_RESOURCES,
} from '@/api/sync';
import { createApiClient, type ApiClient, type ApiResponse } from '@/integrations/api-client';

/** F2/2.9 — adapter sync BARU: 3 endpoint `IsAuthenticated` (kontrak §5). */

interface PostCall {
  path: string;
  body: unknown;
}

function stubClient(data: unknown): { client: ApiClient; calls: PostCall[] } {
  const calls: PostCall[] = [];

  const client = {
    post: async <T,>(path: string, body: unknown): Promise<ApiResponse<T>> => {
      calls.push({ path, body });

      return { ok: true, status: 200, data: data as T };
    },
  } as unknown as ApiClient;

  return { client, calls };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('F2 — sync (real) path & body', () => {
  it('konstanta path', () => {
    expect(SYNC_ODOO_PATH).toBe('/sync/odoo/');
    expect(SYNC_MASTER_PATH).toBe('/sync/master/');
    expect(SYNC_SCRAP_PATH).toBe('/sync/scrap/');
    expect([...SYNC_STAGES]).toEqual(['WIP', 'FG']);
    expect([...SYNC_STAGE_RESOURCES]).toEqual(['bundle', 'work_order']);
  });

  it('postSyncOdoo(WIP) → POST /sync/odoo/WIP/ + body kontrak §5.1', async () => {
    const queued = {
      ok: true,
      status: 'queued',
      task_id: 'task-1',
      sync_record_id: 15,
      stage: 'WIP',
      resource: 'bundle',
      resource_id: '16',
    };
    const { client, calls } = stubClient(queued);
    const input = { resource: 'bundle' as const, resource_id: '16', payload: { qty: 4, ref: 'WIP-16' } };

    const response = await postSyncOdoo(client, 'WIP', input);

    expect(calls).toEqual([{ path: '/sync/odoo/WIP/', body: input }]);
    expect(response.status).toBe('queued');
    expect(response.sync_record_id).toBe(15);
  });

  it('postSyncOdoo(FG) → POST /sync/odoo/FG/', async () => {
    const { client, calls } = stubClient({ ok: true, status: 'queued', task_id: 't' });

    await postSyncOdoo(client, 'FG', { resource: 'work_order', resource_id: '5', payload: {} });

    expect(calls[0]?.path).toBe('/sync/odoo/FG/');
  });

  it('postSyncMaster memakai entity PLURAL (bentuk tunggal = 404 di backend)', async () => {
    const { client, calls } = stubClient({ status: 'queued', task_id: 'task-2' });

    const response = await postSyncMaster(client, 'products');

    expect(calls).toEqual([{ path: '/sync/master/products/', body: {} }]);
    expect(response.task_id).toBe('task-2');
    expect([...SYNC_MASTER_ENTITIES]).toEqual([
      'products',
      'boms',
      'partners',
      'locations',
      'taxes',
      'uoms',
      'warehouses',
      'journals',
      'currencies',
    ]);
  });

  it('postSyncScrap → POST /sync/scrap/ + counter {sent,failed,skipped}', async () => {
    const { client, calls } = stubClient({ sent: 3, failed: 0, skipped: 1 });

    const response = await postSyncScrap(client);

    expect(calls).toEqual([{ path: '/sync/scrap/', body: {} }]);
    expect(response).toEqual({ sent: 3, failed: 0, skipped: 1 });
  });

  it('gagal HTTP (403 anon) → melempar pesan backend', async () => {
    const client = {
      post: async <T,>(): Promise<ApiResponse<T>> => ({
        ok: false,
        status: 403,
        error: { kind: 'http_error', message: 'Detail: Autentikasi diperlukan.' },
      }),
    } as unknown as ApiClient;

    await expect(postSyncScrap(client)).rejects.toThrow(/Autentikasi/);
  });
});

describe('F2 + F1.6 — sync lewat api-client (URL /api/v1 + credentials + CSRF)', () => {
  it('postSyncScrap memakai URL penuh, credentials include, X-CSRFToken', async () => {
    const calls: { url: string; init: RequestInit }[] = [];
    vi.stubGlobal('document', { cookie: 'sessionid=abc; csrftoken=csrf-123' });
    vi.stubGlobal(
      'fetch',
      vi.fn((url: RequestInfo | URL, init?: RequestInit) => {
        calls.push({ url: String(url), init: init ?? {} });

        return Promise.resolve(
          new Response(JSON.stringify({ sent: 1, failed: 0, skipped: 0 }), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          })
        );
      })
    );

    const client = createApiClient({ baseUrl: 'http://localhost:8000/api/v1' });
    const response = await postSyncScrap(client);

    const headers = (calls[0]?.init.headers ?? {}) as Record<string, string>;

    expect(calls[0]?.url).toBe('http://localhost:8000/api/v1/sync/scrap/');
    expect(calls[0]?.init.method).toBe('POST');
    expect(calls[0]?.init.credentials).toBe('include');
    expect(headers['X-CSRFToken']).toBe('csrf-123');
    expect(response.sent).toBe(1);
  });
});
