// REAL - Customer Invoice MES (H3.1). Endpoint: `/api/v1/finance/customer-invoices/`
//   GET|POST `/finance/customer-invoices/` + GET|PUT|DELETE `…/<id>/`
//   POST `…/<id>/confirm/` | `…/<id>/done/` | `…/<id>/cancel/`
//
// Pemetaan UI ↔ backend (tidak ada shape yang dikarang):
//   * envelope ListPage `{rows, total_count, has_more, next_cursor}` (paging offset);
//   * filter `?search=`, `?state=`, `?customer_id=`, `?order_id=`;
//   * baris `{id, code, order_id, order_no, customer_id, customer_name, customer_code,
//     invoice_date, due_date, state, notes, lines_count, amount_total, odoo_id, …}`;
//   * detail menambah `{lines[], odoo_sync_status, odoo_sync_error, allowed_actions}`;
//   * POST/PUT/aksi menambah `{sync_record_id, task_id, queued}` (+ `duplicate_warning`
//     pada create bila order sudah punya invoice aktif — termin/DP, tidak diblokir).
//
// ⚠️ BEDA dari F15 `/finance/invoices/` (antrean I5 read-only, amplop `has_next`):
// halaman tersebut TETAP seperti semula; adapter ini hanya untuk CRUD model MES.
//
// Catatan: `ApiClient` hanya punya `get`/`post` — PUT/DELETE lewat `client.request()`.
import type { ApiClient, ApiResponse } from '@/integrations/api-client';
import type {
  CustomerInvoiceDetail,
  CustomerInvoiceInput,
  CustomerInvoiceLineInput,
  CustomerInvoiceLineRow,
  CustomerInvoiceRow,
  CustomerInvoiceSaved,
  CustomerInvoiceState,
} from '@/types/customer-invoice';
import { unwrap } from '../client';
import {
  buildQueryPath,
  getParsed,
  isRecord,
  readBool,
  readListPage,
  readNullableNum,
  readNullableStr,
  readNum,
  readStr,
  type ListPage,
} from './_shape';

/** Path relatif terhadap `VITE_API_BASE_URL` (`…/api/v1`). */
export const CUSTOMER_INVOICES_PATH = '/finance/customer-invoices/';

/** Batas paging backend (`garment/api/customer_invoices.py::DEFAULT_LIMIT`/`MAX_LIMIT`). */
export const INVOICES_LIMIT_DEFAULT = 50;
export const INVOICES_LIMIT_MAX = 200;

/** Aksi transisi yang dikenal backend. */
export const CUSTOMER_INVOICE_ACTIONS = ['confirm', 'done', 'cancel'] as const;
export type CustomerInvoiceAction = (typeof CUSTOMER_INVOICE_ACTIONS)[number];

/** Respons 200 `GET /finance/customer-invoices/`. */
export type CustomerInvoicePage = ListPage<CustomerInvoiceRow>;

export interface CustomerInvoicesParams {
  search?: string | null;
  state?: CustomerInvoiceState | null;
  customer_id?: number | null;
  order_id?: number | null;
  limit?: number | null;
  cursor?: number | null;
}

/** PURE — path + query `GET /finance/customer-invoices/`. */
export function buildCustomerInvoicesPath(params: CustomerInvoicesParams = {}): string {
  return buildQueryPath(CUSTOMER_INVOICES_PATH, {
    search: params.search,
    state: params.state,
    customer_id: params.customer_id,
    order_id: params.order_id,
    limit: params.limit,
    cursor: params.cursor,
  });
}

/** PURE — path aksi transisi (`confirm`/`done`/`cancel`). */
export function customerInvoiceActionPath(id: number, action: CustomerInvoiceAction): string {
  return `${CUSTOMER_INVOICES_PATH}${id}/${action}/`;
}

/** PURE — state backend yang sah; lain → `DRAFT` (defensif). */
export function readCustomerInvoiceState(value: unknown): CustomerInvoiceState {
  return value === 'CONFIRMED' || value === 'SENT' || value === 'DONE' || value === 'CANCELLED'
    ? value
    : 'DRAFT';
}

