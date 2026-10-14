// REAL - master Warehouse (H1.3). Endpoint: `/api/v1/master/warehouses/`
//   GET|POST `/master/warehouses/`  +  GET|PUT|DELETE `/master/warehouses/<id>/`
//
// Pemetaan UI ↔ backend (tidak ada shape yang dikarang):
//   * envelope ListPage `{rows, total_count, has_more, next_cursor}` (paging offset:
//     `limit` 1..200 default 50, `cursor` = offset);
//   * filter `?search=` (code/name icontains), `?active=true|false`; urut `code`;
//   * baris `{id, code, name, reception_steps, delivery_steps, active, odoo_id}` —
//     `active` adalah nama publik `Warehouse.is_active`;
//   * POST/PUT menambah `{sync_record_id, task_id, queued}` (push Odoo async);
//   * **DELETE = soft delete** (`active=False`; baris tetap ada, 200 + `{deleted:true}`).
//
// Catatan: `ApiClient` hanya punya `get`/`post` — PUT/DELETE lewat `client.request()`.
import type { ApiClient, ApiResponse } from '@/integrations/api-client';
import type {
  DeliverySteps,
  MasterWarehouseInput,
  MasterWarehouseRow,
  MasterWarehouseSaved,
  ReceptionSteps,
} from '@/types/master-warehouse';
import { unwrap } from '../client';
import {
  buildQueryPath,
  getParsed,
  isRecord,
  readBool,
  readListPage,
  readNullableNum,
  readNullableStr,
  readStr,
  type ListPage,
} from './_shape';

/** Path relatif terhadap `VITE_API_BASE_URL` (`…/api/v1`). */
export const MASTER_WAREHOUSES_PATH = '/master/warehouses/';

/** Batas paging backend (`master/api.py::DEFAULT_LIMIT` / `MAX_LIMIT`). */
export const WAREHOUSES_LIMIT_DEFAULT = 50;
export const WAREHOUSES_LIMIT_MAX = 200;

/** Respons 200 `GET /master/warehouses/`. */
export type MasterWarehousePage = ListPage<MasterWarehouseRow>;

export interface MasterWarehousesParams {
  search?: string | null;
  /** `null`/`undefined` = tidak difilter (backend hanya memfilter kalau param dikirim). */
  active?: boolean | null;
  limit?: number | null;
  cursor?: number | null;
}

/** PURE — path + query `GET /master/warehouses/` (hanya param terisi yang dikirim). */
export function buildMasterWarehousesPath(params: MasterWarehousesParams = {}): string {
  return buildQueryPath(MASTER_WAREHOUSES_PATH, {
    search: params.search,
    active: params.active === null || params.active === undefined ? null : params.active,
    limit: params.limit,
    cursor: params.cursor,
  });
}

/** PURE — nilai `reception_steps` backend yang sah; lain → `one_step`. */
export function readReceptionSteps(value: unknown): ReceptionSteps {
  if (value === 'two_steps' || value === 'three_steps') return value;

  return 'one_step';
}

/** PURE — nilai `delivery_steps` backend yang sah; lain → `ship_only`. */
export function readDeliverySteps(value: unknown): DeliverySteps {
  if (value === 'pick_ship' || value === 'pick_pack_ship') return value;

  return 'ship_only';
}

/** PURE — satu baris mentah → `MasterWarehouseRow`; `null` kalau tanpa `id` angka. */
export function readMasterWarehouseRow(raw: unknown): MasterWarehouseRow | null {
  if (!isRecord(raw)) return null;

  const id = raw['id'];
  if (typeof id !== 'number' || !Number.isFinite(id)) return null;

  return {
    id,
    code: readStr(raw['code']),
    name: readStr(raw['name']),
    reception_steps: readReceptionSteps(raw['reception_steps']),
    delivery_steps: readDeliverySteps(raw['delivery_steps']),
    active: readBool(raw['active']),
    odoo_id: readNullableNum(raw['odoo_id']),
  };
}

/** PURE — respons ListPage master Warehouse. */
export function readMasterWarehousePage(raw: unknown): MasterWarehousePage | null {
  return readListPage<MasterWarehouseRow>(raw, readMasterWarehouseRow);
}

/** PURE — baris hasil simpan (+ info sinkronisasi H1.3). */
export function readMasterWarehouseSaved(raw: unknown): MasterWarehouseSaved | null {
  const row = readMasterWarehouseRow(raw);
  if (row === null) return null;

  const extra = isRecord(raw) ? raw : {};

  return {
    ...row,
    sync_record_id: readNullableNum(extra['sync_record_id']),
    task_id: readNullableStr(extra['task_id']),
    queued: readBool(extra['queued']),
  };
}

/** PURE — input UI → body backend (trim teks). */
export function toMasterWarehouseBody(input: MasterWarehouseInput): Record<string, unknown> {
  return {
    code: input.code.trim(),
    name: input.name.trim(),
    reception_steps: input.reception_steps,
    delivery_steps: input.delivery_steps,
    active: input.active,
  };
}

function readSaved(res: ApiResponse<unknown>): MasterWarehouseSaved {
  const saved = readMasterWarehouseSaved(unwrap(res));
  if (saved === null) {
    throw new Error('Bentuk respons simpan gudang tidak dikenali.');
  }

  return saved;
}

/** Daftar gudang + filter (halaman memakai `next_cursor`/`has_more` untuk paging). */
export async function fetchWarehouses(
  client: ApiClient,
  params: MasterWarehousesParams = {},
): Promise<MasterWarehousePage> {
  return getParsed(
    client,
    buildMasterWarehousesPath(params),
    readMasterWarehousePage,
    'daftar master gudang',
  );
}

/** Detail satu gudang. Gagal HTTP (404/403) → melempar pesan backend. */
export async function fetchWarehouse(
  client: ApiClient,
  id: number,
): Promise<MasterWarehouseRow> {
  return getParsed(
    client,
    `${MASTER_WAREHOUSES_PATH}${id}/`,
    readMasterWarehouseRow,
    'detail master gudang',
  );
}

/** Buat gudang (POST) — backend membalas 201 + `sync_record_id`/`task_id`. */
export async function createWarehouse(
  client: ApiClient,
  input: MasterWarehouseInput,
): Promise<MasterWarehouseSaved> {
  return readSaved(
    await client.post<unknown>(MASTER_WAREHOUSES_PATH, toMasterWarehouseBody(input)),
  );
}

/** Ubah gudang (PUT) — hanya field yang dikirim yang berubah. */
export async function updateWarehouse(
  client: ApiClient,
  id: number,
  input: MasterWarehouseInput,
): Promise<MasterWarehouseSaved> {
  return readSaved(
    await client.request<unknown>(`${MASTER_WAREHOUSES_PATH}${id}/`, {
      method: 'PUT',
      body: toMasterWarehouseBody(input),
    }),
  );
}

/** Nonaktifkan gudang (DELETE = **soft delete**; baris tidak dihapus dari DB). */
export async function deleteWarehouse(client: ApiClient, id: number): Promise<void> {
  unwrap(await client.request<unknown>(`${MASTER_WAREHOUSES_PATH}${id}/`, { method: 'DELETE' }));
}

