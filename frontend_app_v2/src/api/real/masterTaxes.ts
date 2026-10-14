// REAL - master Tax (H3.6). Endpoint: `/api/v1/master/taxes/`
//   GET|POST `/master/taxes/` + GET|PUT|DELETE `/master/taxes/<id>/`
//   POST `/master/taxes/<id>/set-default/`  +  GET `/master/taxes/default/`
//
// Pemetaan UI ↔ backend (tidak ada shape yang dikarang):
//   * envelope ListPage `{rows, total_count, has_more, next_cursor}` (paging offset:
//     `limit` 1..200 default 50, `cursor` = offset);
//   * filter `?search=` (code/name icontains), `?type_tax_use=sale|purchase|none`,
//     `?active=true|false`; urut `code`;
//   * baris `{id, code, name, amount, amount_type, type_tax_use, price_include,
//     is_default, active, odoo_id}`;
//   * POST/PUT menambah `{sync_record_id, task_id, queued}` (push Odoo async);
//   * **DELETE = soft delete** (`active=False`; penanda `is_default` dilepas).
//
// `default/` dipakai form SO/PO (H2.1/H2.2) untuk mengisi `tax_ids` otomatis.
//
// Catatan: `ApiClient` hanya punya `get`/`post` — PUT/DELETE lewat `client.request()`.
import type { ApiClient, ApiResponse } from '@/integrations/api-client';
import type {
  MasterTaxInput,
  MasterTaxRow,
  MasterTaxSaved,
  TaxAmountType,
  TaxUse,
} from '@/types/master-tax';
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
export const MASTER_TAXES_PATH = '/master/taxes/';

/** Batas paging backend (`master/api.py::DEFAULT_LIMIT` / `MAX_LIMIT`). */
export const TAXES_LIMIT_DEFAULT = 50;
export const TAXES_LIMIT_MAX = 200;

/** Respons 200 `GET /master/taxes/`. */
export type MasterTaxPage = ListPage<MasterTaxRow>;

export interface MasterTaxesParams {
  search?: string | null;
  /** `null`/`undefined` = tidak difilter (backend hanya memfilter kalau param dikirim). */
  type_tax_use?: TaxUse | null;
  active?: boolean | null;
  limit?: number | null;
  cursor?: number | null;
}

/** PURE — path + query `GET /master/taxes/` (hanya param terisi yang dikirim). */
export function buildMasterTaxesPath(params: MasterTaxesParams = {}): string {
  return buildQueryPath(MASTER_TAXES_PATH, {
    search: params.search,
    type_tax_use: params.type_tax_use,
    active: params.active === null || params.active === undefined ? null : params.active,
    limit: params.limit,
    cursor: params.cursor,
  });
}

/** PURE — nilai `amount_type` backend yang sah (`percent|fixed`); lain → `percent`. */
export function readTaxAmountType(value: unknown): TaxAmountType {
  return value === 'fixed' ? 'fixed' : 'percent';
}

/** PURE — nilai `type_tax_use` backend yang sah (`sale|purchase|none`); lain → `sale`. */
export function readTaxUse(value: unknown): TaxUse {
  return value === 'purchase' || value === 'none' ? value : 'sale';
}

/** PURE — satu baris mentah → `MasterTaxRow`; `null` kalau tanpa `id` angka. */
export function readMasterTaxRow(raw: unknown): MasterTaxRow | null {
  if (!isRecord(raw)) return null;

  const id = raw['id'];
  if (typeof id !== 'number' || !Number.isFinite(id)) return null;

  return {
    id,
    code: readStr(raw['code']),
    name: readStr(raw['name']),
    amount: readNum(raw['amount']),
    amount_type: readTaxAmountType(raw['amount_type']),
    type_tax_use: readTaxUse(raw['type_tax_use']),
    price_include: readBool(raw['price_include']),
    is_default: readBool(raw['is_default']),
    active: readBool(raw['active']),
    odoo_id: readNullableNum(raw['odoo_id']),
  };
}

/** PURE — respons ListPage master Tax. */
export function readMasterTaxPage(raw: unknown): MasterTaxPage | null {
  return readListPage<MasterTaxRow>(raw, readMasterTaxRow);
}

