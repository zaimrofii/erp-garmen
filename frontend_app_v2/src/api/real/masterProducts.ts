// REAL - master produk (H1.1). Endpoint: `/api/v1/master/products/`
//   GET|POST `/master/products/`  +  GET|PUT|DELETE `/master/products/<id>/`
//
// Pemetaan UI ↔ backend (tidak ada shape yang dikarang):
//   * envelope ListPage `{rows, total_count, has_more, next_cursor}` (paging offset:
//     `limit` 1..200 default 50, `cursor` = offset);
//   * filter `?search=` (code/name/category icontains), `?category=` (icontains),
//     `?active=true|false`; urut `code` ASC;
//   * baris `{id, code, name, category, uom_id, uom_code, sale_price, cost_price,
//     weight, image_url, active, odoo_id, created_at, updated_at}` — `active` adalah
//     nama publik `Product.is_active`, `odoo_id` = kunci sync (null = belum push);
//   * POST/PUT menambah `{sync_record_id, task_id, queued}` (push Odoo async);
//   * **DELETE = soft delete** (`active=False`; baris tetap ada, 200 + `{deleted:true}`).
//
// Catatan: `ApiClient` hanya punya `get`/`post` — PUT/DELETE lewat `client.request()`.
import type { ApiClient, ApiResponse } from '@/integrations/api-client';
import type {
  MasterProductInput,
  MasterProductPriceHistoryPage,
  MasterProductPriceHistoryRow,
  MasterProductPriceInput,
  MasterProductRow,
  MasterProductSaved,
} from '@/types/master-product';
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
export const MASTER_PRODUCTS_PATH = '/master/products/';

/** Batas paging backend (`master/api.py::DEFAULT_LIMIT` / `MAX_LIMIT`). */
export const PRODUCTS_LIMIT_DEFAULT = 50;
export const PRODUCTS_LIMIT_MAX = 200;

/** Respons 200 `GET /master/products/`. */
export type MasterProductPage = ListPage<MasterProductRow>;

export interface MasterProductsParams {
  search?: string | null;
  category?: string | null;
  /** `null`/`undefined` = tidak difilter (backend hanya memfilter kalau param dikirim). */
  active?: boolean | null;
  limit?: number | null;
  cursor?: number | null;
}

/** PURE — path + query `GET /master/products/` (hanya param terisi yang dikirim). */
export function buildMasterProductsPath(params: MasterProductsParams = {}): string {
  return buildQueryPath(MASTER_PRODUCTS_PATH, {
    search: params.search,
    category: params.category,
    active: params.active === null || params.active === undefined ? null : params.active,
    limit: params.limit,
    cursor: params.cursor,
  });
}

/** PURE — satu baris mentah → `MasterProductRow`; `null` kalau tanpa `id` angka. */
export function readMasterProductRow(raw: unknown): MasterProductRow | null {
  if (!isRecord(raw)) return null;

  const id = raw['id'];
  if (typeof id !== 'number' || !Number.isFinite(id)) return null;

  return {
    id,
    code: readStr(raw['code']),
    name: readStr(raw['name']),
    category: readStr(raw['category']),
    uom_id: readNullableNum(raw['uom_id']),
    uom_code: readNullableStr(raw['uom_code']),
    sale_price: readNum(raw['sale_price']),
    cost_price: readNum(raw['cost_price']),
    price_updated_at: readNullableStr(raw['price_updated_at']),
    weight: readNullableNum(raw['weight']),
    image_url: readStr(raw['image_url']),
    active: readBool(raw['active']),
    odoo_id: readNullableNum(raw['odoo_id']),
    created_at: readNullableStr(raw['created_at']),
    updated_at: readNullableStr(raw['updated_at']),
  };
}

/** PURE — respons ListPage master produk. */
export function readMasterProductPage(raw: unknown): MasterProductPage | null {
  return readListPage<MasterProductRow>(raw, readMasterProductRow);
}

/** PURE — baris hasil simpan (+ info sinkronisasi H1.1). */
export function readMasterProductSaved(raw: unknown): MasterProductSaved | null {
  const row = readMasterProductRow(raw);
  if (row === null) return null;

  const extra = isRecord(raw) ? raw : {};

  return {
    ...row,
    sync_record_id: readNullableNum(extra['sync_record_id']),
    task_id: readNullableStr(extra['task_id']),
    queued: readBool(extra['queued']),
  };
}

/** PURE — input UI → body backend (`active` & `uom_id` apa adanya). */
export function toMasterProductBody(input: MasterProductInput): Record<string, unknown> {
  return {
    code: input.code.trim(),
    name: input.name.trim(),
    category: input.category.trim(),
    uom_id: input.uom_id,
    sale_price: input.sale_price,
    cost_price: input.cost_price,
    weight: input.weight,
    image_url: input.image_url.trim(),
    active: input.active,
  };
}

// ---------------------------------------------------------------------------
// H3.5 — harga produk: update khusus + riwayat (audit trail)
// ---------------------------------------------------------------------------
/** PURE — URL `PUT /master/products/<id>/price/`. */
export function masterProductPricePath(id: number): string {
  return `${MASTER_PRODUCTS_PATH}${String(id)}/price/`;
}

