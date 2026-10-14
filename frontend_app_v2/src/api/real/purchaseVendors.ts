// REAL - daftar vendor/partner (F2C.2). Endpoint: GET /api/v1/purchase/vendors/
//
// Backend `monitoring.PurchaseVendorsView` (B12). ListPage.
// CATATAN: `email`/`phone`/`city` SELALU `null` (master.Partner tidak punya field itu).
import type { ApiClient } from '@/integrations/api-client';
import { unwrap } from '../client';

/** Path relatif terhadap `VITE_API_BASE_URL`. */
export const PURCHASE_VENDORS_PATH = '/purchase/vendors/';

export interface VendorRow {
  id: number;
  name: string;
  odoo_id: number | null;
  email: string | null;
  phone: string | null;
  city: string | null;
}

export interface VendorPage {
  rows: VendorRow[];
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

function readStr(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

function readNullableStr(value: unknown): string | null {
  return typeof value === 'string' ? value : null;
}

/** PURE — satu baris vendor mentah → `VendorRow`; `null` kalau tanpa `id` angka. */
export function readVendorRow(raw: unknown): VendorRow | null {
  if (!isRecord(raw)) return null;
  const id = raw['id'];
  if (typeof id !== 'number' || !Number.isFinite(id)) return null;
  return {
    id,
    name: readStr(raw['name']),
    odoo_id: typeof raw['odoo_id'] === 'number' ? raw['odoo_id'] : null,
    email: readNullableStr(raw['email']),
    phone: readNullableStr(raw['phone']),
    city: readNullableStr(raw['city']),
  };
}

/** PURE — respons mentah → `VendorPage`; `null` kalau `rows` bukan array. */
export function readVendorPage(raw: unknown): VendorPage | null {
  if (!isRecord(raw)) return null;
  const rows = raw['rows'];
  if (!Array.isArray(rows)) return null;

  const parsed: VendorRow[] = [];
  for (const row of rows) {
    const item = readVendorRow(row);
    if (item !== null) parsed.push(item);
  }

  return {
    rows: parsed,
    total_count: readNum(raw['total_count']),
    has_more: raw['has_more'] === true,
    next_cursor: typeof raw['next_cursor'] === 'number' ? raw['next_cursor'] : null,
  };
}

/** PURE — path + query `GET /purchase/vendors/`. */
export function buildPurchaseVendorsPath(
  params: { q?: string | null; limit?: number | null; cursor?: number | null } = {},
): string {
  const qs = new URLSearchParams();
  const q = params.q?.trim();
  if (q) qs.set('q', q);
  if (params.limit != null) qs.set('limit', String(params.limit));
  if (params.cursor != null && params.cursor > 0) qs.set('cursor', String(params.cursor));
  const suffix = qs.toString();
  return suffix.length === 0 ? PURCHASE_VENDORS_PATH : `${PURCHASE_VENDORS_PATH}?${suffix}`;
}

/** Baca daftar vendor (rows saja). Gagal HTTP → melempar (`unwrap`). */
export async function fetchVendors(
  client: ApiClient,
  params: { q?: string | null; limit?: number | null; cursor?: number | null } = {},
): Promise<VendorRow[]> {
  const res = await client.get<unknown>(buildPurchaseVendorsPath(params));
  const page = readVendorPage(unwrap(res));

  if (page === null) {
    throw new Error('Bentuk respons daftar vendor tidak dikenali.');
  }

  return page.rows;
}
