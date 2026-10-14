// REAL - Payment MES (H3.3). Endpoint: `/api/v1/finance/payments/`
//   GET|POST `/finance/payments/` + GET|PUT|DELETE `…/<id>/`
//   POST `…/<id>/confirm/` | `…/<id>/done/` | `…/<id>/cancel/`
//
// Pemetaan UI ↔ backend (tidak ada shape yang dikarang):
//   * envelope ListPage `{rows, total_count, has_more, next_cursor}` (paging offset);
//   * filter `?search=` (kode/referensi/nama partner/kode sumber), `?state=`,
//     `?payment_type=`, `?partner_id=`, `?customer_invoice_id=`, `?vendor_bill_id=`;
//   * baris `{id, code, payment_type, partner_id, partner_name, partner_code,
//     customer_invoice_id, customer_invoice_code, vendor_bill_id, vendor_bill_code,
//     source_type, source_label, amount, currency, payment_date, payment_method,
//     reference, memo, state, odoo_id, …}`;
//   * detail menambah `{odoo_sync_status, odoo_sync_error, allowed_actions,
//     source_amount_total, source_remaining_amount}`;
//   * POST/PUT/aksi menambah `{sync_record_id, task_id, queued}`.
//
// ⚠️ RECONCILE TIDAK ADA di MES (keputusan STEP 0): payment dibuat **draft** di Odoo
// dan akuntan yang mem-posting + merekonsiliasi. Odoo = source of truth untuk
// `payment_state`/`paid_amount` invoice/bill.
//
// Catatan: `ApiClient` hanya punya `get`/`post` — PUT/DELETE lewat `client.request()`.
import type { ApiClient, ApiResponse } from '@/integrations/api-client';
import type {
  PaymentDetail,
  PaymentInput,
  PaymentMethod,
  PaymentRow,
  PaymentSaved,
  PaymentSourceType,
  PaymentState,
  PaymentType,
} from '@/types/payment';
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
export const PAYMENTS_PATH = '/finance/payments/';

/** Batas paging backend (`garment/api/payments.py::DEFAULT_LIMIT`/`MAX_LIMIT`). */
export const PAYMENTS_LIMIT_DEFAULT = 50;
export const PAYMENTS_LIMIT_MAX = 200;

/** Aksi transisi yang dikenal backend. */
export const PAYMENT_ACTIONS = ['confirm', 'done', 'cancel'] as const;
export type PaymentAction = (typeof PAYMENT_ACTIONS)[number];

/** Respons 200 `GET /finance/payments/`. */
export type PaymentPage = ListPage<PaymentRow>;

export interface PaymentsParams {
  search?: string | null;
  state?: PaymentState | null;
  payment_type?: PaymentType | null;
  partner_id?: number | null;
  customer_invoice_id?: number | null;
  vendor_bill_id?: number | null;
  limit?: number | null;
  cursor?: number | null;
}

/** PURE — path + query `GET /finance/payments/`. */
export function buildPaymentsPath(params: PaymentsParams = {}): string {
  return buildQueryPath(PAYMENTS_PATH, {
    search: params.search,
    state: params.state,
    payment_type: params.payment_type,
    partner_id: params.partner_id,
    customer_invoice_id: params.customer_invoice_id,
    vendor_bill_id: params.vendor_bill_id,
    limit: params.limit,
    cursor: params.cursor,
  });
}

/** PURE — path aksi transisi (`confirm`/`done`/`cancel`). */
export function paymentActionPath(id: number, action: PaymentAction): string {
  return `${PAYMENTS_PATH}${id}/${action}/`;
}

/** PURE — state backend yang sah; lain → `DRAFT` (defensif). */
export function readPaymentState(value: unknown): PaymentState {
  return value === 'CONFIRMED' || value === 'SENT' || value === 'DONE' || value === 'CANCELLED'
    ? value
    : 'DRAFT';
}

/** PURE — arah bayar backend yang sah; lain → `INBOUND` (defensif). */
export function readPaymentType(value: unknown): PaymentType {
  return value === 'OUTBOUND' ? 'OUTBOUND' : 'INBOUND';
}

/** PURE — cara bayar backend yang sah; lain → `manual` (defensif). */
export function readPaymentMethod(value: unknown): PaymentMethod {
  return value === 'bank' || value === 'cash' ? value : 'manual';
}

/** PURE — jenis sumber backend yang sah; lain → `UNKNOWN`. */
export function readPaymentSourceType(value: unknown): PaymentSourceType {
  if (value === 'CUSTOMER_INVOICE' || value === 'VENDOR_BILL') return value;

  return 'UNKNOWN';
}


/** PURE — satu baris mentah → `PaymentRow`; `null` kalau tanpa `id` angka. */
export function readPaymentRow(raw: unknown): PaymentRow | null {
  if (!isRecord(raw)) return null;
  const id = readNullableNum(raw['id']);
  if (id === null) return null;

  return {
    id,
    code: readStr(raw['code']),
    payment_type: readPaymentType(raw['payment_type']),
    partner_id: readNum(raw['partner_id']),
    partner_name: readNullableStr(raw['partner_name']),
    partner_code: readNullableStr(raw['partner_code']),
    customer_invoice_id: readNullableNum(raw['customer_invoice_id']),
    customer_invoice_code: readNullableStr(raw['customer_invoice_code']),
    vendor_bill_id: readNullableNum(raw['vendor_bill_id']),
    vendor_bill_code: readNullableStr(raw['vendor_bill_code']),
    source_type: readPaymentSourceType(raw['source_type']),
    source_label: readStr(raw['source_label']),
    amount: readStr(raw['amount']),
    currency: readStr(raw['currency']),
    payment_date: readNullableStr(raw['payment_date']),
    payment_method: readPaymentMethod(raw['payment_method']),
    reference: readStr(raw['reference']),
    memo: readStr(raw['memo']),
    state: readPaymentState(raw['state']),
    odoo_id: readNullableNum(raw['odoo_id']),
    created_at: readNullableStr(raw['created_at']),
    updated_at: readNullableStr(raw['updated_at']),
  };
}

