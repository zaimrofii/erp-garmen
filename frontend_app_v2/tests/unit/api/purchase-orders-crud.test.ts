import { describe, expect, it } from 'vitest';
import {
  buildPurchaseOrdersMesPath,
  createPurchaseOrderMes,
  deletePurchaseOrderMes,
  fetchPurchaseOrderMes,
  fetchPurchaseOrderOdooState,
  fetchPurchaseOrdersMes,
  PURCHASE_ORDERS_MES_LIMIT_DEFAULT,
  PURCHASE_ORDERS_MES_LIMIT_MAX,
  PURCHASE_ORDERS_MES_PATH,
  PURCHASE_ORDER_MES_ACTIONS,
  PURCHASE_ORDER_MES_STATES,
  purchaseOrderMesActionPath,
  purchaseOrderMesDetailPath,
  purchaseOrderMesSyncStatePath,
  readPurchaseOrderMesDetail,
  readPurchaseOrderMesLineRow,
  readPurchaseOrderMesPage,
  readPurchaseOrderMesRow,
  readPurchaseOrderMesSaved,
  readPurchaseOrderOdooState,
  runPurchaseOrderMesAction,
  toPurchaseOrderMesBody,
  updatePurchaseOrderMes,
} from '@/api/purchaseOrdersCrud';
import { MODE, isReal } from '@/api/_adapter';
import type { ApiClient, ApiResponse } from '@/integrations/api-client';
import type { PurchaseOrderMesInput, PurchaseOrderMesRow } from '@/types/purchase-order';

/**
 * H2.2 — adapter Purchase Order MES (`/api/v1/garmen/purchase-orders/…`).
 *
 * Bentuk = PERSIS `apps_industry/garment/services/purchase_order_services.py`
 * (`purchase_order_row`/`purchase_order_detail_row`/`purchase_order_line_row`):
 * qty/harga/subtotal/total = **string** (Decimal 2 desimal), detail menambah
 * `lines[]` + `odoo_sync_status` + `allowed_actions`, POST/PUT/transisi menambah
 * `{sync_record_id, task_id, queued}`, dan `sync-odoo-state` mengembalikan
 * `{odoo_id, odoo_state, odoo_name}` (read-only).
 */

const LINE = {
  id: 41,
  product_id: 9,
  product_code: 'KAIN-COTTON',
  product_name: 'Kain Cotton 30s',
  qty: '10.50',
  price_unit: '30000.00',
  subtotal: '315000.00',
  tax_ids: [20],
  date_planned: '2026-11-25',
  odoo_id: null,
  created_at: '2026-10-11T02:00:00+00:00',
  updated_at: '2026-10-11T02:00:00+00:00',
};

const ROW: PurchaseOrderMesRow = {
  id: 7,
  code: 'PO-2026-0001',
  partner_ref: 'PO-2026-0001',
  vendor_id: 45,
  vendor_name: 'PT Supplier A',
  vendor_code: 'VEND-A',
  state: 'DRAFT',
  expected_date: '2026-11-30',
  notes: 'PO uji',
  lines_count: 1,
  amount_total: '315000.00',
  odoo_id: null,
  created_at: '2026-10-11T02:00:00+00:00',
  updated_at: '2026-10-11T02:00:00+00:00',
};

const DETAIL_BODY = {
  ...ROW,
  lines: [LINE],
  odoo_sync_status: 'PENDING',
  allowed_actions: ['CONFIRMED', 'CANCELLED'],
};

const SAVED_BODY = { ...DETAIL_BODY, sync_record_id: 88, task_id: 'task-po-1', queued: true };

const LIVE_BODY = {
  rows: [ROW, { ...ROW, id: 8, code: 'PO-2026-0002', state: 'CONFIRMED', odoo_id: 555 }],
  total_count: 2,
  has_more: false,
  next_cursor: null,
};

