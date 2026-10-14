import { describe, expect, it } from 'vitest';
import {
  buildWorkOrdersCrudPath,
  createWorkOrderCrud,
  deleteWorkOrderCrud,
  fetchWorkOrderCrud,
  fetchWorkOrdersCrud,
  generateWorkOrdersForOrder,
  orderGenerateWoPath,
  readWorkOrderCrudDetail,
  readWorkOrderCrudListRow,
  readWorkOrderCrudSaved,
  readWorkOrderGenerateResult,
  readWorkOrderSplitSaved,
  runWorkOrderCrudAction,
  splitWorkOrderCrud,
  toWorkOrderCrudBody,
  updateWorkOrderCrud,
  workOrderCrudActionPath,
  workOrderCrudDetailPath,
  workOrderCrudSplitPath,
  WORK_ORDERS_CRUD_PATH,
} from '@/api/workOrdersCrud';
import { MODE, isReal } from '@/api/_adapter';
import type { ApiClient, ApiResponse } from '@/integrations/api-client';

/**
 * H2.3 — adapter Work Order MES (`/api/v1/garmen/work-orders/…`).
 *
 * Bentuk = PERSIS `apps_industry/garment/services/work_order_services.py`
 * (`wo_row`/`wo_detail_row`): list F3 tetap **5 key**, detail menambah order line +
 * `bundles[]` + `allowed_actions` + `version`, CUD menambah `{ledger_id, cancelled,
 * deleted}` (MES-only ⇒ TANPA `odoo_id`/`task_id`/`queued`), split menambah
 * `work_orders[]` + `summary.parts`.
 */

const LIST_ROW = {
  id: 5,
  code: 'WO-2026-0001',
  state: 'DRAFT',
  qty_planned: 20,
  qty_done: 0,
};

const DETAIL = {
  ...LIST_ROW,
  order_line_id: 11,
  order_id: 3,
  order_code: 'SO-2026-0001',
  product_id: 9,
  product_code: 'KAOS-POLO',
  bundles_count: 1,
  allowed_actions: ['WO_START', 'WO_CANCEL'],
  created_at: '2026-10-11T02:00:00+00:00',
  updated_at: '2026-10-11T02:00:00+00:00',
  version: 'a'.repeat(64),
  bundles: [{ id: 77, code: 'BND-1', state: 'DRAFT', size: 'M', qty: 20, qty_done: 0 }],
};

const SAVED = { ...DETAIL, ledger_id: 901, cancelled: false, deleted: false };

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
    get: async <T,>() => response<T>(),
    post: async <T,>() => response<T>(),
    request: async <T,>() => response<T>(),
  } as unknown as ApiClient;
}

describe('H2.3 — path & parser Work Order', () => {
  it('buildWorkOrdersCrudPath hanya mengirim param terisi', () => {
    expect(buildWorkOrdersCrudPath()).toBe(WORK_ORDERS_CRUD_PATH);
    expect(buildWorkOrdersCrudPath({ limit: 20, offset: 40 })).toBe(
      `${WORK_ORDERS_CRUD_PATH}?limit=20&offset=40`,
    );
  });

  it('helper path detail/split/aksi/generate benar', () => {
    expect(workOrderCrudDetailPath(5)).toBe('/garmen/work-orders/5/');
    expect(workOrderCrudSplitPath(5)).toBe('/garmen/work-orders/5/split/');
    expect(workOrderCrudActionPath(5, 'WO_START')).toBe('/garmen/work-orders/5/WO_START/');
    expect(orderGenerateWoPath(3)).toBe('/garmen/orders/3/generate-wo/');
    expect(WORK_ORDERS_CRUD_PATH).toBe('/garmen/work-orders/');
  });

  it('readWorkOrderCrudListRow memetakan 5 key (kontrak F3)', () => {
    expect(readWorkOrderCrudListRow(LIST_ROW)).toEqual(LIST_ROW);
    expect(readWorkOrderCrudListRow({ code: 'X' })).toBeNull();
    expect(readWorkOrderCrudListRow(null)).toBeNull();
  });

  it('readWorkOrderCrudDetail membaca bundles + version + allowed_actions', () => {
    const parsed = readWorkOrderCrudDetail(DETAIL);

    expect(parsed).not.toBeNull();
    expect(parsed?.bundles[0]?.code).toBe('BND-1');
    expect(parsed?.version).toHaveLength(64);
    expect(parsed?.allowed_actions).toEqual(['WO_START', 'WO_CANCEL']);
    expect(parsed?.order_code).toBe('SO-2026-0001');
  });

  it('readWorkOrderCrudDetail menoleransi allowed_actions/bundles rusak', () => {
    const parsed = readWorkOrderCrudDetail({
      ...DETAIL,
      allowed_actions: ['WO_START', 7],
      bundles: [null, { id: 'x' }],
    });

    expect(parsed?.allowed_actions).toEqual(['WO_START']);
    expect(parsed?.bundles).toEqual([]);
  });

  it('readWorkOrderCrudSaved membaca jejak MES-only (ledger_id/cancelled/deleted)', () => {
    const parsed = readWorkOrderCrudSaved(SAVED);

    expect(parsed?.ledger_id).toBe(901);
    expect(parsed?.cancelled).toBe(false);
    expect(parsed?.deleted).toBe(false);
  });

  it('readWorkOrderSplitSaved membaca work_orders[] + summary.parts', () => {
    const parsed = readWorkOrderSplitSaved({
      ...SAVED,
      qty_planned: 60,
      work_orders: [{ ...LIST_ROW, id: 6, code: 'WO-2026-0002', qty_planned: 40 }],
      summary: { parts: [60, 40], created: 1 },
    });

    expect(parsed?.summary.parts).toEqual([60, 40]);
    expect(parsed?.summary.created).toBe(1);
    expect(parsed?.work_orders[0]?.code).toBe('WO-2026-0002');
  });

  it('readWorkOrderGenerateResult membaca summary created/skipped', () => {
    const parsed = readWorkOrderGenerateResult({
      order_id: 3,
      order_code: 'SO-2026-0001',
      summary: { created: 2, skipped: 1 },
      work_orders: [LIST_ROW],
    });

    expect(parsed?.summary).toEqual({ created: 2, skipped: 1 });
    expect(parsed?.order_code).toBe('SO-2026-0001');
    expect(parsed?.work_orders).toHaveLength(1);
  });

  it('toWorkOrderCrudBody membuang kode kosong & qty null', () => {
    expect(toWorkOrderCrudBody({ order_line_id: 11, code: '  ', qty_planned: null })).toEqual({
      order_line_id: 11,
    });
    expect(toWorkOrderCrudBody({ order_line_id: 11, code: ' WO-X ', qty_planned: 7 })).toEqual({
      order_line_id: 11,
      code: 'WO-X',
      qty_planned: 7,
    });
  });
});

