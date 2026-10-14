// REAL - Purchase Order MES (H2.2). Endpoint: `/api/v1/garmen/purchase-orders/…`
//   GET|POST `/garmen/purchase-orders/`            +  GET|PUT|DELETE `/<id>/`
//   POST     `/<id>/confirm|done|cancel/`  +  POST `/<id>/sync-odoo-state/` (read-only)
//
// Bentuk baris = PERSIS `django_app/apps_industry/garment/services/purchase_order_services.py`
// (`purchase_order_row`/`purchase_order_detail_row`/`purchase_order_line_row`):
//   * `qty`/`price_unit`/`subtotal`/`amount_total` = **string** (Decimal, 2 desimal);
//   * detail menambah `lines[]`, `odoo_sync_status`, `allowed_actions`;
//   * POST/PUT/transisi menambah `{sync_record_id, task_id, queued}`;
//   * DELETE = **hard delete** & hanya saat `state='DRAFT'` (backend 400).
//
// CATATAN: ini BUKAN B10 (`real/purchaseOrders.ts`, monitoring read-only dari Odoo) —
// path-nya `/garmen/purchase-orders/` supaya tidak bentrok dengan `/purchase/orders/`.
//
// `ApiClient` hanya punya `get`/`post` — PUT/DELETE lewat `client.request()`.
import type { ApiClient, ApiResponse } from '@/integrations/api-client';
import type {
  PurchaseOrderMesDetail,
  PurchaseOrderMesInput,
  PurchaseOrderMesLineInput,
  PurchaseOrderMesLineRow,
  PurchaseOrderMesRow,
  PurchaseOrderMesSaved,
  PurchaseOrderOdooState,
} from '@/types/purchase-order';
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
export const PURCHASE_ORDERS_MES_PATH = '/garmen/purchase-orders/';

/** Batas paging backend (`api/purchase_orders.py::DEFAULT_LIMIT` / `MAX_LIMIT`). */
export const PURCHASE_ORDERS_MES_LIMIT_DEFAULT = 50;
export const PURCHASE_ORDERS_MES_LIMIT_MAX = 200;

/** State PO MES yang sah (backend `purchase_order_services.PO_STATES`). */
export const PURCHASE_ORDER_MES_STATES = ['DRAFT', 'CONFIRMED', 'DONE', 'CANCELLED'] as const;

/** Aksi transisi yang dikenali backend (`api/purchase_orders.py::PURCHASE_ORDER_ACTIONS`). */
export const PURCHASE_ORDER_MES_ACTIONS = ['confirm', 'done', 'cancel'] as const;

export type PurchaseOrderMesAction = (typeof PURCHASE_ORDER_MES_ACTIONS)[number];

export type PurchaseOrderMesPage = ListPage<PurchaseOrderMesRow>;

export interface PurchaseOrdersMesParams {
  search?: string | null;
  state?: string | null;
  vendor_id?: number | null;
  limit?: number | null;
  cursor?: number | null;
}

/** URL detail satu PO. */
export function purchaseOrderMesDetailPath(id: number): string {
  return `${PURCHASE_ORDERS_MES_PATH}${String(id)}/`;
}

/** URL aksi transisi satu PO (`confirm`/`done`/`cancel`). */
export function purchaseOrderMesActionPath(id: number, action: PurchaseOrderMesAction): string {
  return `${PURCHASE_ORDERS_MES_PATH}${String(id)}/${action}/`;
}

/** URL baca state Odoo (read-only) satu PO. */
export function purchaseOrderMesSyncStatePath(id: number): string {
  return `${PURCHASE_ORDERS_MES_PATH}${String(id)}/sync-odoo-state/`;
}

/** PURE — path + query `GET /garmen/purchase-orders/` (hanya param terisi dikirim). */
export function buildPurchaseOrdersMesPath(params: PurchaseOrdersMesParams = {}): string {
  return buildQueryPath(PURCHASE_ORDERS_MES_PATH, {
    search: params.search,
    state: params.state,
    vendor_id: params.vendor_id,
    limit: params.limit,
    cursor: params.cursor,
  });
}

/** PURE — array id pajak (`tax_ids`) dari respons backend. */
export function readPurchaseOrderTaxIds(value: unknown): number[] {
  if (!Array.isArray(value)) return [];

  const out: number[] = [];
  for (const item of value) {
    const parsed = readNullableNum(item);
    if (parsed !== null) out.push(parsed);
  }

  return out;
}

