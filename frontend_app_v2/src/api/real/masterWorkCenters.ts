// REAL - master Work Center (H1.7). Endpoint: `/api/v1/master/work-centers/`
//   GET|POST `/master/work-centers/`  +  GET|PUT|DELETE `/master/work-centers/<id>/`
//
// Pemetaan UI ↔ backend (tidak ada shape yang dikarang):
//   * envelope ListPage `{rows, total_count, has_more, next_cursor}` (`limit` 1..200
//     default 50, `cursor` = offset); filter `?search=` (code/name/wc_type icontains),
//     `?wc_type=` (exact case-insensitive), `?active=`; urut `code`;
//   * baris `{id, code, name, wc_type, capability_tags, capacity_per_hour,
//     description, active, config, created_at, updated_at}`; **detail** menambah
//     `active_bundles_count` + `production_lines`;
//   * POST/PUT membalas detail + `{sync_record_id, sync_status, task_id, queued,
//     mes_only}` — H1.7 **MES-only**: `sync_status='SKIPPED'`, `task_id=null`,
//     `queued=false` (tidak ada push Odoo; lihat `/settings/sync?status=SKIPPED`);
//   * **DELETE = soft delete** (`active=false`) — 400 kalau WC masih memegang
//     bundle aktif (state bukan DONE/CANCELLED).
//
// Catatan: `ApiClient` hanya punya `get`/`post` — PUT/DELETE lewat `client.request()`.
import type { ApiClient, ApiResponse } from '@/integrations/api-client';
import type {
  MasterWorkCenterDetail,
  MasterWorkCenterInput,
  MasterWorkCenterLine,
  MasterWorkCenterRow,
  MasterWorkCenterSaved,
} from '@/types/master-work-center';
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
export const MASTER_WORK_CENTERS_PATH = '/master/work-centers/';

/** Batas paging backend (`master/api.py::DEFAULT_LIMIT` / `MAX_LIMIT`). */
export const WORK_CENTERS_LIMIT_DEFAULT = 50;
export const WORK_CENTERS_LIMIT_MAX = 200;

/** Respons 200 `GET /master/work-centers/`. */
export type MasterWorkCenterPage = ListPage<MasterWorkCenterRow>;

export interface MasterWorkCentersParams {
  search?: string | null;
  /** Kode tipe stasiun (exact, case-insensitive di backend). */
  wc_type?: string | null;
  active?: boolean | null;
  limit?: number | null;
  cursor?: number | null;
}

/** PURE — path + query `GET /master/work-centers/` (hanya param terisi dikirim). */
export function buildMasterWorkCentersPath(params: MasterWorkCentersParams = {}): string {
  return buildQueryPath(MASTER_WORK_CENTERS_PATH, {
    search: params.search,
    wc_type: params.wc_type,
    active: params.active === null || params.active === undefined ? null : params.active,
    limit: params.limit,
    cursor: params.cursor,
  });
}

/** PURE — daftar tag dari payload mentah (`unknown` → string[]). */
function readTags(raw: unknown): string[] {
  if (!Array.isArray(raw)) return [];

  return raw.filter((item): item is string => typeof item === 'string');
}

/** PURE — satu lini produksi dari payload mentah. */
function readLine(raw: unknown): MasterWorkCenterLine | null {
  if (!isRecord(raw)) return null;
  const id = raw['id'];
  if (typeof id !== 'number' || !Number.isFinite(id)) return null;

  return { id, code: readStr(raw['code']), name: readStr(raw['name']) };
}

/** PURE — `config` mentah → objek (default `{}`). */
function readConfig(raw: unknown): Record<string, unknown> {
  return isRecord(raw) ? raw : {};
}

/** PURE — baris list mentah → `MasterWorkCenterRow`; `null` kalau tanpa `id` angka. */
export function readMasterWorkCenterRow(raw: unknown): MasterWorkCenterRow | null {
  if (!isRecord(raw)) return null;

  const id = raw['id'];
  if (typeof id !== 'number' || !Number.isFinite(id)) return null;

  return {
    id,
    code: readStr(raw['code']),
    name: readStr(raw['name']),
    wc_type: readStr(raw['wc_type']),
    capability_tags: readTags(raw['capability_tags']),
    capacity_per_hour: readNum(raw['capacity_per_hour']),
    description: readStr(raw['description']),
    active: readBool(raw['active']),
    config: readConfig(raw['config']),
    created_at: readNullableStr(raw['created_at']),
    updated_at: readNullableStr(raw['updated_at']),
  };
}