/** PURE — respons list mentah → `PaymentPage`; `null` kalau bentuk rusak. */
export function readPaymentPage(raw: unknown): PaymentPage | null {
  return readListPage(raw, readPaymentRow);
}

/** PURE — respons detail mentah → `PaymentDetail`; `null` kalau bentuk rusak. */
export function readPaymentDetail(raw: unknown): PaymentDetail | null {
  const row = readPaymentRow(raw);
  if (row === null || !isRecord(raw)) return null;

  const actions = raw['allowed_actions'];

  return {
    ...row,
    odoo_sync_status: readNullableStr(raw['odoo_sync_status']),
    odoo_sync_error: readNullableStr(raw['odoo_sync_error']),
    allowed_actions: Array.isArray(actions) ? actions.filter((a) => typeof a === 'string') : [],
    source_amount_total: readNullableStr(raw['source_amount_total']),
    source_remaining_amount: readNullableStr(raw['source_remaining_amount']),
  };
}

/** PURE — respons simpan (detail + jejak push) → `PaymentSaved`; `null` kalau rusak. */
export function readPaymentSaved(raw: unknown): PaymentSaved | null {
  const detail = readPaymentDetail(raw);
  if (detail === null || !isRecord(raw)) return null;

  return {
    ...detail,
    sync_record_id: readNullableNum(raw['sync_record_id']),
    task_id: readNullableStr(raw['task_id']),
    queued: raw['queued'] === true,
  };
}


/** PURE — input UI → body backend (angka sudah number; teks di-trim). */
export function toPaymentBody(input: PaymentInput): Record<string, unknown> {
  const body: Record<string, unknown> = {
    payment_type: input.payment_type,
    amount: input.amount,
    payment_date: input.payment_date,
  };

  if (input.payment_type === 'INBOUND') {
    if (input.customer_invoice_id !== undefined && input.customer_invoice_id !== null) {
      body['customer_invoice_id'] = input.customer_invoice_id;
    }
  } else if (input.vendor_bill_id !== undefined && input.vendor_bill_id !== null) {
    body['vendor_bill_id'] = input.vendor_bill_id;
  }

  if (input.partner_id !== undefined && input.partner_id !== null) {
    body['partner_id'] = input.partner_id;
  }
  if (input.currency !== undefined && input.currency !== '') {
    body['currency'] = input.currency.trim().toUpperCase();
  }
  if (input.payment_method !== undefined) {
    body['payment_method'] = input.payment_method;
  }
  if (input.reference !== undefined) {
    body['reference'] = input.reference.trim();
  }
  if (input.memo !== undefined) {
    body['memo'] = input.memo.trim();
  }
  if (input.notes !== undefined) {
    body['notes'] = input.notes;
  }

  return body;
}

function readSaved(res: ApiResponse<unknown>): PaymentSaved {
  const saved = readPaymentSaved(unwrap(res));
  if (saved === null) {
    throw new Error('Bentuk respons simpan payment tidak dikenali.');
  }

  return saved;
}

/** Daftar payment + filter (halaman memakai `next_cursor`/`has_more`). */
export async function fetchPayments(
  client: ApiClient,
  params: PaymentsParams = {},
): Promise<PaymentPage> {
  return getParsed(client, buildPaymentsPath(params), readPaymentPage, 'daftar payment');
}

/** Detail payment. Gagal HTTP (404/403) → melempar pesan backend. */
export async function fetchPayment(client: ApiClient, id: number): Promise<PaymentDetail> {
  return getParsed(client, `${PAYMENTS_PATH}${id}/`, readPaymentDetail, 'detail payment');
}

/** Buat payment (POST) — tepat satu sumber; guard anti-overpay di backend. */
export async function createPayment(client: ApiClient, input: PaymentInput): Promise<PaymentSaved> {
  return readSaved(await client.post<unknown>(PAYMENTS_PATH, toPaymentBody(input)));
}

/** Ubah payment (PUT) — DRAFT-only. */
export async function updatePayment(
  client: ApiClient,
  id: number,
  input: PaymentInput,
): Promise<PaymentSaved> {
  return readSaved(
    await client.request<unknown>(`${PAYMENTS_PATH}${id}/`, {
      method: 'PUT',
      body: toPaymentBody(input),
    }),
  );
}

/** Hapus payment (DELETE) — DRAFT-only (hard delete di backend). */
export async function deletePayment(client: ApiClient, id: number): Promise<void> {
  unwrap(await client.request<unknown>(`${PAYMENTS_PATH}${id}/`, { method: 'DELETE' }));
}

/** Transisi payment (`confirm` → enqueue push, `done`, `cancel`) — POST aksi. */
export async function actPayment(
  client: ApiClient,
  id: number,
  action: PaymentAction,
): Promise<PaymentSaved> {
  return readSaved(await client.post<unknown>(paymentActionPath(id, action), {}));
}