/** PURE — satu baris list mentah → `PurchaseOrderMesRow`; `null` kalau tanpa `id`. */
export function readPurchaseOrderMesRow(raw: unknown): PurchaseOrderMesRow | null {
  if (!isRecord(raw)) return null;

  const id = readNullableNum(raw['id']);
  if (id === null) return null;

  return {
    id,
    code: readStr(raw['code']),
    partner_ref: readStr(raw['partner_ref']),
    vendor_id: readNullableNum(raw['vendor_id']),
    vendor_name: readNullableStr(raw['vendor_name']),
    vendor_code: readNullableStr(raw['vendor_code']),
    state: readStr(raw['state']),
    expected_date: readNullableStr(raw['expected_date']),
    notes: readStr(raw['notes']),
    lines_count: readNum(raw['lines_count']),
    amount_total: readStr(raw['amount_total']),
    odoo_id: readNullableNum(raw['odoo_id']),
    created_at: readNullableStr(raw['created_at']),
    updated_at: readNullableStr(raw['updated_at']),
  };
}

export function readPurchaseOrderMesLineRow(raw: unknown): PurchaseOrderMesLineRow | null {
  if (!isRecord(raw)) return null;

  const id = readNullableNum(raw['id']);
  if (id === null) return null;

  return {
    id,
    product_id: readNullableNum(raw['product_id']),
    product_code: readNullableStr(raw['product_code']),
    product_name: readNullableStr(raw['product_name']),
    qty: readStr(raw['qty']),
    price_unit: readStr(raw['price_unit']),
    subtotal: readStr(raw['subtotal']),
    tax_ids: readPurchaseOrderTaxIds(raw['tax_ids']),
    date_planned: readNullableStr(raw['date_planned']),
    odoo_id: readNullableNum(raw['odoo_id']),
    created_at: readNullableStr(raw['created_at']),
    updated_at: readNullableStr(raw['updated_at']),
  };
}