/** PURE — detail mentah → `MasterWorkCenterDetail` (+ bundle aktif & lini). */
export function readMasterWorkCenterDetail(raw: unknown): MasterWorkCenterDetail | null {
  const row = readMasterWorkCenterRow(raw);
  if (row === null) return null;

  const extra = isRecord(raw) ? raw : {};
  const lines = Array.isArray(extra['production_lines']) ? extra['production_lines'] : [];

  return {
    ...row,
    active_bundles_count: readNum(extra['active_bundles_count']),
    production_lines: lines
      .map(readLine)
      .filter((line): line is MasterWorkCenterLine => line !== null),
  };
}

/** PURE — respons ListPage master Work Center. */
export function readMasterWorkCenterPage(raw: unknown): MasterWorkCenterPage | null {
  return readListPage<MasterWorkCenterRow>(raw, readMasterWorkCenterRow);
}

/** PURE — baris hasil simpan (+ jejak sync MES-only). */
export function readMasterWorkCenterSaved(raw: unknown): MasterWorkCenterSaved | null {
  const detail = readMasterWorkCenterDetail(raw);
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

/** PURE — input UI → body backend (trim teks; tag dibersihkan view agar konsisten). */
export function toMasterWorkCenterBody(
  input: MasterWorkCenterInput,
): Record<string, unknown> {
  return {
    code: input.code.trim(),
    name: input.name.trim(),
    wc_type: input.wc_type.trim(),
    capability_tags: input.capability_tags,
    capacity_per_hour: input.capacity_per_hour,
    description: input.description.trim(),
    active: input.active,
  };
}

function readSaved(res: ApiResponse<unknown>): MasterWorkCenterSaved {
  const saved = readMasterWorkCenterSaved(unwrap(res));
  if (saved === null) {
    throw new Error('Bentuk respons simpan work center tidak dikenali.');
  }

  return saved;
}

/** Daftar work center + filter (`next_cursor`/`has_more` untuk paging). */
export async function fetchWorkCenters(
  client: ApiClient,
  params: MasterWorkCentersParams = {},
): Promise<MasterWorkCenterPage> {
  return getParsed(
    client,
    buildMasterWorkCentersPath(params),
    readMasterWorkCenterPage,
    'daftar master work center',
  );
}

/** Detail satu work center (+ `active_bundles_count` & `production_lines`). */
export async function fetchWorkCenter(
  client: ApiClient,
  id: number,
): Promise<MasterWorkCenterDetail> {
  return getParsed(
    client,
    `${MASTER_WORK_CENTERS_PATH}${id}/`,
    readMasterWorkCenterDetail,
    'detail master work center',
  );
}

/** Buat work center (POST) — 201 + detail + `sync_record_id`/`sync_status`. */
export async function createWorkCenter(
  client: ApiClient,
  input: MasterWorkCenterInput,
): Promise<MasterWorkCenterSaved> {
  return readSaved(
    await client.post<unknown>(MASTER_WORK_CENTERS_PATH, toMasterWorkCenterBody(input)),
  );
}

/** Ubah work center (PUT) — hanya field yang dikirim yang berubah. */
export async function updateWorkCenter(
  client: ApiClient,
  id: number,
  input: MasterWorkCenterInput,
): Promise<MasterWorkCenterSaved> {
  return readSaved(
    await client.request<unknown>(`${MASTER_WORK_CENTERS_PATH}${id}/`, {
      method: 'PUT',
      body: toMasterWorkCenterBody(input),
    }),
  );
}

/** Nonaktifkan work center (DELETE = soft delete; 400 kalau masih ada bundle aktif). */
export async function deleteWorkCenter(client: ApiClient, id: number): Promise<void> {
  unwrap(await client.request<unknown>(`${MASTER_WORK_CENTERS_PATH}${id}/`, { method: 'DELETE' }));
}