/** PURE — URL `GET /master/products/<id>/price-history/`. */
export function masterProductPriceHistoryPath(id: number): string {
  return `${MASTER_PRODUCTS_PATH}${String(id)}/price-history/`;
}

/** PURE — path + query riwayat harga (`limit`/`cursor` = offset). */
export function buildPriceHistoryPath(
  id: number,
  params: { limit?: number | null; cursor?: number | null } = {},
): string {
  return buildQueryPath(masterProductPriceHistoryPath(id), {
    limit: params.limit,
    cursor: params.cursor,
  });
}

/** PURE — input harga UI → body backend (hanya field yang dikirim). */
export function toMasterProductPriceBody(input: MasterProductPriceInput): Record<string, unknown> {
  const body: Record<string, unknown> = {};
  if (input.sale_price !== undefined) body['sale_price'] = input.sale_price;
  if (input.cost_price !== undefined) body['cost_price'] = input.cost_price;

  return body;
}

/** PURE — peta `{field: nilai}` dari metadata audit (defensif). */
function readPriceMap(raw: unknown): Record<string, string> {
  if (!isRecord(raw)) return {};
  const out: Record<string, string> = {};
  for (const [field, value] of Object.entries(raw)) {
    out[field] = typeof value === 'string' ? value : String(value ?? '');
  }

  return out;
}

/** PURE — satu baris riwayat harga; `null` kalau `id` tidak valid. */
export function readPriceHistoryRow(raw: unknown): MasterProductPriceHistoryRow | null {
  if (!isRecord(raw)) return null;
  const id = readNullableNum(raw['id']);
  if (id === null) return null;

  const fields = Array.isArray(raw['fields'])
    ? raw['fields'].map((value) => String(value))
    : [];

  return {
    id,
    action: readStr(raw['action']),
    source: readStr(raw['source']),
    fields,
    before: readPriceMap(raw['before']),
    after: readPriceMap(raw['after']),
    user: readNullableStr(raw['user']),
    timestamp: readNullableStr(raw['timestamp']),
    request_id: readStr(raw['request_id']),
  };
}

/** PURE — respons riwayat harga (envelope §3). */
export function readPriceHistoryPage(raw: unknown): MasterProductPriceHistoryPage | null {
  return readListPage<MasterProductPriceHistoryRow>(raw, readPriceHistoryRow);
}

/** H3.5 — ubah harga produk (sale/cost) lewat endpoint khusus + audit trail. */
export async function updateProductPrice(
  client: ApiClient,
  id: number,
  input: MasterProductPriceInput,
): Promise<MasterProductSaved> {
  return readSaved(
    await client.request<unknown>(masterProductPricePath(id), {
      method: 'PUT',
      body: toMasterProductPriceBody(input),
    }),
  );
}

/** H3.5 — riwayat perubahan harga produk (dibaca dari AuditLog backend). */
export async function fetchProductPriceHistory(
  client: ApiClient,
  id: number,
  params: { limit?: number | null; cursor?: number | null } = {},
): Promise<MasterProductPriceHistoryPage> {
  return getParsed(
    client,
    buildPriceHistoryPath(id, params),
    readPriceHistoryPage,
    'riwayat harga produk',
  );
}

function readSaved(res: ApiResponse<unknown>): MasterProductSaved {
  const saved = readMasterProductSaved(unwrap(res));
  if (saved === null) {
    throw new Error('Bentuk respons simpan produk tidak dikenali.');
  }

  return saved;
}

/** Daftar produk + filter (halaman memakai `next_cursor`/`has_more` untuk paging). */
export async function fetchProducts(
  client: ApiClient,
  params: MasterProductsParams = {},
): Promise<MasterProductPage> {
  return getParsed(
    client,
    buildMasterProductsPath(params),
    readMasterProductPage,
    'daftar master produk',
  );
}

/** Detail satu produk. Gagal HTTP (404/403) → melempar pesan backend. */
export async function fetchProduct(client: ApiClient, id: number): Promise<MasterProductRow> {
  return getParsed(
    client,
    `${MASTER_PRODUCTS_PATH}${id}/`,
    readMasterProductRow,
    'detail master produk',
  );
}

/** Buat produk (POST) — backend membalas 201 + `sync_record_id`/`task_id`. */
export async function createProduct(
  client: ApiClient,
  input: MasterProductInput,
): Promise<MasterProductSaved> {
  return readSaved(await client.post<unknown>(MASTER_PRODUCTS_PATH, toMasterProductBody(input)));
}

/** Ubah produk (PUT) — hanya field yang dikirim yang berubah. */
export async function updateProduct(
  client: ApiClient,
  id: number,
  input: MasterProductInput,
): Promise<MasterProductSaved> {
  return readSaved(
    await client.request<unknown>(`${MASTER_PRODUCTS_PATH}${id}/`, {
      method: 'PUT',
      body: toMasterProductBody(input),
    }),
  );
}

/** Nonaktifkan produk (DELETE = **soft delete**; baris tidak dihapus dari DB). */
export async function deleteProduct(client: ApiClient, id: number): Promise<void> {
  unwrap(await client.request<unknown>(`${MASTER_PRODUCTS_PATH}${id}/`, { method: 'DELETE' }));
}

