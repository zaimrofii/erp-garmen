import { describe, expect, it } from 'vitest';
import {
  buildSalesOrdersPath,
  createOrder,
  deleteOrder,
  fetchOrder,
  fetchOrders,
  readSalesOrderDetail,
  readSalesOrderLineRow,
  readSalesOrderPage,
  readSalesOrderRow,
  readSalesOrderSaved,
  runOrderAction,
  SALES_ORDERS_LIMIT_DEFAULT,
  SALES_ORDERS_LIMIT_MAX,
  SALES_ORDERS_PATH,
  SALES_ORDER_ACTIONS,
  SALES_ORDER_STATES,
  salesOrderActionPath,
  salesOrderDetailPath,
  toSalesOrderBody,
  updateOrder,
} from '@/api/salesOrders';
import { MODE, isReal } from '@/api/_adapter';
import type { ApiClient, ApiResponse } from '@/integrations/api-client';
import type { SalesOrderInput, SalesOrderRow } from '@/types/sales-order';

/**
 * H2.1 — adapter Sales Order (`/api/v1/garmen/orders/…`).
 *
 * Bentuk = PERSIS `apps_industry/garment/services/order_services.py::order_row` /
 * `order_detail_row` / `line_row`: harga/total = **string** (Decimal backend),
 * detail menambah `lines[]` + `work_orders_count` + `odoo_sync_status` +
 * `allowed_actions`, dan POST/PUT/transisi menambah `{sync_record_id, task_id, queued}`.
 */

const LINE = {
  id: 41,
  product_id: 9,
  product_code: 'KAOS-L',
  product_name: 'Kaos L',
  qty: 12,
  tag: 'EXPORT',
  ticket_code: null,
  price_unit: '75000.00',
  subtotal: '900000.00',
  tax_ids: [19],
  odoo_id: null,
  created_at: '2026-10-11T02:00:00+00:00',
  updated_at: '2026-10-11T02:00:00+00:00',
};

const ROW: SalesOrderRow = {
  id: 7,
  code: 'SO-2026-0001',
  client_order_ref: 'SO-2026-0001',
  customer_id: 51,
  customer_name: 'PT Buyer Export',
  order_type: 'EXPORT',
  state: 'DRAFT',
  priority: 0,
  deadline: '2026-11-30T00:00:00+00:00',
  lines_count: 1,
  amount_total: '900000.00',
  odoo_id: null,
  created_at: '2026-10-11T02:00:00+00:00',
  updated_at: '2026-10-11T02:00:00+00:00',
};

const DETAIL_BODY = {
  ...ROW,
  lines: [LINE],
  work_orders_count: 0,
  odoo_sync_status: 'PENDING',
  allowed_actions: ['CONFIRMED', 'CANCELLED'],
};

const SAVED_BODY = { ...DETAIL_BODY, sync_record_id: 77, task_id: 'task-so-1', queued: true };

const LIVE_BODY = {
  rows: [ROW, { ...ROW, id: 8, code: 'SO-2026-0002', state: 'CONFIRMED', odoo_id: 555 }],
  total_count: 2,
  has_more: false,
  next_cursor: null,
};

