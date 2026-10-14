// REAL - master UoM (H1.2). Endpoint: `/api/v1/master/uoms/`
//   GET|POST `/master/uoms/`  +  GET|PUT|DELETE `/master/uoms/<id>/`
//
// Pemetaan UI ↔ backend (tidak ada shape yang dikarang):
//   * envelope ListPage `{rows, total_count, has_more, next_cursor}` (paging offset:
//     `limit` 1..200 default 50, `cursor` = offset);
//   * filter `?search=` (code/name/category icontains), `?active=true|false`; urut `code`;
//   * baris `{id, code, name, category, uom_type, factor, rounding, active, odoo_id}`
//     — `active` adalah nama publik `UoM.is_active`;
//   * POST/PUT menambah `{sync_record_id, task_id, queued}` (push Odoo async);
//   * **DELETE = soft delete** (`active=False`; baris tetap ada, 200 + `{deleted:true}`).
//
// Catatan: `ApiClient` hanya punya `get`/`post` — PUT/DELETE lewat `client.request()`.
import type { ApiClient, ApiResponse } from '@/integrations/api-client';
import type { MasterUomInput, MasterUomRow, MasterUomSaved, UomType } from '@/types/master-uom';
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
export const MASTER_UOMS_PATH = '/master/uoms/';

/** Batas paging backend (`master/api.py::DEFAULT_LIMIT` / `MAX_LIMIT`). */
export const UOMS_LIMIT_DEFAULT = 50;
export const UOMS_LIMIT_MAX = 200;

/** Respons 200 `GET /master/uoms/`. */
export type MasterUomPage = ListPage<MasterUomRow>;

export interface MasterUomsParams {
  search?: string | null;
  /** `null`/`undefined` = tidak difilter (backend hanya memfilter kalau param dikirim). */
  active?: boolean | null;
  limit?: number | null;
  cursor?: number | null;
}

/** PURE — path + query `GET /master/uoms/` (hanya param terisi yang dikirim). */
export function buildMasterUomsPath(params: MasterUomsParams = {}): string {
  return buildQueryPath(MASTER_UOMS_PATH, {
    search: params.search,
    active: params.active === null || params.active === undefined ? null : params.active,
    limit: params.limit,
    cursor: params.cursor,
  });
}

/** PURE — nilai `uom_type` backend yang sah (`bigger|reference|smaller`); lain → `reference`. */
export function readUomType(value: unknown): UomType {
  return value === 'bigger' || value === 'smaller' ? value : 'reference';
}

/** PURE — satu baris mentah → `MasterUomRow`; `null` kalau tanpa `id` angka. */
export function readMasterUomRow(raw: unknown): MasterUomRow | null {
  if (!isRecord(raw)) return null;

  const id = raw['id'];
  if (typeof id !== 'number' || !Number.isFinite(id)) return null;

  return {
    id,
    code: readStr(raw['code']),
    name: readStr(raw['name']),
    category: readStr(raw['category']),
    uom_type: readUomType(raw['uom_type']),
    factor: readNum(raw['factor']),
    rounding: readNum(raw['rounding']),
    active: readBool(raw['active']),
    odoo_id: readNullableNum(raw['odoo_id']),
  };
}

/** PURE — respons ListPage master UoM. */
export function readMasterUomPage(raw: unknown): MasterUomPage | null {
  return readListPage<MasterUomRow>(raw, readMasterUomRow);
}

/** PURE — baris hasil simpan (+ info sinkronisasi H1.2). */
export function readMasterUomSaved(raw: unknown): MasterUomSaved | null {
  const row = readMasterUomRow(raw);
  if (row === null) return null;

  const extra = isRecord(raw) ? raw : {};

  return {
    ...row,
    sync_record_id: readNullableNum(extra['sync_record_id']),
    task_id: readNullableStr(extra['task_id']),
    queued: readBool(extra['queued']),
  };
}

/** PURE — input UI → body backend (trim teks, angka apa adanya). */
export function toMasterUomBody(input: MasterUomInput): Record<string, unknown> {
  return {
    code: input.code.trim(),
    name: input.name.trim(),
    category: input.category.trim(),
    uom_type: input.uom_type,
    factor: input.factor,
    rounding: input.rounding,
    active: input.active,
  };
}

function readSaved(res: ApiResponse<unknown>): MasterUomSaved {
  const saved = readMasterUomSaved(unwrap(res));
  if (saved === null) {
    throw new Error('Bentuk respons simpan UoM tidak dikenali.');
  }

  return saved;
}

/** Daftar UoM + filter (halaman memakai `next_cursor`/`has_more` untuk paging). */
export async function fetchUoms(
  client: ApiClient,
  params: MasterUomsParams = {},
): Promise<MasterUomPage> {
  return getParsed(client, buildMasterUomsPath(params), readMasterUomPage, 'daftar master UoM');
}

/** Detail satu UoM. Gagal HTTP (404/403) → melempar pesan backend. */
export async function fetchUom(client: ApiClient, id: number): Promise<MasterUomRow> {
  return getParsed(client, `${MASTER_UOMS_PATH}${id}/`, readMasterUomRow, 'detail master UoM');
}

/** Buat UoM (POST) — backend membalas 201 + `sync_record_id`/`task_id`. */
export async function createUom(
  client: ApiClient,
  input: MasterUomInput,
): Promise<MasterUomSaved> {
  return readSaved(await client.post<unknown>(MASTER_UOMS_PATH, toMasterUomBody(input)));
}

/** Ubah UoM (PUT) — hanya field yang dikirim yang berubah. */
export async function updateUom(
  client: ApiClient,
  id: number,
  input: MasterUomInput,
): Promise<MasterUomSaved> {
  return readSaved(
    await client.request<unknown>(`${MASTER_UOMS_PATH}${id}/`, {
      method: 'PUT',
      body: toMasterUomBody(input),
    }),
  );
}

/** Nonaktifkan UoM (DELETE = **soft delete**; baris tidak dihapus dari DB). */
export async function deleteUom(client: ApiClient, id: number): Promise<void> {
  unwrap(await client.request<unknown>(`${MASTER_UOMS_PATH}${id}/`, { method: 'DELETE' }));
}
