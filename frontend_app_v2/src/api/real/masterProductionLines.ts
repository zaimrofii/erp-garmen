// REAL - master Production Line (H1.8). Endpoint: `/api/v1/master/production-lines/`
//   GET|POST `/master/production-lines/`
//   GET|PUT|DELETE `/master/production-lines/<id>/`
//
// Pemetaan UI ↔ backend (tidak ada shape yang dikarang):
//   * envelope ListPage `{rows, total_count, has_more, next_cursor}` (`limit` 1..200
//     default 50, `cursor` = offset); filter `?search=` (code/name icontains),
//     `?capability_tag=` (cocok sebagian di list tag, case-insensitive),
//     `?work_center=<id>`, `?active=`; urut `code`;
//   * baris `{id, code, name, description, capability_tags, work_centers_count,
//     work_center_ids, work_center_names, allocation_rules_count, active,
//     created_at, updated_at}`; **detail** menambah `work_centers[]` +
//     `active_bundles_count`;
//   * POST/PUT mengirim `work_center_ids` (replace penuh, atomic di backend) dan
//     membalas detail + `{sync_record_id, sync_status, task_id, queued, mes_only}`
//     → H1.8 **MES-only**: `sync_status='SKIPPED'`, `task_id=null`, `queued=false`;
//   * **DELETE = soft delete** (`active=false`) — 400 kalau lini masih menampung
//     bundle aktif (state bukan DONE/CANCELLED).
//
// Catatan: `ApiClient` hanya punya `get`/`post` — PUT/DELETE lewat `client.request()`.
import type { ApiClient, ApiResponse } from '@/integrations/api-client';
import type {
  MasterProductionLineDetail,
  MasterProductionLineInput,
  MasterProductionLineRow,
  MasterProductionLineSaved,
  MasterProductionLineWorkCenter,
} from '@/types/master-production-line';
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
export const MASTER_PRODUCTION_LINES_PATH = '/master/production-lines/';

/** Batas paging backend (`master/api.py::DEFAULT_LIMIT` / `MAX_LIMIT`). */
export const PRODUCTION_LINES_LIMIT_DEFAULT = 50;
export const PRODUCTION_LINES_LIMIT_MAX = 200;

/** Respons 200 `GET /master/production-lines/`. */
export type MasterProductionLinePage = ListPage<MasterProductionLineRow>;

export interface MasterProductionLinesParams {
  search?: string | null;
  capability_tag?: string | null;
  work_center?: number | null;
  active?: boolean | null;
  limit?: number | null;
  cursor?: number | null;
}

/** PURE — path + query `GET /master/production-lines/` (hanya param terisi dikirim). */
export function buildMasterProductionLinesPath(
  params: MasterProductionLinesParams = {},
): string {
  return buildQueryPath(MASTER_PRODUCTION_LINES_PATH, {
    search: params.search,
    capability_tag: params.capability_tag,
    work_center: params.work_center,
    active: params.active === null || params.active === undefined ? null : params.active,
    limit: params.limit,
    cursor: params.cursor,
  });
}

/** PURE — daftar string dari payload mentah (tag/WC names). */
function readStrings(raw: unknown): string[] {
  if (!Array.isArray(raw)) return [];

  return raw.filter((item): item is string => typeof item === 'string');
}

/** PURE — daftar angka dari payload mentah (id WC). */
function readNumbers(raw: unknown): number[] {
  if (!Array.isArray(raw)) return [];

  return raw.filter((item): item is number => typeof item === 'number' && Number.isFinite(item));
}

/** PURE — satu anggota WC dari payload mentah (dipakai `work_centers[]`). */
function readWorkCenter(raw: unknown): MasterProductionLineWorkCenter | null {
  if (!isRecord(raw)) return null;
  const id = raw['id'];
  if (typeof id !== 'number' || !Number.isFinite(id)) return null;

  return { id, code: readStr(raw['code']), name: readStr(raw['name']) };
}

/** PURE — baris list mentah → `MasterProductionLineRow`; `null` tanpa `id` angka. */
export function readMasterProductionLineRow(raw: unknown): MasterProductionLineRow | null {
  if (!isRecord(raw)) return null;

  const id = raw['id'];
  if (typeof id !== 'number' || !Number.isFinite(id)) return null;

  return {
    id,
    code: readStr(raw['code']),
    name: readStr(raw['name']),
    description: readStr(raw['description']),
    capability_tags: readStrings(raw['capability_tags']),
    work_centers_count: readNum(raw['work_centers_count']),
    work_center_ids: readNumbers(raw['work_center_ids']),
    work_center_names: readStrings(raw['work_center_names']),
    allocation_rules_count: readNum(raw['allocation_rules_count']),
    active: readBool(raw['active']),
    created_at: readNullableStr(raw['created_at']),
    updated_at: readNullableStr(raw['updated_at']),
  };
}

