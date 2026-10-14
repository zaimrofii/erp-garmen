import { describe, expect, it } from 'vitest';
import {
  buildBundlesCrudPath,
  BUNDLES_CRUD_PATH,
  bundleCrudDetailPath,
  bundleCrudMergePath,
  bundleCrudPreviewPath,
  bundleCrudSplitPath,
  createBundles,
  deleteBundle,
  fetchBundleCrud,
  fetchBundlesCrud,
  mergeBundles,
  previewBundles,
  readBundleCrudCreated,
  readBundleCrudDetail,
  readBundleCrudListRow,
  readBundleCrudSaved,
  readBundleMergeSaved,
  readBundlePreview,
  splitBundle,
  toBundleCreateBody,
  toBundleUpdateBody,
  updateBundle,
} from '@/api/bundlesCrud';
import { MODE, isReal } from '@/api/_adapter';
import type { ApiClient, ApiResponse } from '@/integrations/api-client';

/**
 * H2.4 — adapter Bundle MES (`/api/v1/garmen/bundles/…`).
 *
 * Bentuk = PERSIS `apps_industry/garment/services/bundle_services.py`
 * (`bundle_row`/`bundle_detail_row`): list F3 tetap **9 key**, detail/CUD menambah
 * WO/order line + `events_count` + `ledger_status` + `{ledger_id, deleted, bundles[]}`
 * (MES-only ⇒ TANPA `odoo_id`), merge menambah `summary.merged_ids`.
 */

const LIST_ROW = {
  id: 9,
  code: '12-L-001',
  state: 'DRAFT',
  size: 'L',
  qty: 5,
  qty_done: 0,
  version: 'a'.repeat(64),
  current_work_center_code: null,
  allowed_actions: [{ id: 'BUNDLE_START', label: 'Mulai' }],
};

const DETAIL = {
  ...LIST_ROW,
  sku_variant: '',
  work_order_id: 3,
  work_order_code: 'WO-2026-0001',
  order_line_id: 12,
  order_code: 'SO-2026-0001',
  product_code: 'KAOS-POLO',
  current_work_center_id: null,
  production_line_id: null,
  production_line_code: null,
  events_count: 0,
  ledger_status: 'SKIPPED',
  created_at: '2026-10-12T02:00:00+00:00',
  updated_at: '2026-10-12T02:00:00+00:00',
};