const INPUT: PurchaseOrderMesInput = {
  vendor_id: 45,
  expected_date: '2026-11-30',
  notes: ' PO uji ',
  lines: [
    {
      product_id: 9,
      qty: '10.50',
      price_unit: '30000.00',
      tax_ids: [20],
      date_planned: '2026-11-25',
    },
  ],
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

describe('H2.2 — MODE, path & parsing', () => {
  it('MODE.purchaseOrdersCrud = real + konstanta path/limit/aksi', () => {
    expect(MODE['purchaseOrdersCrud']).toBe('real');
    expect(isReal('purchaseOrdersCrud')).toBe(true);
    // B10 (monitoring) TETAP terpisah.
    expect(MODE['purchaseOrders']).toBe('real');
    expect(PURCHASE_ORDERS_MES_PATH).toBe('/garmen/purchase-orders/');
    expect(PURCHASE_ORDERS_MES_LIMIT_DEFAULT).toBe(50);
    expect(PURCHASE_ORDERS_MES_LIMIT_MAX).toBe(200);
    expect([...PURCHASE_ORDER_MES_STATES]).toEqual(['DRAFT', 'CONFIRMED', 'DONE', 'CANCELLED']);
    expect([...PURCHASE_ORDER_MES_ACTIONS]).toEqual(['confirm', 'done', 'cancel']);
    expect(purchaseOrderMesDetailPath(7)).toBe('/garmen/purchase-orders/7/');
    expect(purchaseOrderMesActionPath(7, 'confirm')).toBe('/garmen/purchase-orders/7/confirm/');
    expect(purchaseOrderMesSyncStatePath(7)).toBe('/garmen/purchase-orders/7/sync-odoo-state/');
  });

  it('buildPurchaseOrdersMesPath: hanya param terisi yang dikirim', () => {
    expect(buildPurchaseOrdersMesPath()).toBe('/garmen/purchase-orders/');
    expect(buildPurchaseOrdersMesPath({ search: 'kain', state: 'DRAFT', limit: 50 })).toBe(
      '/garmen/purchase-orders/?search=kain&state=DRAFT&limit=50',
    );
    expect(buildPurchaseOrdersMesPath({ vendor_id: 45, cursor: 20 })).toBe(
      '/garmen/purchase-orders/?vendor_id=45&cursor=20',
    );
  });

  it('readPurchaseOrderMesRow / LineRow: qty & harga tetap string', () => {
    const row = readPurchaseOrderMesRow(ROW);
    expect(row?.code).toBe('PO-2026-0001');
    expect(row?.partner_ref).toBe('PO-2026-0001');
    expect(row?.amount_total).toBe('315000.00');
    expect(readPurchaseOrderMesRow({ code: 'tanpa-id' })).toBeNull();

    const line = readPurchaseOrderMesLineRow(LINE);
    expect(line?.qty).toBe('10.50');
    expect(line?.price_unit).toBe('30000.00');
    expect(line?.subtotal).toBe('315000.00');
    expect(line?.tax_ids).toEqual([20]);
    expect(line?.date_planned).toBe('2026-11-25');
    expect(readPurchaseOrderMesLineRow({ product_id: 9 })).toBeNull();
  });

  it('readPurchaseOrderMesDetail & Saved: lines + allowed_actions + jejak push', () => {
    const detail = readPurchaseOrderMesDetail(DETAIL_BODY);

    expect(detail?.lines).toHaveLength(1);
    expect(detail?.allowed_actions).toEqual(['CONFIRMED', 'CANCELLED']);
    expect(detail?.odoo_sync_status).toBe('PENDING');
    expect(detail?.notes).toBe('PO uji');

    const saved = readPurchaseOrderMesSaved(SAVED_BODY);
    expect(saved?.sync_record_id).toBe(88);
    expect(saved?.task_id).toBe('task-po-1');
    expect(saved?.queued).toBe(true);
    expect(readPurchaseOrderMesSaved({ ok: true })).toBeNull();
  });

  it('readPurchaseOrderMesPage & readPurchaseOrderOdooState', () => {
    const page = readPurchaseOrderMesPage(LIVE_BODY);

    expect(page?.total_count).toBe(2);
    expect(page?.rows[1]?.state).toBe('CONFIRMED');
    expect(page?.rows[1]?.odoo_id).toBe(555);
    expect(readPurchaseOrderMesPage({ rows: 'bukan-array' })).toBeNull();

    expect(
      readPurchaseOrderOdooState({ odoo_id: 13, odoo_state: 'purchase', odoo_name: 'P00013' }),
    ).toEqual({ odoo_id: 13, odoo_state: 'purchase', odoo_name: 'P00013' });
    expect(readPurchaseOrderOdooState({ odoo_state: 'purchase' })).toBeNull();
  });

  it('toPurchaseOrderMesBody: trim notes + baris ternormalisasi', () => {
    expect(toPurchaseOrderMesBody(INPUT)).toEqual({
      vendor_id: 45,
      expected_date: '2026-11-30',
      notes: 'PO uji',
      lines: [
        {
          product_id: 9,
          qty: '10.50',
          price_unit: '30000.00',
          tax_ids: [20],
          date_planned: '2026-11-25',
        },
      ],
    });
  });
});

describe('H2.2 — jaringan (list/detail/tulis/transisi/sync-state)', () => {
  it('fetchPurchaseOrdersMes: path + query, bentuk rusak → melempar', async () => {
    const { client, requests } = stubClient(LIVE_BODY);

    const page = await fetchPurchaseOrdersMes(client, {
      search: 'kain',
      state: 'DRAFT',
      limit: 200,
    });

    expect(requests).toEqual([
      { path: '/garmen/purchase-orders/?search=kain&state=DRAFT&limit=200', method: 'GET' },
    ]);
    expect(page.total_count).toBe(2);

    await expect(fetchPurchaseOrdersMes(stubClient({ ok: true }).client)).rejects.toThrow(
      /tidak dikenali/,
    );
  });

  it('fetchPurchaseOrderMes: detail + melempar pesan backend 404/403', async () => {
    const { client, requests } = stubClient(DETAIL_BODY);

    const detail = await fetchPurchaseOrderMes(client, 7);
    expect(requests).toEqual([{ path: '/garmen/purchase-orders/7/', method: 'GET' }]);
    expect(detail.lines[0]?.qty).toBe('10.50');

    await expect(
      fetchPurchaseOrderMes(failingClient(404, 'Purchase Order tidak ditemukan.'), 9),
    ).rejects.toThrow(/tidak ditemukan/);
    await expect(fetchPurchaseOrderMes(failingClient(403, 'HTTP 403'), 9)).rejects.toThrow(/403/);
  });

  it('createPurchaseOrderMes: POST body + parse saved; 400/403 melempar', async () => {
    const { client, requests } = stubClient(SAVED_BODY);

    const saved = await createPurchaseOrderMes(client, INPUT);

    expect(requests).toEqual([
      { path: '/garmen/purchase-orders/', method: 'POST', body: toPurchaseOrderMesBody(INPUT) },
    ]);
    expect(saved.id).toBe(7);
    expect(saved.queued).toBe(true);

    await expect(
      createPurchaseOrderMes(failingClient(400, 'Vendor 999 tidak ditemukan.'), INPUT),
    ).rejects.toThrow(/tidak ditemukan/);
    await expect(createPurchaseOrderMes(failingClient(403, 'HTTP 403'), INPUT)).rejects.toThrow(
      /403/,
    );
  });

  it('updatePurchaseOrderMes (PUT) & deletePurchaseOrderMes (DELETE)', async () => {
    const { client, requests } = stubClient(SAVED_BODY);

    await updatePurchaseOrderMes(client, 7, INPUT);
    expect(requests).toEqual([
      { path: '/garmen/purchase-orders/7/', method: 'PUT', body: toPurchaseOrderMesBody(INPUT) },
    ]);

    const removal = stubClient({ deleted: true, id: 7 });
    await deletePurchaseOrderMes(removal.client, 7);
    expect(removal.requests).toEqual([
      { path: '/garmen/purchase-orders/7/', method: 'DELETE', body: undefined },
    ]);
  });

  it('runPurchaseOrderMesAction: confirm tanpa body, cancel dengan reason', async () => {
    const { client, requests } = stubClient(SAVED_BODY);

    await runPurchaseOrderMesAction(client, 7, 'confirm');
    await runPurchaseOrderMesAction(client, 7, 'done');
    await runPurchaseOrderMesAction(client, 7, 'cancel', '  vendor batal  ');
    await runPurchaseOrderMesAction(client, 7, 'cancel', '   ');

    expect(requests).toEqual([
      { path: '/garmen/purchase-orders/7/confirm/', method: 'POST', body: {} },
      { path: '/garmen/purchase-orders/7/done/', method: 'POST', body: {} },
      {
        path: '/garmen/purchase-orders/7/cancel/',
        method: 'POST',
        body: { reason: 'vendor batal' },
      },
      { path: '/garmen/purchase-orders/7/cancel/', method: 'POST', body: {} },
    ]);

    await expect(
      runPurchaseOrderMesAction(failingClient(400, 'Harga satuan harus > 0.'), 7, 'confirm'),
    ).rejects.toThrow(/Harga satuan/);
  });

  it('fetchPurchaseOrderOdooState: POST sync-odoo-state + parse; error melempar', async () => {
    const { client, requests } = stubClient({
      odoo_id: 13,
      odoo_state: 'purchase',
      odoo_name: 'P00013',
    });

    const info = await fetchPurchaseOrderOdooState(client, 7);

    expect(requests).toEqual([
      { path: '/garmen/purchase-orders/7/sync-odoo-state/', method: 'POST', body: {} },
    ]);
    expect(info.odoo_state).toBe('purchase');

    await expect(
      fetchPurchaseOrderOdooState(failingClient(400, 'PO belum punya `odoo_id`.'), 7),
    ).rejects.toThrow(/odoo_id/);
    await expect(
      fetchPurchaseOrderOdooState(stubClient({ odoo_state: 'purchase' }).client, 7),
    ).rejects.toThrow(/tidak dikenali/);
  });
});
