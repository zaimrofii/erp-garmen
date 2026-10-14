// REAL - daftar PO Odoo (F2C.2). Endpoint: GET /api/v1/purchase/orders/
//
// Backend `monitoring.PurchaseOrdersView` (B10 + G5). ListPage (via Odoo transport).
import type { ApiClient } from '@/integrations/api-client';
import { unwrap } from '../client';

/** Path relatif terhadap `VITE_API_BASE_URL`. */
export const PURCHASE_ORDERS_PATH = '/purchase/orders/';

export interface PurchaseOrderLine {
  product_code: string | null;
  description: string | null;
  qty: number;
  price_unit: number;
  subtotal: number;
}

export interface PurchaseOrderRow {
  id: number | null;
  name: string | null;
  partner_name: string | null;
  state: string | null;
  /** String Odoo mentah ("YYYY-MM-DD HH:MM:SS"). */
  date_order: string | null;
  date_planned: string | null;
  amount_total: number | null;
  vendor_code: string | null;
  lines: PurchaseOrderLine[];
}

export interface PurchaseOrderPage {
  rows: PurchaseOrderRow[];
  total_count: number;
  has_more: boolean;
  next_cursor: number | null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function readNum(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0;
}

function readNullableNum(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function readNullableStr(value: unknown): string | null {
  return typeof value === 'string' ? value : null;
}

function readLines(value: unknown): PurchaseOrderLine[] {
  if (!Array.isArray(value)) return [];
  return value.filter(isRecord).map((row) => ({
    product_code: readNullableStr(row['product_code']),
    description: readNullableStr(row['description']),
    qty: readNum(row['qty']),
    price_unit: readNum(row['price_unit']),
    subtotal: readNum(row['subtotal']),
  }));
}

/** PURE — satu baris PO mentah → `PurchaseOrderRow`. */
export function readPurchaseOrderRow(raw: unknown): PurchaseOrderRow | null {
  if (!isRecord(raw)) return null;
  return {
    id: typeof raw['id'] === 'number' ? raw['id'] : null,
    name: readNullableStr(raw['name']),
    partner_name: readNullableStr(raw['partner_name']),
    state: readNullableStr(raw['state']),
    date_order: readNullableStr(raw['date_order']),
    date_planned: readNullableStr(raw['date_planned']),
    amount_total: readNullableNum(raw['amount_total']),
    vendor_code: readNullableStr(raw['vendor_code']),
    lines: readLines(raw['lines']),
  };
}

/** PURE — respons mentah → `PurchaseOrderPage`; `null` kalau `rows` bukan array. */
export function readPurchaseOrderPage(raw: unknown): PurchaseOrderPage | null {
  if (!isRecord(raw)) return null;
  const rows = raw['rows'];
  if (!Array.isArray(rows)) return null;

  const parsed: PurchaseOrderRow[] = [];
  for (const row of rows) {
    const item = readPurchaseOrderRow(row);
    if (item !== null) parsed.push(item);
  }

  return {
    rows: parsed,
    total_count: readNum(raw['total_count']),
    has_more: raw['has_more'] === true,
    next_cursor: typeof raw['next_cursor'] === 'number' ? raw['next_cursor'] : null,
  };
}

/** PURE — path + query `GET /purchase/orders/`. */
export function buildPurchaseOrdersPath(
  params: { state?: string | null; limit?: number | null; cursor?: number | null } = {},
): string {
  const qs = new URLSearchParams();
  const state = params.state?.trim();
  if (state) qs.set('state', state);
  if (params.limit != null) qs.set('limit', String(params.limit));
  if (params.cursor != null && params.cursor > 0) qs.set('cursor', String(params.cursor));
  const suffix = qs.toString();
  return suffix.length === 0 ? PURCHASE_ORDERS_PATH : `${PURCHASE_ORDERS_PATH}?${suffix}`;
}

/** Baca daftar PO (rows saja). Gagal HTTP → melempar (`unwrap`). */
export async function fetchPurchaseOrders(
  client: ApiClient,
  params: { state?: string | null; limit?: number | null; cursor?: number | null } = {},
): Promise<PurchaseOrderRow[]> {
  const res = await client.get<unknown>(buildPurchaseOrdersPath(params));
  const page = readPurchaseOrderPage(unwrap(res));

  if (page === null) {
    throw new Error('Bentuk respons daftar purchase order tidak dikenali.');
  }

  return page.rows;
}