interface RecordedRequest {
  path: string;
  method: string;
  body?: unknown;
  options?: unknown;
}

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
    request: async <T,>(path: string, options?: Record<string, unknown>): Promise<ApiResponse<T>> => {
      requests.push({ path, method: String(options?.['method'] ?? 'GET'), options });

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

describe('H2.4 — path & parser Bundle', () => {
  it('buildBundlesCrudPath mengirim filter terisi saja', () => {
    expect(buildBundlesCrudPath()).toBe(BUNDLES_CRUD_PATH);
    expect(
      buildBundlesCrudPath({ state: 'DRAFT', size: 'L', work_order_id: 3, limit: 20, offset: 0 }),
    ).toBe(`${BUNDLES_CRUD_PATH}?state=DRAFT&size=L&work_order_id=3&limit=20&offset=0`);
  });

  it('helper path detail/split/merge/preview benar', () => {
    expect(bundleCrudDetailPath(9)).toBe('/garmen/bundles/9/');
    expect(bundleCrudSplitPath(9)).toBe('/garmen/bundles/9/split/');
    expect(bundleCrudMergePath(9)).toBe('/garmen/bundles/9/merge/');
    expect(bundleCrudPreviewPath()).toBe('/garmen/bundles/preview/');
    expect(BUNDLES_CRUD_PATH).toBe('/garmen/bundles/');
  });

  it('readBundleCrudListRow: 9 key kontrak F3 + nama aksi dinormalisasi', () => {
    const row = readBundleCrudListRow(LIST_ROW);

    expect(row?.code).toBe('12-L-001');
    expect(row?.allowed_actions).toEqual(['BUNDLE_START']);
    expect(readBundleCrudListRow({ code: 'X' })).toBeNull();
    expect(readBundleCrudListRow(null)).toBeNull();
  });

  it('readBundleCrudDetail butuh version & membaca jejak MES-only', () => {
    const detail = readBundleCrudDetail(DETAIL);

    expect(detail?.work_order_code).toBe('WO-2026-0001');
    expect(detail?.ledger_status).toBe('SKIPPED');
    expect(detail?.events_count).toBe(0);
    expect(readBundleCrudDetail({ ...DETAIL, version: '' })).toBeNull();
  });

  it('readBundleCrudSaved membaca ledger_id/deleted/bundles[]', () => {
    const saved = readBundleCrudSaved({
      ...DETAIL,
      ledger_id: 901,
      deleted: false,
      bundles: [LIST_ROW],
      summary: { created: 1 },
    });

    expect(saved?.ledger_id).toBe(901);
    expect(saved?.deleted).toBe(false);
    expect(saved?.bundles).toHaveLength(1);
  });

  it('readBundleCrudCreated & readBundleMergeSaved membaca ringkasan', () => {
    const created = readBundleCrudCreated({
      ...DETAIL,
      created: 2,
      ledger_id: 5,
      deleted: false,
      summary: { created: 2, total_qty: 7 },
      bundles: [LIST_ROW],
    });
    const merged = readBundleMergeSaved({
      ...DETAIL,
      ledger_id: 7,
      deleted: false,
      summary: { merged: 2, qty: 13, merged_ids: [11, 12] },
    });

    expect(created?.created).toBe(2);
    expect(created?.summary.total_qty).toBe(7);
    expect(merged?.summary.merged_ids).toEqual([11, 12]);
  });

  it('readBundlePreview membaca plan[] + summary', () => {
    const preview = readBundlePreview({
      plan: [{ code: '12-L-001', size: 'L', sku_variant: '', qty: 5, work_order_id: 3 }],
      summary: { created: 0, planned: 1, total_qty: 5 },
    });

    expect(preview?.plan[0]?.code).toBe('12-L-001');
    expect(preview?.summary.planned).toBe(1);
  });

  it('toBundleCreateBody / toBundleUpdateBody membuang field kosong', () => {
    expect(
      toBundleCreateBody({
        work_order_id: 3,
        size_matrix: { L: 5 },
        bundle_size: null,
        sku_variant: '  ',
      }),
    ).toEqual({ work_order_id: 3, size_matrix: { L: 5 } });

    expect(
      toBundleUpdateBody({
        size: ' l ',
        sku_variant: ' POLO ',
        qty: 8,
        current_work_center_id: null,
        production_line_id: null,
      }),
    ).toEqual({ size: 'L', sku_variant: 'POLO', qty: 8 });
  });
});

describe('H2.4 — panggilan HTTP Bundle', () => {
  it('fetchBundlesCrud GET list (9 key/baris) + filter state', async () => {
    const { client, requests } = stubClient({
      rows: [LIST_ROW],
      total_count: 1,
      has_more: false,
      next_cursor: null,
    });

    const page = await fetchBundlesCrud(client, { state: 'DRAFT', limit: 20, offset: 0 });

    expect(requests[0]?.path).toBe('/garmen/bundles/?state=DRAFT&limit=20&offset=0');
    expect(page.rows[0]?.code).toBe('12-L-001');
  });

  it('fetchBundleCrud GET detail; HTTP gagal → melempar', async () => {
    const { client, requests } = stubClient(DETAIL);

    const detail = await fetchBundleCrud(client, 9);

    expect(requests[0]?.path).toBe('/garmen/bundles/9/');
    expect(detail.id).toBe(9);
    await expect(fetchBundleCrud(failingClient(404, 'Bundle 9 tidak ditemukan.'), 9)).rejects.toThrow();
  });

  it('previewBundles POST /bundles/preview/ tanpa menyimpan', async () => {
    const { client, requests } = stubClient({
      plan: [{ code: '12-L-001', size: 'L', sku_variant: '', qty: 5, work_order_id: 3 }],
      summary: { created: 0, planned: 1, total_qty: 5 },
    });

    const preview = await previewBundles(client, {
      work_order_id: 3,
      size_matrix: { L: 5 },
      bundle_size: 5,
      sku_variant: '',
    });

    expect(requests[0]).toEqual({
      path: '/garmen/bundles/preview/',
      method: 'POST',
      body: { work_order_id: 3, size_matrix: { L: 5 }, bundle_size: 5 },
      options: undefined,
    });
    expect(preview.plan).toHaveLength(1);
  });

  it('createBundles POST /bundles/ (+idempotency key)', async () => {
    const { client, requests } = stubClient({
      ...DETAIL,
      created: 2,
      ledger_id: 5,
      deleted: false,
      summary: { created: 2, total_qty: 7 },
      bundles: [LIST_ROW],
    });

    const saved = await createBundles(
      client,
      { work_order_id: 3, size_matrix: { L: 7 }, bundle_size: 5, sku_variant: '' },
      'key-1',
    );

    expect(requests[0]?.path).toBe('/garmen/bundles/');
    expect(requests[0]?.options).toEqual({ idempotencyKey: 'key-1' });
    expect(saved.created).toBe(2);
  });

  it('updateBundle PUT + baseVersion (optimistic lock)', async () => {
    const { client, requests } = stubClient({ ...DETAIL, ledger_id: 6, deleted: false });

    await updateBundle(
      client,
      9,
      { size: 'L', sku_variant: 'POLO', qty: 6, current_work_center_id: null, production_line_id: null },
      'a'.repeat(64),
    );

    expect(requests[0]?.path).toBe('/garmen/bundles/9/');
    expect(requests[0]?.method).toBe('PUT');
    expect(requests[0]?.options).toEqual({
      method: 'PUT',
      body: { size: 'L', sku_variant: 'POLO', qty: 6 },
      baseVersion: 'a'.repeat(64),
    });
  });

  it('deleteBundle DELETE: soft/hard (hard ⇒ null)', async () => {
    const soft = stubClient({ ...DETAIL, deleted: true, ledger_id: 8 });
    const saved = await deleteBundle(soft.client, 9);

    expect(soft.requests[0]?.method).toBe('DELETE');
    expect(saved?.deleted).toBe(true);

    const hard = stubClient({ deleted: true });
    expect(await deleteBundle(hard.client, 9)).toBeNull();
  });

  it('splitBundle & mergeBundles POST payload benar', async () => {
    const split = stubClient({ ...DETAIL, ledger_id: 9, deleted: false });
    await splitBundle(split.client, 9, [3, 2]);

    expect(split.requests[0]).toEqual({
      path: '/garmen/bundles/9/split/',
      method: 'POST',
      body: { parts: [3, 2] },
      options: undefined,
    });

    const merge = stubClient({
      ...DETAIL,
      ledger_id: 10,
      deleted: false,
      summary: { merged: 2, qty: 13, merged_ids: [11, 12] },
    });
    const merged = await mergeBundles(merge.client, 9, [11, 12]);

    expect(merge.requests[0]?.body).toEqual({ bundle_ids: [11, 12] });
    expect(merged.summary.merged_ids).toEqual([11, 12]);
  });

  it('MODE.bundlesCrud real dan F13 bundles tetap terpisah', () => {
    expect(MODE['bundlesCrud']).toBe('real');
    expect(isReal('bundlesCrud')).toBe(true);
    expect(MODE['bundles']).toBe('real');
  });
});