// REAL - Vendor Bill MES (H3.2). Endpoint: `/api/v1/finance/vendor-bills/`
//   GET|POST `/finance/vendor-bills/` + GET|PUT|DELETE `…/<id>/`
//   POST `…/<id>/confirm/` | `…/<id>/done/` | `…/<id>/cancel/`
//
// Pemetaan UI ↔ backend (tidak ada shape yang dikarang):
//   * envelope ListPage `{rows, total_count, has_more, next_cursor}` (paging offset);
//   * filter `?search=` (kode/ref/vendor/PO), `?state=`, `?vendor_id=`,
//     `?purchase_order_id=`;
//   * baris `{id, code, purchase_order_id, purchase_order_no, vendor_id, vendor_name,
//     vendor_code, ref, invoice_date, due_date, state, notes, lines_count,
//     amount_total, odoo_id, …}`;
//   * detail menambah `{lines[], odoo_sync_status, odoo_sync_error, allowed_actions}`;
//   * POST/PUT/aksi menambah `{sync_record_id, task_id, queued}` (+ `duplicate_warning`
//     pada create bila PO sudah punya bill aktif — termin/partial, tidak diblokir).
//
// ⚠️ BEDA dari I6 (tarik `fetch_vendor_bills` → `MaterialReadiness.vendor_bill_*`) dan
// dari B10 `/purchase/orders/` (monitoring Odoo read-only): keduanya TETAP seperti
// semula; adapter ini hanya untuk model MES `VendorBill`.
//
// Catatan: `ApiClient` hanya punya `get`/`post` — PUT/DELETE lewat `client.request()`.
import type { ApiClient, ApiResponse } from '@/integrations/api-client';
import type {
  VendorBillDetail,
  VendorBillInput,
  VendorBillLineInput,
  VendorBillLineRow,
  VendorBillRow,
  VendorBillSaved,
  VendorBillState,
} from '@/types/vendor-bill';
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
export const VENDOR_BILLS_PATH = '/finance/vendor-bills/';

/** Batas paging backend (`garment/api/vendor_bills.py::DEFAULT_LIMIT`/`MAX_LIMIT`). */
export const VENDOR_BILLS_LIMIT_DEFAULT = 50;
export const VENDOR_BILLS_LIMIT_MAX = 200;

/** Aksi transisi yang dikenal backend. */
export const VENDOR_BILL_ACTIONS = ['confirm', 'done', 'cancel'] as const;
export type VendorBillAction = (typeof VENDOR_BILL_ACTIONS)[number];

/** Respons 200 `GET /finance/vendor-bills/`. */
export type VendorBillPage = ListPage<VendorBillRow>;

export interface VendorBillsParams {
  search?: string | null;
  state?: VendorBillState | null;
  vendor_id?: number | null;
  purchase_order_id?: number | null;
  limit?: number | null;
  cursor?: number | null;
}

/** PURE — path + query `GET /finance/vendor-bills/`. */
export function buildVendorBillsPath(params: VendorBillsParams = {}): string {
  return buildQueryPath(VENDOR_BILLS_PATH, {
    search: params.search,
    state: params.state,
    vendor_id: params.vendor_id,
    purchase_order_id: params.purchase_order_id,
    limit: params.limit,
    cursor: params.cursor,
  });
}

/** PURE — path aksi transisi (`confirm`/`done`/`cancel`). */
export function vendorBillActionPath(id: number, action: VendorBillAction): string {
  return `${VENDOR_BILLS_PATH}${id}/${action}/`;
}

/** PURE — state backend yang sah; lain → `DRAFT` (defensif). */
export function readVendorBillState(value: unknown): VendorBillState {
  return value === 'CONFIRMED' || value === 'SENT' || value === 'DONE' || value === 'CANCELLED'
    ? value
    : 'DRAFT';
}

