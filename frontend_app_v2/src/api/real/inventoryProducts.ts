// REAL - produk inventory (F2c.1). Endpoint: GET /api/v1/inventory/products/
//
// Backend `integrations/erp_sync/monitoring.py::InventoryProductsView` (B7):
//   * `IsAuthenticated` (anon 403); read-only DB (`master.Product` + stok WIP/FG).
//   * envelope ListPage `{rows, total_count, has_more, next_cursor}`
//     (paging offset: `limit` 1..200 default 50, `cursor` = offset);
//   * filter `q` (code/name icontains);
//   * baris: `{id, code, name, odoo_id, stock_qty}` (urut `code` ASC).
//
// Field lama `type`/`uom` TIDAK ada di backend -> dibuang (lihat contract-gap).
import type { ApiClient } from '@/integrations/api-client';
import type { ProductRow } from '@/types/inventory-product';
import { unwrap } from '../client';

/** Path relatif terhadap `VITE_API_BASE_URL`. */
export const INVENTORY_PRODUCTS_PATH = '/inventory/products/';

/** Batas paging backend (`monitoring.DEFAULT_LIMIT` / `MAX_LIMIT` / `MAX_OFFSET`). */
export const PRODUCTS_LIMIT_DEFAULT = 50;
export const PRODUCTS_LIMIT_MAX = 200;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function readNumber(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0;
}

function readNullableNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function readText(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

/** PURE — path + query `GET /inventory/products/` (hanya param valid yang dikirim). */
export function buildInventoryProductsPath(
  params: { q?: string | null; limit?: number | null; cursor?: number | null } = {},
): string {
  const qs = new URLSearchParams();
  const query = params.q?.trim();

  if (query) qs.set('q', query);
  if (params.limit != null) qs.set('limit', String(params.limit));
  if (params.cursor != null && params.cursor > 0) qs.set('cursor', String(params.cursor));

  const suffix = qs.toString();

  return suffix.length === 0 ? INVENTORY_PRODUCTS_PATH : `${INVENTORY_PRODUCTS_PATH}?${suffix}`;
}

/** PURE — satu baris mentah → `ProductRow`; `null` kalau tanpa `id` angka. */
export function readProductRow(raw: unknown): ProductRow | null {
  if (!isRecord(raw)) return null;

  const id = raw['id'];
  if (typeof id !== 'number' || !Number.isFinite(id)) return null;

  return {
    id,
    code: readText(raw['code']),
    name: readText(raw['name']),
    odoo_id: readNullableNumber(raw['odoo_id']),
    stock_qty: readNumber(raw['stock_qty']),
  };
}

/** PURE — semua baris valid (baris rusak dilewati). */
export function readProductRows(rows: readonly unknown[]): ProductRow[] {
  const parsed: ProductRow[] = [];

  for (const raw of rows) {
    const row = readProductRow(raw);
    if (row !== null) parsed.push(row);
  }

  return parsed;
}

/** Respons 200 `GET /inventory/products/`. */
export interface ProductPage {
  rows: ProductRow[];
  total_count: number;
  has_more: boolean;
  next_cursor: number | null;
}

/** PURE — respons mentah → `ProductPage`; `null` kalau envelope tak dikenali. */
export function readProductPage(raw: unknown): ProductPage | null {
  if (!isRecord(raw)) return null;

  const rows = raw['rows'];
  if (!Array.isArray(rows)) return null;

  return {
    rows: readProductRows(rows),
    total_count: readNumber(raw['total_count']),
    has_more: raw['has_more'] === true,
    next_cursor: readNullableNumber(raw['next_cursor']),
  };
}

/**
 * Baca daftar produk (mengembalikan `rows` saja — halaman memaginasi di klien).
 * Gagal HTTP (403 anon / 400 param) → melempar pesan backend (`unwrap`);
 * bentuk tak dikenal → melempar pesan jelas.
 */
export async function fetchProducts(
  client: ApiClient,
  params: { q?: string | null; limit?: number | null; cursor?: number | null } = {},
): Promise<ProductRow[]> {
  const res = await client.get<unknown>(buildInventoryProductsPath(params));
  const page = readProductPage(unwrap(res));

  if (page === null) {
    throw new Error('Bentuk respons daftar produk tidak dikenali.');
  }

  return page.rows;
}

export type { ProductRow } from '@/types/inventory-product';
