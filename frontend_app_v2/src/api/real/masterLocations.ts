// REAL - master Location (H1.4). Endpoint: `/api/v1/master/locations/`
//   GET|POST `/master/locations/`  +  GET|PUT|DELETE `/master/locations/<id>/`
//
// Pemetaan UI ↔ backend (tidak ada shape yang dikarang):
//   * envelope ListPage `{rows, total_count, has_more, next_cursor}` (paging offset:
//     `limit` 1..200 default 50, `cursor` = offset);
//   * filter `?search=` (code/name icontains), `?usage=`, `?warehouse_id=`,
//     `?parent_id=`, `?active=true|false`; urut `code`;
//   * baris `{id, code, name, usage, parent_id, parent_name, warehouse_id,
//     warehouse_name, active, odoo_id, children_count, complete_name}`;
//   * POST/PUT menambah `{sync_record_id, task_id, queued}` (push Odoo async);
//   * **DELETE = soft delete** (`active=False`) dan backend menolak **400** kalau
//     lokasi masih punya anak aktif (nonaktifkan anak dulu).
//
// Catatan: `ApiClient` hanya punya `get`/`post` — PUT/DELETE lewat `client.request()`.
import type { ApiClient, ApiResponse } from '@/integrations/api-client';
import type {
  LocationUsage,
  MasterLocationInput,
  MasterLocationRow,
  MasterLocationSaved,
} from '@/types/master-location';
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
export const MASTER_LOCATIONS_PATH = '/master/locations/';

/** Batas paging backend (`master/api.py::DEFAULT_LIMIT` / `MAX_LIMIT`). */
export const LOCATIONS_LIMIT_DEFAULT = 50;
export const LOCATIONS_LIMIT_MAX = 200;

/** Nilai `usage` yang sah (probe `fields_get` `stock.location.usage`). */
export const LOCATION_USAGE_VALUES: readonly LocationUsage[] = [
  'supplier',
  'view',
  'internal',
  'customer',
  'inventory',
  'production',
  'transit',
];

/** Respons 200 `GET /master/locations/`. */
export type MasterLocationPage = ListPage<MasterLocationRow>;

export interface MasterLocationsParams {
  search?: string | null;
  usage?: LocationUsage | null;
  /** `null`/`undefined` = tidak difilter (backend hanya memfilter kalau param dikirim). */
  warehouse_id?: number | null;
  parent_id?: number | null;
  active?: boolean | null;
  limit?: number | null;
  cursor?: number | null;
}

/** PURE — path + query `GET /master/locations/` (hanya param terisi yang dikirim). */
export function buildMasterLocationsPath(params: MasterLocationsParams = {}): string {
  return buildQueryPath(MASTER_LOCATIONS_PATH, {
    search: params.search,
    usage: params.usage,
    warehouse_id: params.warehouse_id,
    parent_id: params.parent_id,
    active: params.active === null || params.active === undefined ? null : params.active,
    limit: params.limit,
    cursor: params.cursor,
  });
}

/** PURE — nilai `usage` backend yang sah; lain → `internal` (default model MES). */
export function readLocationUsage(value: unknown): LocationUsage {
  return LOCATION_USAGE_VALUES.find((candidate) => candidate === value) ?? 'internal';
}

/** PURE — satu baris mentah → `MasterLocationRow`; `null` kalau tanpa `id` angka. */
export function readMasterLocationRow(raw: unknown): MasterLocationRow | null {
  if (!isRecord(raw)) return null;

  const id = raw['id'];
  if (typeof id !== 'number' || !Number.isFinite(id)) return null;

  return {
    id,
    code: readStr(raw['code']),
    name: readStr(raw['name']),
    usage: readLocationUsage(raw['usage']),
    parent_id: readNullableNum(raw['parent_id']),
    parent_name: readNullableStr(raw['parent_name']),
    warehouse_id: readNullableNum(raw['warehouse_id']),
    warehouse_name: readNullableStr(raw['warehouse_name']),
    active: readBool(raw['active']),
    odoo_id: readNullableNum(raw['odoo_id']),
    children_count: readNum(raw['children_count']),
    complete_name: readStr(raw['complete_name']),
  };
}

/** PURE — respons ListPage master Location. */
export function readMasterLocationPage(raw: unknown): MasterLocationPage | null {
  return readListPage<MasterLocationRow>(raw, readMasterLocationRow);
}

/** PURE — baris hasil simpan (+ info sinkronisasi H1.4). */
export function readMasterLocationSaved(raw: unknown): MasterLocationSaved | null {
  const row = readMasterLocationRow(raw);
  if (row === null) return null;

  const extra = isRecord(raw) ? raw : {};

  return {
    ...row,
    sync_record_id: readNullableNum(extra['sync_record_id']),
    task_id: readNullableStr(extra['task_id']),
    queued: readBool(extra['queued']),
  };
}

/** PURE — input UI → body backend (trim teks; `parent_id`/`warehouse_id` apa adanya). */
export function toMasterLocationBody(input: MasterLocationInput): Record<string, unknown> {
  return {
    code: input.code.trim(),
    name: input.name.trim(),
    usage: input.usage,
    parent_id: input.parent_id,
    warehouse_id: input.warehouse_id,
    active: input.active,
  };
}

function readSaved(res: ApiResponse<unknown>): MasterLocationSaved {
  const saved = readMasterLocationSaved(unwrap(res));
  if (saved === null) {
    throw new Error('Bentuk respons simpan lokasi tidak dikenali.');
  }

  return saved;
}

/** Daftar lokasi + filter (halaman memakai `next_cursor`/`has_more` untuk paging). */
export async function fetchLocations(
  client: ApiClient,
  params: MasterLocationsParams = {},
): Promise<MasterLocationPage> {
  return getParsed(
    client,
    buildMasterLocationsPath(params),
    readMasterLocationPage,
    'daftar master lokasi',
  );
}

/** Detail satu lokasi. Gagal HTTP (404/403) → melempar pesan backend. */
export async function fetchLocation(client: ApiClient, id: number): Promise<MasterLocationRow> {
  return getParsed(
    client,
    `${MASTER_LOCATIONS_PATH}${id}/`,
    readMasterLocationRow,
    'detail master lokasi',
  );
}

/** Buat lokasi (POST) — backend membalas 201 + `sync_record_id`/`task_id`. */
export async function createLocation(
  client: ApiClient,
  input: MasterLocationInput,
): Promise<MasterLocationSaved> {
  return readSaved(await client.post<unknown>(MASTER_LOCATIONS_PATH, toMasterLocationBody(input)));
}

/** Ubah lokasi (PUT) — hanya field yang dikirim yang berubah. */
export async function updateLocation(
  client: ApiClient,
  id: number,
  input: MasterLocationInput,
): Promise<MasterLocationSaved> {
  return readSaved(
    await client.request<unknown>(`${MASTER_LOCATIONS_PATH}${id}/`, {
      method: 'PUT',
      body: toMasterLocationBody(input),
    }),
  );
}

/**
 * Nonaktifkan lokasi (DELETE = **soft delete**; baris tidak dihapus dari DB).
 * Backend membalas **400** kalau masih ada anak aktif — pesannya diteruskan apa adanya.
 */
export async function deleteLocation(client: ApiClient, id: number): Promise<void> {
  unwrap(await client.request<unknown>(`${MASTER_LOCATIONS_PATH}${id}/`, { method: 'DELETE' }));
}
