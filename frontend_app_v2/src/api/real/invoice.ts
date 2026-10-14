// REAL - antrean invoice (F15, revive F10). Endpoint: GET /finance/invoices/
//
// Backend `integrations/erp_sync/monitoring.py::InvoiceListView` (FASE 4.4):
//   * `IsAuthenticated` → anonim **403** (dulu 404 sebelum Fase 4.4);
//   * baris = `SyncRecord(resource="order", stage="INVOICE")` di-join ke `Order`
//     lewat `resource_id` (satu Order = satu invoice);
//   * envelope `{rows, total_count, has_next, next_cursor}` — paging offset
//     (`limit` 1..200 default 50, `cursor` = offset 0..100000);
//   * filter `state` = **status sync** (`PENDING|SENT|FAILED|DUPLICATE`, case-insensitive).
//     Kontrak docs menyebut `draft|posted` (state invoice Odoo) tetapi repo TIDAK
//     menyimpannya (`InvoiceSyncService.enqueue` hanya menyimpan `{order_id, ref}`).
//
// CATATAN kolom: brief F15 meminta `invoice_no, partner, date, amount, payment_state, ref`
// — backend TIDAK mengirim field itu. Yang tersedia: `order_id, order_no, invoice_status,
// erp_id, attempts, last_error, sent_at, created_at`. Halaman memakai field NYATA.
import type { ApiClient } from '@/integrations/api-client';
import { unwrap } from '../client';

/** Path relatif terhadap `VITE_API_BASE_URL`. */
export const INVOICES_PATH = '/finance/invoices/';

/** Batas `limit` backend (`monitoring.DEFAULT_LIMIT` / `MAX_LIMIT`). */
export const INVOICE_LIMIT_DEFAULT = 50;
export const INVOICE_LIMIT_MIN = 1;
export const INVOICE_LIMIT_MAX = 200;
/** Batas `cursor` (offset) backend. */
export const INVOICE_CURSOR_MAX = 100000;

/** Status sync yang dikenal (`SyncStatus`). */
export const INVOICE_STATUSES = ['PENDING', 'SENT', 'FAILED', 'DUPLICATE'] as const;
export type InvoiceStatus = (typeof INVOICE_STATUSES)[number];

/** Satu baris antrean invoice (`InvoiceListView`). */
export interface InvoiceRow {
  order_id: number | null;
  order_no: string | null;
  /** Status sync (`PENDING`/`SENT`/`FAILED`/`DUPLICATE`) — bukan state invoice Odoo. */
  invoice_status: string;
  erp_id: string | null;
  attempts: number;
  last_error: string | null;
  sent_at: string | null;
  created_at: string | null;
}

/** Respons 200 `GET /finance/invoices/`. */
export interface InvoicePage {
  rows: InvoiceRow[];
  total_count: number;
  has_next: boolean;
  next_cursor: number | null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function readNullableNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function readNullableString(value: unknown): string | null {
  return typeof value === 'string' ? value : null;
}

function readCount(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0;
}

/** PURE — string angka → nilai dalam rentang backend, atau `null` (invalid → JANGAN kirim). */
export function parseIntParam(value: unknown, min: number, max: number): number | null {
  if (typeof value === 'number') {
    return Number.isInteger(value) && value >= min && value <= max ? value : null;
  }

  if (typeof value !== 'string') return null;

  const trimmed = value.trim();
  if (!/^\d+$/.test(trimmed)) return null;

  const parsed = Number(trimmed);

  return parsed >= min && parsed <= max ? parsed : null;
}

/** PURE — status sync yang valid (case-insensitive), atau `null`. */
export function parseInvoiceStatus(value: unknown): InvoiceStatus | null {
  if (typeof value !== 'string') return null;

  const candidate = value.trim().toUpperCase();

  return (INVOICE_STATUSES as readonly string[]).includes(candidate)
    ? (candidate as InvoiceStatus)
    : null;
}

/** PURE — path + query `GET /finance/invoices/` (hanya parameter valid yang dikirim). */
export function buildInvoicesPath(
  params: { state?: string | null; limit?: number | null; cursor?: number | null } = {},
): string {
  const qs = new URLSearchParams();
  const state = parseInvoiceStatus(params.state);

  if (state !== null) qs.set('state', state);
  if (params.limit != null) qs.set('limit', String(params.limit));
  if (params.cursor != null && params.cursor > 0) qs.set('cursor', String(params.cursor));

  const suffix = qs.toString();

  return suffix.length === 0 ? INVOICES_PATH : `${INVOICES_PATH}?${suffix}`;
}

/** PURE — satu baris mentah → `InvoiceRow`; `null` kalau bukan objek. */
export function readInvoiceRow(raw: unknown): InvoiceRow | null {
  if (!isRecord(raw)) return null;

  return {
    order_id: readNullableNumber(raw['order_id']),
    order_no: readNullableString(raw['order_no']),
    invoice_status: readNullableString(raw['invoice_status']) ?? '',
    erp_id: readNullableString(raw['erp_id']),
    attempts: readCount(raw['attempts']),
    last_error: readNullableString(raw['last_error']),
    sent_at: readNullableString(raw['sent_at']),
    created_at: readNullableString(raw['created_at']),
  };
}

/**
 * PURE — respons mentah → `InvoicePage`; `null` kalau envelope tidak dikenali.
 * Menerima `has_next` (backend monitoring) maupun `has_more` (kontrak list lama).
 */
export function readInvoicePage(raw: unknown): InvoicePage | null {
  if (!isRecord(raw)) return null;

  const list = raw['rows'];
  if (!Array.isArray(list)) return null;

  const parsed: InvoiceRow[] = [];
  for (const item of list) {
    const row = readInvoiceRow(item);
    if (row !== null) parsed.push(row);
  }

  return {
    rows: parsed,
    total_count: readCount(raw['total_count']),
    has_next: raw['has_next'] === true || raw['has_more'] === true,
    next_cursor: readNullableNumber(raw['next_cursor']),
  };
}

/**
 * Baca antrean invoice. Gagal HTTP (403 tanpa session / 400 param invalid) → melempar
 * pesan backend (`unwrap`); bentuk tak dikenal → melempar pesan jelas.
 */
export async function getInvoices(
  client: ApiClient,
  params: { state?: string | null; limit?: number | null; cursor?: number | null } = {},
): Promise<InvoicePage> {
  const res = await client.get<unknown>(buildInvoicesPath(params));
  const parsed = readInvoicePage(unwrap(res));

  if (parsed === null) {
    throw new Error('Bentuk respons antrean invoice tidak dikenali.');
  }

  return parsed;
}