const INPUT: SalesOrderInput = {
  customer_id: 51,
  order_type: 'export',
  priority: 3,
  deadline: '2026-11-30',
  lines: [{ product_id: 9, qty: 12, price_unit: '75000.00', tag: ' EXPORT ', tax_ids: [19] }],
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


describe('H2.1 — MODE, path & parsing', () => {
  it('MODE.salesOrders = real + konstanta path/limit/aksi', () => {
    expect(MODE['salesOrders']).toBe('real');
    expect(isReal('salesOrders')).toBe(true);
    expect(SALES_ORDERS_PATH).toBe('/garmen/orders/');
    expect(SALES_ORDERS_LIMIT_DEFAULT).toBe(50);
    expect(SALES_ORDERS_LIMIT_MAX).toBe(200);
    expect([...SALES_ORDER_STATES]).toEqual(['DRAFT', 'CONFIRMED', 'DONE', 'CANCELLED']);
    expect([...SALES_ORDER_ACTIONS]).toEqual(['confirm', 'done', 'cancel']);
    expect(salesOrderDetailPath(7)).toBe('/garmen/orders/7/');
    expect(salesOrderActionPath(7, 'confirm')).toBe('/garmen/orders/7/confirm/');
  });

  it('buildSalesOrdersPath: hanya param terisi yang dikirim', () => {
    expect(buildSalesOrdersPath()).toBe('/garmen/orders/');
    expect(buildSalesOrdersPath({ search: 'kaos', state: 'DRAFT', limit: 50 })).toBe(
      '/garmen/orders/?search=kaos&state=DRAFT&limit=50',
    );
    expect(buildSalesOrdersPath({ customer_id: 51, cursor: 20 })).toBe(
      '/garmen/orders/?customer_id=51&cursor=20',
    );
  });

  it('readSalesOrderRow / readSalesOrderLineRow: harga tetap string', () => {
    const row = readSalesOrderRow(ROW);
    expect(row?.code).toBe('SO-2026-0001');
    expect(row?.amount_total).toBe('900000.00');
    expect(readSalesOrderRow({ code: 'tanpa-id' })).toBeNull();

    const line = readSalesOrderLineRow(LINE);
    expect(line?.price_unit).toBe('75000.00');
    expect(line?.subtotal).toBe('900000.00');
    expect(line?.tax_ids).toEqual([19]);
    expect(readSalesOrderLineRow({ product_id: 9 })).toBeNull();
  });

  it('readSalesOrderDetail & Saved: lines + allowed_actions + jejak push', () => {
    const detail = readSalesOrderDetail(DETAIL_BODY);

    expect(detail?.lines).toHaveLength(1);
    expect(detail?.allowed_actions).toEqual(['CONFIRMED', 'CANCELLED']);
    expect(detail?.work_orders_count).toBe(0);
    expect(detail?.odoo_sync_status).toBe('PENDING');

    const saved = readSalesOrderSaved(SAVED_BODY);
    expect(saved?.sync_record_id).toBe(77);
    expect(saved?.task_id).toBe('task-so-1');
    expect(saved?.queued).toBe(true);
    expect(readSalesOrderSaved({ ok: true })).toBeNull();
  });

  it('readSalesOrderPage: amplop ListPage backend', () => {
    const page = readSalesOrderPage(LIVE_BODY);

    expect(page?.total_count).toBe(2);
    expect(page?.rows[1]?.state).toBe('CONFIRMED');
    expect(page?.rows[1]?.odoo_id).toBe(555);
    expect(readSalesOrderPage({ rows: 'bukan-array' })).toBeNull();
  });

  it('toSalesOrderBody: trim + uppercase tipe order + baris ternormalisasi', () => {
    expect(toSalesOrderBody(INPUT)).toEqual({
      customer_id: 51,
      order_type: 'EXPORT',
      priority: 3,
      deadline: '2026-11-30',
      lines: [{ product_id: 9, qty: 12, price_unit: '75000.00', tag: 'EXPORT', tax_ids: [19] }],
    });
  });
});


describe('H2.1 — jaringan (list/detail/tulis/transisi)', () => {
  it('fetchOrders: path + query, dan bentuk rusak → melempar', async () => {
    const { client, requests } = stubClient(LIVE_BODY);

    const page = await fetchOrders(client, { search: 'kaos', state: 'DRAFT', limit: 200 });

    expect(requests).toEqual([
      { path: '/garmen/orders/?search=kaos&state=DRAFT&limit=200', method: 'GET' },
    ]);
    expect(page.total_count).toBe(2);

    await expect(fetchOrders(stubClient({ ok: true }).client)).rejects.toThrow(/tidak dikenali/);
  });

  it('fetchOrder: `/garmen/orders/<id>/` + melempar pesan backend 404/403', async () => {
    const { client, requests } = stubClient(DETAIL_BODY);

    const detail = await fetchOrder(client, 7);
    expect(requests).toEqual([{ path: '/garmen/orders/7/', method: 'GET' }]);
    expect(detail.lines[0]?.qty).toBe(12);

    await expect(fetchOrder(failingClient(404, 'Order tidak ditemukan.'), 9)).rejects.toThrow(
      /tidak ditemukan/,
    );
    await expect(fetchOrder(failingClient(403, 'HTTP 403'), 9)).rejects.toThrow(/403/);
  });

  it('createOrder: POST body + parse jawaban saved (sync_record_id/queued)', async () => {
    const { client, requests } = stubClient(SAVED_BODY);

    const saved = await createOrder(client, INPUT);

    expect(requests).toEqual([
      { path: '/garmen/orders/', method: 'POST', body: toSalesOrderBody(INPUT) },
    ]);
    expect(saved.id).toBe(7);
    expect(saved.queued).toBe(true);
    expect(saved.lines[0]?.price_unit).toBe('75000.00');

    await expect(
      createOrder(failingClient(400, 'Customer 999999 tidak ditemukan.'), INPUT),
    ).rejects.toThrow(/tidak ditemukan/);
    await expect(createOrder(failingClient(403, 'HTTP 403'), INPUT)).rejects.toThrow(/403/);
  });

  it('updateOrder (PUT, DRAFT-only) & deleteOrder (DELETE hard delete)', async () => {
    const { client, requests } = stubClient(SAVED_BODY);

    await updateOrder(client, 7, INPUT);
    expect(requests).toEqual([
      { path: '/garmen/orders/7/', method: 'PUT', body: toSalesOrderBody(INPUT) },
    ]);

    const removal = stubClient({ deleted: true, id: 7 });
    await deleteOrder(removal.client, 7);
    expect(removal.requests).toEqual([
      { path: '/garmen/orders/7/', method: 'DELETE', body: undefined },
    ]);

    await expect(
      deleteOrder(failingClient(400, 'hapus hanya boleh saat DRAFT.'), 7),
    ).rejects.toThrow(/DRAFT/);
  });

  it('runOrderAction: confirm tanpa body, cancel dengan reason', async () => {
    const { client, requests } = stubClient(SAVED_BODY);

    await runOrderAction(client, 7, 'confirm');
    await runOrderAction(client, 7, 'done');
    await runOrderAction(client, 7, 'cancel', '  batal klien  ');
    await runOrderAction(client, 7, 'cancel', '   ');

    expect(requests).toEqual([
      { path: '/garmen/orders/7/confirm/', method: 'POST', body: {} },
      { path: '/garmen/orders/7/done/', method: 'POST', body: {} },
      { path: '/garmen/orders/7/cancel/', method: 'POST', body: { reason: 'batal klien' } },
      { path: '/garmen/orders/7/cancel/', method: 'POST', body: {} },
    ]);

    await expect(
      runOrderAction(failingClient(400, 'Masih ada 1 WorkOrder belum selesai.'), 7, 'done'),
    ).rejects.toThrow(/WorkOrder/);
  });
});
