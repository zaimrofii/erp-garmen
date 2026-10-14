// REAL - Sales Order (H2.1). Endpoint: `/api/v1/garmen/orders/…`
//   GET|POST `/garmen/orders/`            +  GET|PUT|DELETE `/garmen/orders/<id>/`
//   POST     `/garmen/orders/<id>/confirm|done|cancel/`
//
// Bentuk baris = PERSIS `django_app/apps_industry/garment/services/order_services.py`
// (`order_row` / `order_detail_row` / `line_row`):
//   * `price_unit`/`subtotal`/`amount_total` = **string** (Decimal backend);
//   * list menambah `lines_count` + `amount_total`; detail menambah `lines[]`,
//     `work_orders_count`, `odoo_sync_status`, `allowed_actions`;
//   * POST/PUT/transisi menambah `{sync_record_id, task_id, queued}`;
//   * DELETE = **hard delete** dan hanya boleh saat `state='DRAFT'` (backend 400).
//
// `ApiClient` hanya punya `get`/`post` — PUT/DELETE lewat `client.request()`.
import type { ApiClient, ApiResponse } from '@/integrations/api-client';
import type {
  SalesOrderDetail,
  SalesOrderInput,
  SalesOrderLineInput,
  SalesOrderLineRow,
  SalesOrderRow,
  SalesOrderSaved,
} from '@/types/sales-order';
import { unwrap } from '../client';
import {
  buildQueryPath,
  getParsed,
  isRecord,
  readListPage,
  readNullableNum,
  readNullableStr,
  readNum,
  readStr,
  type ListPage,
} from './_shape';

/** Path relatif terhadap `VITE_API_BASE_URL` (`…/api/v1`). */
export const SALES_ORDERS_PATH = '/garmen/orders/';

/** Batas paging backend (`api/orders.py::DEFAULT_LIMIT` / `MAX_LIMIT`). */
export const SALES_ORDERS_LIMIT_DEFAULT = 50;
export const SALES_ORDERS_LIMIT_MAX = 200;

/** State MES yang sah (backend `order_services.ORDER_STATES`). */
export const SALES_ORDER_STATES = ['DRAFT', 'CONFIRMED', 'DONE', 'CANCELLED'] as const;

/** Aksi transisi yang dikenali backend (`api/orders.py::ORDER_ACTIONS`). */
export const SALES_ORDER_ACTIONS = ['confirm', 'done', 'cancel'] as const;

export type SalesOrderAction = (typeof SALES_ORDER_ACTIONS)[number];

export type SalesOrderPage = ListPage<SalesOrderRow>;

export interface SalesOrdersParams {
  search?: string | null;
  state?: string | null;
  customer_id?: number | null;
  limit?: number | null;
  cursor?: number | null;
}

/** URL detail satu order. */
export function salesOrderDetailPath(id: number): string {
  return `${SALES_ORDERS_PATH}${String(id)}/`;
}

/** URL aksi transisi satu order (`confirm`/`done`/`cancel`). */
export function salesOrderActionPath(id: number, action: SalesOrderAction): string {
  return `${SALES_ORDERS_PATH}${String(id)}/${action}/`;
}

/** PURE — path + query `GET /garmen/orders/` (hanya param terisi dikirim). */
export function buildSalesOrdersPath(params: SalesOrdersParams = {}): string {
  return buildQueryPath(SALES_ORDERS_PATH, {
    search: params.search,
    state: params.state,
    customer_id: params.customer_id,
    limit: params.limit,
    cursor: params.cursor,
  });
}

/** PURE — array id pajak (`tax_ids`) dari respons backend. */
export function readNumArray(value: unknown): number[] {
  if (!Array.isArray(value)) return [];

  const out: number[] = [];
  for (const item of value) {
    const parsed = readNullableNum(item);
    if (parsed !== null) out.push(parsed);
  }

  return out;
}

/** PURE — satu baris list mentah → `SalesOrderRow`; `null` kalau tanpa `id` angka. */
export function readSalesOrderRow(raw: unknown): SalesOrderRow | null {
  if (!isRecord(raw)) return null;

  const id = readNullableNum(raw['id']);
  if (id === null) return null;

  return {
    id,
    code: readStr(raw['code']),
    client_order_ref: readStr(raw['client_order_ref']),
    customer_id: readNullableNum(raw['customer_id']),
    customer_name: readNullableStr(raw['customer_name']),
    order_type: readStr(raw['order_type']),
    state: readStr(raw['state']),
    priority: readNum(raw['priority']),
    deadline: readNullableStr(raw['deadline']),
    lines_count: readNum(raw['lines_count']),
    amount_total: readStr(raw['amount_total']),
    odoo_id: readNullableNum(raw['odoo_id']),
    created_at: readNullableStr(raw['created_at']),
    updated_at: readNullableStr(raw['updated_at']),
  };
}

/** PURE — detail order mentah → `SalesOrderDetail` (dengan `lines[]`). */
export function readSalesOrderDetail(raw: unknown): SalesOrderDetail | null {
  const row = readSalesOrderRow(raw);
  if (row === null) return null;

  const source = isRecord(raw) ? raw : {};
  const lines: SalesOrderLineRow[] = [];
  const rawLines = source['lines'];
  if (Array.isArray(rawLines)) {
    for (const item of rawLines) {
      const line = readSalesOrderLineRow(item);
      if (line !== null) lines.push(line);
    }
  }

  const actions: string[] = [];
  const rawActions = source['allowed_actions'];
  if (Array.isArray(rawActions)) {
    for (const item of rawActions) {
      if (typeof item === 'string') actions.push(item);
    }
  }

  return {
    ...row,
    lines,
    work_orders_count: readNum(source['work_orders_count']),
    odoo_sync_status: readNullableStr(source['odoo_sync_status']),
    allowed_actions: actions,
  };
}