/** PURE — detail PO mentah → `PurchaseOrderMesDetail` (dengan `lines[]`). */
export function readPurchaseOrderMesDetail(raw: unknown): PurchaseOrderMesDetail | null {
  const row = readPurchaseOrderMesRow(raw);
  if (row === null) return null;

  const source = isRecord(raw) ? raw : {};
  const lines: PurchaseOrderMesLineRow[] = [];
  const rawLines = source['lines'];
  if (Array.isArray(rawLines)) {
    for (const item of rawLines) {
      const line = readPurchaseOrderMesLineRow(item);
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
    odoo_sync_status: readNullableStr(source['odoo_sync_status']),
    allowed_actions: actions,
  };
}

/** PURE — respons ListPage PO MES. */
export function readPurchaseOrderMesPage(raw: unknown): PurchaseOrderMesPage | null {
  return readListPage<PurchaseOrderMesRow>(raw, readPurchaseOrderMesRow);
}

/** PURE — baris hasil simpan/transisi (+ info push). */
export function readPurchaseOrderMesSaved(raw: unknown): PurchaseOrderMesSaved | null {
  const detail = readPurchaseOrderMesDetail(raw);
  if (detail === null) return null;

  const extra = isRecord(raw) ? raw : {};

  return {
    ...detail,
    sync_record_id: readNullableNum(extra['sync_record_id']),
    task_id: readNullableStr(extra['task_id']),
    queued: extra['queued'] === true,
  };
}

/** PURE — respons `sync-odoo-state` (`{odoo_id, odoo_state, odoo_name}`). */
export function readPurchaseOrderOdooState(raw: unknown): PurchaseOrderOdooState | null {
  if (!isRecord(raw)) return null;

  const odooId = readNullableNum(raw['odoo_id']);
  if (odooId === null) return null;

  return {
    odoo_id: odooId,
    odoo_state: readNullableStr(raw['odoo_state']),
    odoo_name: readNullableStr(raw['odoo_name']),
  };
}


function readSaved(res: ApiResponse<unknown>): PurchaseOrderMesSaved {
  const saved = readPurchaseOrderMesSaved(unwrap(res));
  if (saved === null) {
    throw new Error('Bentuk respons simpan Purchase Order tidak dikenali.');
  }

  return saved;
}

/** Daftar PO MES + filter (`?search=&state=&vendor_id=`). */
export async function fetchPurchaseOrdersMes(
  client: ApiClient,
  params: PurchaseOrdersMesParams = {},
): Promise<PurchaseOrderMesPage> {
  return getParsed(
    client,
    buildPurchaseOrdersMesPath(params),
    readPurchaseOrderMesPage,
    'daftar Purchase Order',
  );
}

/** Detail satu PO MES (termasuk `lines[]`). Gagal HTTP (404/403) → melempar. */
export async function fetchPurchaseOrderMes(
  client: ApiClient,
  id: number,
): Promise<PurchaseOrderMesDetail> {
  return getParsed(
    client,
    purchaseOrderMesDetailPath(id),
    readPurchaseOrderMesDetail,
    'detail Purchase Order',
  );
}

/** Buat PO (POST) — nomor `PO-<TAHUN>-<SEQ>` dibangkitkan backend (Sprint C). */
export async function createPurchaseOrderMes(
  client: ApiClient,
  input: PurchaseOrderMesInput,
): Promise<PurchaseOrderMesSaved> {
  return readSaved(
    await client.post<unknown>(PURCHASE_ORDERS_MES_PATH, toPurchaseOrderMesBody(input)),
  );
}

/** Ubah PO (PUT) — hanya boleh saat DRAFT; `lines` menggantikan seluruh baris. */
export async function updatePurchaseOrderMes(
  client: ApiClient,
  id: number,
  input: PurchaseOrderMesInput,
): Promise<PurchaseOrderMesSaved> {
  return readSaved(
    await client.request<unknown>(purchaseOrderMesDetailPath(id), {
      method: 'PUT',
      body: toPurchaseOrderMesBody(input),
    }),
  );
}

/** Hapus PO (DELETE) — **hard delete** & hanya DRAFT (backend tolak selain itu). */
export async function deletePurchaseOrderMes(client: ApiClient, id: number): Promise<void> {
  unwrap(await client.request<unknown>(purchaseOrderMesDetailPath(id), { method: 'DELETE' }));
}

/**
 * Jalankan transisi state (§14).
 *
 * `reason` hanya dipakai `cancel` (masuk metadata audit backend).
 */
export async function runPurchaseOrderMesAction(
  client: ApiClient,
  id: number,
  action: PurchaseOrderMesAction,
  reason = '',
): Promise<PurchaseOrderMesSaved> {
  const body = action === 'cancel' && reason.trim().length > 0 ? { reason: reason.trim() } : {};
  const res = await client.post<unknown>(purchaseOrderMesActionPath(id, action), body);

  return readSaved(res);
}

/**
 * Baca state PO di Odoo **on-demand** (read-only, tidak mengubah data MES).
 *
 * Dipakai untuk memastikan purchasing sudah men-*confirm* PO di UI Odoo — syarat agar
 * PO ikut dihitung `material_readiness` (I3 hanya membaca state `purchase`/`done`).
 */
export async function fetchPurchaseOrderOdooState(
  client: ApiClient,
  id: number,
): Promise<PurchaseOrderOdooState> {
  const state = readPurchaseOrderOdooState(
    unwrap(await client.post<unknown>(purchaseOrderMesSyncStatePath(id), {})),
  );
  if (state === null) {
    throw new Error('Bentuk respons sync state Odoo tidak dikenali.');
  }

  return state;
}

/** PURE — satu baris form → body baris backend (trim teks). */
export function toPurchaseOrderMesLineBody(
  line: PurchaseOrderMesLineInput,
): Record<string, unknown> {
  return {
    product_id: line.product_id,
    qty: line.qty,
    price_unit: line.price_unit,
    tax_ids: [...line.tax_ids],
    date_planned: line.date_planned,
  };
}

/** PURE — input UI → body backend (trim teks; baris dipetakan satu per satu). */
export function toPurchaseOrderMesBody(input: PurchaseOrderMesInput): Record<string, unknown> {
  return {
    vendor_id: input.vendor_id,
    expected_date: input.expected_date,
    notes: input.notes.trim(),
    lines: input.lines.map(toPurchaseOrderMesLineBody),
  };
}