/** PURE — `tax_ids` mentah → array angka (id `master.Tax` MES). */
export function readTaxIds(value: unknown): number[] {
  if (!Array.isArray(value)) return [];

  const ids: number[] = [];
  for (const raw of value) {
    if (typeof raw === 'number' && Number.isFinite(raw)) ids.push(raw);
  }

  return ids;
}


/** PURE — satu baris mentah → `VendorBillLineRow`; `null` kalau tanpa `id` angka. */
export function readVendorBillLineRow(raw: unknown): VendorBillLineRow | null {
  if (!isRecord(raw)) return null;
  const id = readNullableNum(raw['id']);
  const productId = readNullableNum(raw['product_id']);
  if (id === null || productId === null) return null;

  return {
    id,
    po_line_id: readNullableNum(raw['po_line_id']),
    product_id: productId,
    product_code: readNullableStr(raw['product_code']),
    product_name: readNullableStr(raw['product_name']),
    qty: readStr(raw['qty']),
    price_unit: readStr(raw['price_unit']),
    subtotal: readStr(raw['subtotal']),
    tax_ids: readTaxIds(raw['tax_ids']),
    tax_odoo_ids: readTaxIds(raw['tax_odoo_ids']),
    line_total: readStr(raw['line_total']),
    created_at: readNullableStr(raw['created_at']),
    updated_at: readNullableStr(raw['updated_at']),
  };
}

/** PURE — satu baris mentah → `VendorBillRow`; `null` kalau tanpa `id` angka. */
export function readVendorBillRow(raw: unknown): VendorBillRow | null {
  if (!isRecord(raw)) return null;
  const id = readNullableNum(raw['id']);
  if (id === null) return null;

  return {
    id,
    code: readStr(raw['code']),
    purchase_order_id: readNullableNum(raw['purchase_order_id']),
    purchase_order_no: readNullableStr(raw['purchase_order_no']),
    vendor_id: readNum(raw['vendor_id']),
    vendor_name: readNullableStr(raw['vendor_name']),
    vendor_code: readNullableStr(raw['vendor_code']),
    ref: readStr(raw['ref']),
    invoice_date: readNullableStr(raw['invoice_date']),
    due_date: readNullableStr(raw['due_date']),
    state: readVendorBillState(raw['state']),
    notes: readStr(raw['notes']),
    lines_count: readNum(raw['lines_count']),
    amount_total: readStr(raw['amount_total']),
    odoo_id: readNullableNum(raw['odoo_id']),
    created_at: readNullableStr(raw['created_at']),
    updated_at: readNullableStr(raw['updated_at']),
  };
}

/** PURE — respons list mentah → `VendorBillPage`; `null` kalau bentuk rusak. */
export function readVendorBillPage(raw: unknown): VendorBillPage | null {
  return readListPage(raw, readVendorBillRow);
}

/** PURE — respons detail mentah → `VendorBillDetail`; `null` kalau bentuk rusak. */
export function readVendorBillDetail(raw: unknown): VendorBillDetail | null {
  const row = readVendorBillRow(raw);
  if (row === null || !isRecord(raw)) return null;

  const rawLines = raw['lines'];
  const lines: VendorBillLineRow[] = [];
  if (Array.isArray(rawLines)) {
    for (const line of rawLines) {
      const parsed = readVendorBillLineRow(line);
      if (parsed !== null) lines.push(parsed);
    }
  }

  const actions = raw['allowed_actions'];

  return {
    ...row,
    lines,
    odoo_sync_status: readNullableStr(raw['odoo_sync_status']),
    odoo_sync_error: readNullableStr(raw['odoo_sync_error']),
    allowed_actions: Array.isArray(actions) ? actions.filter((a) => typeof a === 'string') : [],
  };
}

/** PURE — respons simpan (detail + jejak push) → `VendorBillSaved`; `null` kalau rusak. */
export function readVendorBillSaved(raw: unknown): VendorBillSaved | null {
  const detail = readVendorBillDetail(raw);
  if (detail === null || !isRecord(raw)) return null;

  return {
    ...detail,
    sync_record_id: readNullableNum(raw['sync_record_id']),
    task_id: readNullableStr(raw['task_id']),
    queued: raw['queued'] === true,
    duplicate_warning: readNullableStr(raw['duplicate_warning']),
  };
}