/** PURE — satu baris mentah → `CustomerInvoiceRow`; `null` kalau tanpa `id` angka. */
export function readCustomerInvoiceRow(raw: unknown): CustomerInvoiceRow | null {
  if (!isRecord(raw)) return null;

  const id = raw['id'];
  if (typeof id !== 'number' || !Number.isFinite(id)) return null;

  return {
    id,
    code: readStr(raw['code']),
    order_id: readNum(raw['order_id']),
    order_no: readNullableStr(raw['order_no']),
    customer_id: readNum(raw['customer_id']),
    customer_name: readNullableStr(raw['customer_name']),
    customer_code: readNullableStr(raw['customer_code']),
    invoice_date: readNullableStr(raw['invoice_date']),
    due_date: readNullableStr(raw['due_date']),
    state: readCustomerInvoiceState(raw['state']),
    notes: readStr(raw['notes']),
    lines_count: readNum(raw['lines_count']),
    amount_total: readStr(raw['amount_total']),
    odoo_id: readNullableNum(raw['odoo_id']),
    created_at: readNullableStr(raw['created_at']),
    updated_at: readNullableStr(raw['updated_at']),
  };
}

/** PURE — satu baris invoice (nested) → `CustomerInvoiceLineRow`. */
export function readCustomerInvoiceLineRow(raw: unknown): CustomerInvoiceLineRow | null {
  if (!isRecord(raw)) return null;

  const id = raw['id'];
  if (typeof id !== 'number' || !Number.isFinite(id)) return null;

  const taxes = Array.isArray(raw['tax_ids']) ? raw['tax_ids'] : [];
  const taxOdoo = Array.isArray(raw['tax_odoo_ids']) ? raw['tax_odoo_ids'] : [];

  return {
    id,
    order_line_id: readNullableNum(raw['order_line_id']),
    product_id: readNum(raw['product_id']),
    product_code: readNullableStr(raw['product_code']),
    product_name: readNullableStr(raw['product_name']),
    qty: readStr(raw['qty']),
    price_unit: readStr(raw['price_unit']),
    subtotal: readStr(raw['subtotal']),
    tax_ids: taxes.filter((value): value is number => typeof value === 'number'),
    tax_odoo_ids: taxOdoo.filter((value): value is number => typeof value === 'number'),
    line_total: readStr(raw['line_total']),
    created_at: readNullableStr(raw['created_at']),
    updated_at: readNullableStr(raw['updated_at']),
  };
}

/** PURE — respons ListPage invoice. */
export function readCustomerInvoicePage(raw: unknown): CustomerInvoicePage | null {
  return readListPage<CustomerInvoiceRow>(raw, readCustomerInvoiceRow);
}

/** PURE — detail invoice (+ `lines[]`/info sync/aksi). */
export function readCustomerInvoiceDetail(raw: unknown): CustomerInvoiceDetail | null {
  const row = readCustomerInvoiceRow(raw);
  if (row === null || !isRecord(raw)) return null;

  const rows = Array.isArray(raw['lines']) ? raw['lines'] : [];
  const lines: CustomerInvoiceLineRow[] = [];
  for (const item of rows) {
    const line = readCustomerInvoiceLineRow(item);
    if (line !== null) lines.push(line);
  }
  const actions = Array.isArray(raw['allowed_actions']) ? raw['allowed_actions'] : [];

  return {
    ...row,
    lines,
    odoo_sync_status: readNullableStr(raw['odoo_sync_status']),
    odoo_sync_error: readNullableStr(raw['odoo_sync_error']),
    allowed_actions: actions.filter((value): value is string => typeof value === 'string'),
  };
}

/** PURE — respons simpan/aksi (+ `sync_record_id`/`task_id`/`queued`). */
export function readCustomerInvoiceSaved(raw: unknown): CustomerInvoiceSaved | null {
  const detail = readCustomerInvoiceDetail(raw);
  if (detail === null || !isRecord(raw)) return null;

  return {
    ...detail,
    sync_record_id: readNullableNum(raw['sync_record_id']),
    task_id: readNullableStr(raw['task_id']),
    queued: readBool(raw['queued']),
    duplicate_warning: readNullableStr(raw['duplicate_warning']),
  };
}