describe('H2.3 — panggilan HTTP Work Order', () => {
  it('fetchWorkOrdersCrud GET list (5 key/baris) + limit/offset', async () => {
    const { client, requests } = stubClient({
      rows: [LIST_ROW],
      total_count: 1,
      has_more: false,
      next_cursor: null,
    });

    const page = await fetchWorkOrdersCrud(client, { limit: 20, offset: 0 });

    expect(requests[0]).toEqual({ path: '/garmen/work-orders/?limit=20&offset=0', method: 'GET' });
    expect(page.rows[0]?.code).toBe('WO-2026-0001');
    expect(page.total_count).toBe(1);
  });

  it('fetchWorkOrderCrud GET detail; HTTP gagal → melempar', async () => {
    const { client, requests } = stubClient(DETAIL);

    const detail = await fetchWorkOrderCrud(client, 5);

    expect(requests[0]?.path).toBe('/garmen/work-orders/5/');
    expect(detail.id).toBe(5);

    await expect(fetchWorkOrderCrud(failingClient(404, 'WorkOrder 5 tidak ditemukan.'), 5)).rejects
      .toThrow();
  });

  it('createWorkOrderCrud POST body H2.3', async () => {
    const { client, requests } = stubClient(SAVED);

    const saved = await createWorkOrderCrud(client, {
      order_line_id: 11,
      code: '',
      qty_planned: null,
    });

    expect(requests[0]).toEqual({
      path: '/garmen/work-orders/',
      method: 'POST',
      body: { order_line_id: 11 },
    });
    expect(saved.ledger_id).toBe(901);
  });

  it('updateWorkOrderCrud PUT kode + qty', async () => {
    const { client, requests } = stubClient(SAVED);

    await updateWorkOrderCrud(client, 5, { order_line_id: null, code: 'WO-UPD', qty_planned: 30 });

    expect(requests[0]).toEqual({
      path: '/garmen/work-orders/5/',
      method: 'PUT',
      body: { code: 'WO-UPD', qty_planned: 30 },
    });
  });

  it('deleteWorkOrderCrud DELETE: soft delete → saved; hard delete → null', async () => {
    const soft = stubClient({ ...SAVED, state: 'CANCELLED', cancelled: true });
    const saved = await deleteWorkOrderCrud(soft.client, 5);

    expect(soft.requests[0]).toEqual({ path: '/garmen/work-orders/5/', method: 'DELETE' });
    expect(saved?.cancelled).toBe(true);

    const hard = stubClient({ deleted: true });
    expect(await deleteWorkOrderCrud(hard.client, 5)).toBeNull();
  });

  it('splitWorkOrderCrud POST {splits} + aksi state POST <ACTION>/', async () => {
    const split = stubClient({
      ...SAVED,
      work_orders: [{ ...LIST_ROW, id: 6 }],
      summary: { parts: [12, 8], created: 1 },
    });

    const result = await splitWorkOrderCrud(split.client, 5, [12, 8]);

    expect(split.requests[0]).toEqual({
      path: '/garmen/work-orders/5/split/',
      method: 'POST',
      body: { splits: [12, 8] },
    });
    expect(result.work_orders).toHaveLength(1);

    const action = stubClient(DETAIL);
    await runWorkOrderCrudAction(action.client, 5, 'WO_START');

    expect(action.requests[0]).toEqual({
      path: '/garmen/work-orders/5/WO_START/',
      method: 'POST',
      body: {},
    });
  });

  it('generateWorkOrdersForOrder POST /orders/<id>/generate-wo/', async () => {
    const { client, requests } = stubClient({
      order_id: 3,
      order_code: 'SO-2026-0001',
      summary: { created: 2, skipped: 0 },
      work_orders: [LIST_ROW],
    });

    const result = await generateWorkOrdersForOrder(client, 3);

    expect(requests[0]).toEqual({ path: '/garmen/orders/3/generate-wo/', method: 'POST', body: {} });
    expect(result.summary.created).toBe(2);
  });

  it('MODE.workOrdersCrud real dan F13 workOrders tetap terpisah', () => {
    expect(MODE['workOrdersCrud']).toBe('real');
    expect(isReal('workOrdersCrud')).toBe(true);
    expect(MODE['workOrders']).toBe('real');
  });
});