/** PURE — satu baris body create/update (nama field backend). */
export function toVendorBillLineBody(line: VendorBillLineInput): Record<string, unknown> {
  const body: Record<string, unknown> = {
    product_id: line.product_id,
    qty: line.qty,
    price_unit: line.price_unit,
    tax_ids: [...line.tax_ids],
  };
  if (line.po_line_id !== undefined && line.po_line_id !== null) {
    body['po_line_id'] = line.po_line_id;
  }

  return body;
}

/** PURE — input UI → body backend (angka sudah number; teks di-trim). */
export function toVendorBillBody(input: VendorBillInput): Record<string, unknown> {
  const body: Record<string, unknown> = {
    vendor_id: input.vendor_id,
    invoice_date: input.invoice_date,
  };

  if (input.purchase_order_id !== undefined && input.purchase_order_id !== null) {
    body['purchase_order_id'] = input.purchase_order_id;
  }
  if (input.ref !== undefined) {
    body['ref'] = input.ref.trim();
  }
  if (input.due_date !== undefined && input.due_date !== null && input.due_date !== '') {
    body['due_date'] = input.due_date;
  }
  if (input.notes !== undefined) {
    body['notes'] = input.notes.trim();
  }
  if (input.lines !== undefined) {
    body['lines'] = input.lines.map((line) => toVendorBillLineBody(line));
  }

  return body;
}

function readSaved(res: ApiResponse<unknown>): VendorBillSaved {
  const saved = readVendorBillSaved(unwrap(res));
  if (saved === null) {
    throw new Error('Bentuk respons simpan vendor bill tidak dikenali.');
  }

  return saved;
}

/** Daftar bill + filter (halaman memakai `next_cursor`/`has_more`). */
export async function fetchVendorBills(
  client: ApiClient,
  params: VendorBillsParams = {},
): Promise<VendorBillPage> {
  return getParsed(client, buildVendorBillsPath(params), readVendorBillPage, 'daftar vendor bill');
}

/** Detail bill. Gagal HTTP (404/403) → melempar pesan backend. */
export async function fetchVendorBill(client: ApiClient, id: number): Promise<VendorBillDetail> {
  return getParsed(
    client,
    `${VENDOR_BILLS_PATH}${id}/`,
    readVendorBillDetail,
    'detail vendor bill',
  );
}

/** Buat bill (POST) — `lines` kosong + ada PO = auto-fill backend dari PO Line. */
export async function createVendorBill(
  client: ApiClient,
  input: VendorBillInput,
): Promise<VendorBillSaved> {
  return readSaved(await client.post<unknown>(VENDOR_BILLS_PATH, toVendorBillBody(input)));
}

/** Ubah bill (PUT) — DRAFT-only; `lines` (bila dikirim) mengganti seluruh baris. */
export async function updateVendorBill(
  client: ApiClient,
  id: number,
  input: VendorBillInput,
): Promise<VendorBillSaved> {
  return readSaved(
    await client.request<unknown>(`${VENDOR_BILLS_PATH}${id}/`, {
      method: 'PUT',
      body: toVendorBillBody(input),
    }),
  );
}

/** Hapus bill (DELETE) — DRAFT-only (hard delete di backend). */
export async function deleteVendorBill(client: ApiClient, id: number): Promise<void> {
  unwrap(await client.request<unknown>(`${VENDOR_BILLS_PATH}${id}/`, { method: 'DELETE' }));
}

/** Transisi bill (`confirm` → enqueue push, `done`, `cancel`) — POST aksi. */
export async function actVendorBill(
  client: ApiClient,
  id: number,
  action: VendorBillAction,
): Promise<VendorBillSaved> {
  return readSaved(await client.post<unknown>(vendorBillActionPath(id, action), {}));
}