/** PURE — detail mentah → `MasterProductionLineDetail` (+ anggota WC & bundle aktif). */
export function readMasterProductionLineDetail(
  raw: unknown,
): MasterProductionLineDetail | null {
  const row = readMasterProductionLineRow(raw);
  if (row === null) return null;

  const extra = isRecord(raw) ? raw : {};
  const centers = Array.isArray(extra['work_centers']) ? extra['work_centers'] : [];

  return {
    ...row,
    work_centers: centers
      .map(readWorkCenter)
      .filter((center): center is MasterProductionLineWorkCenter => center !== null),
    active_bundles_count: readNum(extra['active_bundles_count']),
  };
}

/** PURE — respons ListPage master Production Line. */
export function readMasterProductionLinePage(raw: unknown): MasterProductionLinePage | null {
  return readListPage<MasterProductionLineRow>(raw, readMasterProductionLineRow);
}

/** PURE — baris hasil simpan (+ jejak sync MES-only). */
export function readMasterProductionLineSaved(raw: unknown): MasterProductionLineSaved | null {
  const detail = readMasterProductionLineDetail(raw);
  if (detail === null) return null;

  const extra = isRecord(raw) ? raw : {};

  return {
    ...detail,
    sync_record_id: readNullableNum(extra['sync_record_id']),
    sync_status: readNullableStr(extra['sync_status']),
    task_id: readNullableStr(extra['task_id']),
    queued: readBool(extra['queued']),
    mes_only: readBool(extra['mes_only']),
  };
}

/** PURE — input UI → body backend (trim teks; `work_center_ids` = replace penuh). */
export function toMasterProductionLineBody(
  input: MasterProductionLineInput,
): Record<string, unknown> {
  return {
    code: input.code.trim(),
    name: input.name.trim(),
    description: input.description.trim(),
    capability_tags: input.capability_tags,
    work_center_ids: input.work_center_ids,
    active: input.active,
  };
}

function readSaved(res: ApiResponse<unknown>): MasterProductionLineSaved {
  const saved = readMasterProductionLineSaved(unwrap(res));
  if (saved === null) {
    throw new Error('Bentuk respons simpan production line tidak dikenali.');
  }

  return saved;
}

/** Daftar production line + filter (`next_cursor`/`has_more` untuk paging). */
export async function fetchProductionLines(
  client: ApiClient,
  params: MasterProductionLinesParams = {},
): Promise<MasterProductionLinePage> {
  return getParsed(
    client,
    buildMasterProductionLinesPath(params),
    readMasterProductionLinePage,
    'daftar master production line',
  );
}

/** Detail satu production line (+ `work_centers[]` & `active_bundles_count`). */
export async function fetchProductionLine(
  client: ApiClient,
  id: number,
): Promise<MasterProductionLineDetail> {
  return getParsed(
    client,
    `${MASTER_PRODUCTION_LINES_PATH}${id}/`,
    readMasterProductionLineDetail,
    'detail master production line',
  );
}

/** Buat production line (POST) — 201 + detail + `sync_record_id`/`sync_status`. */
export async function createProductionLine(
  client: ApiClient,
  input: MasterProductionLineInput,
): Promise<MasterProductionLineSaved> {
  return readSaved(
    await client.post<unknown>(MASTER_PRODUCTION_LINES_PATH, toMasterProductionLineBody(input)),
  );
}

/** Ubah production line (PUT) — termasuk replace M2M `work_center_ids`. */
export async function updateProductionLine(
  client: ApiClient,
  id: number,
  input: MasterProductionLineInput,
): Promise<MasterProductionLineSaved> {
  return readSaved(
    await client.request<unknown>(`${MASTER_PRODUCTION_LINES_PATH}${id}/`, {
      method: 'PUT',
      body: toMasterProductionLineBody(input),
    }),
  );
}

/** Nonaktifkan lini (DELETE = soft delete; 400 kalau masih ada bundle aktif). */
export async function deleteProductionLine(client: ApiClient, id: number): Promise<void> {
  unwrap(
    await client.request<unknown>(`${MASTER_PRODUCTION_LINES_PATH}${id}/`, { method: 'DELETE' }),
  );
}