/** PURE — respons ListPage sales order. */
export function readSalesOrderPage(raw: unknown): SalesOrderPage | null {
  return readListPage<SalesOrderRow>(raw, readSalesOrderRow);
}

/** PURE — baris hasil simpan/transisi (+ info push). */
export function readSalesOrderSaved(raw: unknown): SalesOrderSaved | null {
  const detail = readSalesOrderDetail(raw);
  if (detail === null) return null;

  const extra = isRecord(raw) ? raw : {};

  return {
    ...detail,
    sync_record_id: readNullableNum(extra['sync_record_id']),
    task_id: readNullableStr(extra['task_id']),
    queued: extra['queued'] === true,
  };
}

/** PURE — satu baris form → body baris backend (trim teks). */
export function toSalesOrderLineBody(line: SalesOrderLineInput): Record<string, unknown> {
  return {
    product_id: line.product_id,
    qty: line.qty,
    price_unit: line.price_unit,
    tag: line.tag.trim(),
    tax_ids: [...line.tax_ids],
  };
}

/** PURE — input UI → body backend (trim teks; baris dipetakan satu per satu). */
export function toSalesOrderBody(input: SalesOrderInput): Record<string, unknown> {
  return {
    customer_id: input.customer_id,
    order_type: input.order_type.trim().toUpperCase(),
    priority: input.priority,
    deadline: input.deadline,
    lines: input.lines.map(toSalesOrderLineBody),
  };
}

function readSaved(res: ApiResponse<unknown>): SalesOrderSaved {
  const saved = readSalesOrderSaved(unwrap(res));
  if (saved === null) {
    throw new Error('Bentuk respons simpan Sales Order tidak dikenali.');
  }

  return saved;
}

/** Daftar order + filter (`?search=&state=&customer_id=`). */
export async function fetchSalesOrders(
  client: ApiClient,
  params: SalesOrdersParams = {},
): Promise<SalesOrderPage> {
  return getParsed(client, buildSalesOrdersPath(params), readSalesOrderPage, 'daftar Sales Order');
}

/** Detail satu order (termasuk `lines[]`). Gagal HTTP (404/403) → melempar. */
export async function fetchSalesOrder(client: ApiClient, id: number): Promise<SalesOrderDetail> {
  return getParsed(
    client,
    salesOrderDetailPath(id),
    readSalesOrderDetail,
    'detail Sales Order',
  );
}

/** Buat order (POST) — nomor `SO-<TAHUN>-<SEQ>` dibangkitkan backend (Sprint C). */
export async function createSalesOrder(
  client: ApiClient,
  input: SalesOrderInput,
): Promise<SalesOrderSaved> {
  return readSaved(await client.post<unknown>(SALES_ORDERS_PATH, toSalesOrderBody(input)));
}

/** Ubah order (PUT) — hanya boleh saat DRAFT; `lines` menggantikan seluruh baris. */
export async function updateSalesOrder(
  client: ApiClient,
  id: number,
  input: SalesOrderInput,
): Promise<SalesOrderSaved> {
  return readSaved(
    await client.request<unknown>(salesOrderDetailPath(id), {
      method: 'PUT',
      body: toSalesOrderBody(input),
    }),
  );
}

/** Hapus order (DELETE) — **hard delete** & hanya DRAFT (backend tolak selain itu). */
export async function deleteSalesOrder(client: ApiClient, id: number): Promise<void> {
  unwrap(await client.request<unknown>(salesOrderDetailPath(id), { method: 'DELETE' }));
}

/**
 * Jalankan transisi state (§14).
 *
 * `reason` hanya dipakai `cancel` (masuk metadata audit backend).
 */
export async function runSalesOrderAction(
  client: ApiClient,
  id: number,
  action: SalesOrderAction,
  reason = '',
): Promise<SalesOrderSaved> {
  const body = action === 'cancel' && reason.trim().length > 0 ? { reason: reason.trim() } : {};
  const res = await client.post<unknown>(salesOrderActionPath(id, action), body);

  return readSaved(res);
}

/** PURE — satu baris order mentah → `SalesOrderLineRow`; `null` kalau tanpa `id` angka. */
export function readSalesOrderLineRow(raw: unknown): SalesOrderLineRow | null {
  if (!isRecord(raw)) return null;

  const id = readNullableNum(raw['id']);
  if (id === null) return null;

  return {
    id,
    product_id: readNullableNum(raw['product_id']),
    product_code: readNullableStr(raw['product_code']),
    product_name: readNullableStr(raw['product_name']),
    qty: readNum(raw['qty']),
    tag: readStr(raw['tag']),
    ticket_code: readNullableStr(raw['ticket_code']),
    price_unit: readStr(raw['price_unit']),
    subtotal: readStr(raw['subtotal']),
    tax_ids: readNumArray(raw['tax_ids']),
    odoo_id: readNullableNum(raw['odoo_id']),
    created_at: readNullableStr(raw['created_at']),
    updated_at: readNullableStr(raw['updated_at']),
  };
}