/** PURE — satu baris input → baris body (angka apa adanya, pajak = array id). */
export function toCustomerInvoiceLineBody(
  line: CustomerInvoiceLineInput,
): Record<string, unknown> {
  const body: Record<string, unknown> = {
    product_id: line.product_id,
    qty: line.qty,
    price_unit: line.price_unit,
    tax_ids: [...line.tax_ids],
  };
  if (line.order_line_id !== undefined && line.order_line_id !== null) {
    body['order_line_id'] = line.order_line_id;
  }

  return body;
}

/** PURE — input UI → body backend (angka sudah number; teks di-trim). */
export function toCustomerInvoiceBody(input: CustomerInvoiceInput): Record<string, unknown> {
  const body: Record<string, unknown> = {
    order_id: input.order_id,
    invoice_date: input.invoice_date,
  };

  if (input.customer_id !== undefined && input.customer_id !== null) {
    body['customer_id'] = input.customer_id;
  }
  if (input.due_date !== undefined && input.due_date !== null && input.due_date !== '') {
    body['due_date'] = input.due_date;
  }
  if (input.notes !== undefined) {
    body['notes'] = input.notes.trim();
  }
  if (input.lines !== undefined) {
    body['lines'] = input.lines.map((line) => toCustomerInvoiceLineBody(line));
  }

  return body;
}

function readSaved(res: ApiResponse<unknown>): CustomerInvoiceSaved {
  const saved = readCustomerInvoiceSaved(unwrap(res));
  if (saved === null) {
    throw new Error('Bentuk respons simpan invoice tidak dikenali.');
  }

  return saved;
}

/** Daftar invoice + filter (halaman memakai `next_cursor`/`has_more`). */
export async function fetchCustomerInvoices(
  client: ApiClient,
  params: CustomerInvoicesParams = {},
): Promise<CustomerInvoicePage> {
  return getParsed(
    client,
    buildCustomerInvoicesPath(params),
    readCustomerInvoicePage,
    'daftar customer invoice',
  );
}

/** Detail invoice. Gagal HTTP (404/403) → melempar pesan backend. */
export async function fetchCustomerInvoice(
  client: ApiClient,
  id: number,
): Promise<CustomerInvoiceDetail> {
  return getParsed(
    client,
    `${CUSTOMER_INVOICES_PATH}${id}/`,
    readCustomerInvoiceDetail,
    'detail customer invoice',
  );
}

/** Buat invoice (POST) — `lines` kosong = auto-fill backend dari OrderLine. */
export async function createCustomerInvoice(
  client: ApiClient,
  input: CustomerInvoiceInput,
): Promise<CustomerInvoiceSaved> {
  return readSaved(
    await client.post<unknown>(CUSTOMER_INVOICES_PATH, toCustomerInvoiceBody(input)),
  );
}

/** Ubah invoice (PUT) — DRAFT-only; `lines` (bila dikirim) mengganti seluruh baris. */
export async function updateCustomerInvoice(
  client: ApiClient,
  id: number,
  input: CustomerInvoiceInput,
): Promise<CustomerInvoiceSaved> {
  return readSaved(
    await client.request<unknown>(`${CUSTOMER_INVOICES_PATH}${id}/`, {
      method: 'PUT',
      body: toCustomerInvoiceBody(input),
    }),
  );
}

/** Hapus invoice (DELETE) — DRAFT-only (hard delete di backend). */
export async function deleteCustomerInvoice(client: ApiClient, id: number): Promise<void> {
  unwrap(await client.request<unknown>(`${CUSTOMER_INVOICES_PATH}${id}/`, { method: 'DELETE' }));
}

/** Transisi invoice (`confirm` → enqueue push, `done`, `cancel`) — POST aksi. */
export async function actCustomerInvoice(
  client: ApiClient,
  id: number,
  action: CustomerInvoiceAction,
): Promise<CustomerInvoiceSaved> {
  return readSaved(await client.post<unknown>(customerInvoiceActionPath(id, action), {}));
}