/** PURE — baris hasil simpan (+ info sinkronisasi H3.6). */
export function readMasterTaxSaved(raw: unknown): MasterTaxSaved | null {
  const row = readMasterTaxRow(raw);
  if (row === null) return null;

  const extra = isRecord(raw) ? raw : {};

  return {
    ...row,
    sync_record_id: readNullableNum(extra['sync_record_id']),
    task_id: readNullableStr(extra['task_id']),
    queued: readBool(extra['queued']),
  };
}

/** PURE — respons `GET /master/taxes/default/` → `{tax: …|null}`. */
export function readMasterTaxDefault(raw: unknown): MasterTaxRow | null {
  if (!isRecord(raw)) return null;

  return readMasterTaxRow(raw['tax']);
}

/** PURE — input UI → body backend (trim teks, angka apa adanya). */
export function toMasterTaxBody(input: MasterTaxInput): Record<string, unknown> {
  return {
    code: input.code.trim(),
    name: input.name.trim(),
    amount: input.amount,
    amount_type: input.amount_type,
    type_tax_use: input.type_tax_use,
    price_include: input.price_include,
    is_default: input.is_default,
    active: input.active,
  };
}

function readSaved(res: ApiResponse<unknown>): MasterTaxSaved {
  const saved = readMasterTaxSaved(unwrap(res));
  if (saved === null) {
    throw new Error('Bentuk respons simpan Tax tidak dikenali.');
  }

  return saved;
}

/** Daftar pajak + filter (halaman memakai `next_cursor`/`has_more` untuk paging). */
export async function fetchTaxes(
  client: ApiClient,
  params: MasterTaxesParams = {},
): Promise<MasterTaxPage> {
  return getParsed(client, buildMasterTaxesPath(params), readMasterTaxPage, 'daftar master Tax');
}

/** Detail satu pajak. Gagal HTTP (404/403) → melempar pesan backend. */
export async function fetchTax(client: ApiClient, id: number): Promise<MasterTaxRow> {
  return getParsed(client, `${MASTER_TAXES_PATH}${id}/`, readMasterTaxRow, 'detail master Tax');
}

/** Buat pajak (POST) — backend membalas 201 + `sync_record_id`/`task_id`. */
export async function createTax(
  client: ApiClient,
  input: MasterTaxInput,
): Promise<MasterTaxSaved> {
  return readSaved(await client.post<unknown>(MASTER_TAXES_PATH, toMasterTaxBody(input)));
}

/** Ubah pajak (PUT) — hanya field yang dikirim yang berubah. */
export async function updateTax(
  client: ApiClient,
  id: number,
  input: MasterTaxInput,
): Promise<MasterTaxSaved> {
  return readSaved(
    await client.request<unknown>(`${MASTER_TAXES_PATH}${id}/`, {
      method: 'PUT',
      body: toMasterTaxBody(input),
    }),
  );
}

/** Nonaktifkan pajak (DELETE = **soft delete**; baris tidak dihapus dari DB). */
export async function deleteTax(client: ApiClient, id: number): Promise<void> {
  unwrap(await client.request<unknown>(`${MASTER_TAXES_PATH}${id}/`, { method: 'DELETE' }));
}

/** Jadikan pajak default MES (POST `set-default/`) — atomik, maksimal satu default. */
export async function setDefaultTax(client: ApiClient, id: number): Promise<MasterTaxRow> {
  const res = await client.post<unknown>(`${MASTER_TAXES_PATH}${id}/set-default/`, {});
  const row = readMasterTaxRow(unwrap(res));

  if (row === null) {
    throw new Error('Bentuk respons pajak default Tax tidak dikenali.');
  }

  return row;
}

/**
 * Pajak default MES (`null` = belum ada pajak sama sekali) — REAL (H3.6).
 *
 * Backend membalas `{"tax": null}` (200) kalau belum ada pajak, jadi `getParsed`
 * TIDAK dipakai di sini (helper itu melempar untuk hasil `null`).
 */
export async function fetchDefaultTax(client: ApiClient): Promise<MasterTaxRow | null> {
  return readMasterTaxDefault(unwrap(await client.get<unknown>(`${MASTER_TAXES_PATH}default/`)));
}

