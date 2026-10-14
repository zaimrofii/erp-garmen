// REAL - master BOM (H1.5). Endpoint: `/api/v1/master/boms/`
//   GET|POST `/master/boms/`  +  GET|PUT|DELETE `/master/boms/<id>/`
//
// Pemetaan UI ↔ backend (tidak ada shape yang dikarang):
//   * envelope ListPage `{rows, total_count, has_more, next_cursor}` (paging offset:
//     `limit` 1..200 default 50, `cursor` = offset);
//   * filter `?search=` (kode/nama BOM + kode/nama produk), `?product_id=`,
//     `?active=true|false`; urut `code`;
//   * baris list `{…, lines_count, …}` (tanpa `lines[]`); **detail** menambah
//     `lines[]` (hanya baris aktif, urut `sequence`);
//   * POST/PUT menambah `{sync_record_id, task_id, queued}` (push Odoo async) dan
//     membalas **detail** BOM (jadi form bisa langsung menampilkan baris hasil simpan);
//   * PUT dengan `lines` **mengganti** seluruh baris aktif (baris lama yang hilang
//     di-*soft-delete* di backend); **DELETE = soft delete** (`active=False`).
//
// Catatan: `ApiClient` hanya punya `get`/`post` — PUT/DELETE lewat `client.request()`.
import type { ApiClient, ApiResponse } from '@/integrations/api-client';
import type {
  MasterBomDetail,
  MasterBomInput,
  MasterBomLineInput,
  MasterBomLineRow,
  MasterBomRow,
  MasterBomSaved,
} from '@/types/master-bom';
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
export const MASTER_BOMS_PATH = '/master/boms/';

/** Batas paging backend (`master/api.py::DEFAULT_LIMIT` / `MAX_LIMIT`). */
export const BOMS_LIMIT_DEFAULT = 50;
export const BOMS_LIMIT_MAX = 200;

/** Respons 200 `GET /master/boms/`. */
export type MasterBomPage = ListPage<MasterBomRow>;

export interface MasterBomsParams {
  search?: string | null;
  /** `null`/`undefined` = tidak difilter (backend hanya memfilter kalau param dikirim). */
  product_id?: number | null;
  active?: boolean | null;
  limit?: number | null;
  cursor?: number | null;
}

/** PURE — path + query `GET /master/boms/` (hanya param terisi yang dikirim). */
export function buildMasterBomsPath(params: MasterBomsParams = {}): string {
  return buildQueryPath(MASTER_BOMS_PATH, {
    search: params.search,
    product_id: params.product_id,
    active: params.active === null || params.active === undefined ? null : params.active,
    limit: params.limit,
    cursor: params.cursor,
  });
}

/** PURE — satu baris komponen mentah → `MasterBomLineRow`; `null` kalau tanpa `id`. */
export function readMasterBomLineRow(raw: unknown): MasterBomLineRow | null {
  if (!isRecord(raw)) return null;

  const id = raw['id'];
  if (typeof id !== 'number' || !Number.isFinite(id)) return null;

  return {
    id,
    product_id: readNullableNum(raw['product_id']),
    product_code: readNullableStr(raw['product_code']),
    product_name: readNullableStr(raw['product_name']),
    qty: readNum(raw['qty']),
    uom_id: readNullableNum(raw['uom_id']),
    uom_code: readNullableStr(raw['uom_code']),
    sequence: readNum(raw['sequence']),
    notes: readStr(raw['notes']),
    active: readBool(raw['active']),
    odoo_id: readNullableNum(raw['odoo_id']),
  };
}

/** PURE — baris list mentah → `MasterBomRow`; `null` kalau tanpa `id` angka. */
export function readMasterBomRow(raw: unknown): MasterBomRow | null {
  if (!isRecord(raw)) return null;

  const id = raw['id'];
  if (typeof id !== 'number' || !Number.isFinite(id)) return null;

  return {
    id,
    code: readStr(raw['code']),
    name: readStr(raw['name']),
    product_id: readNullableNum(raw['product_id']),
    product_code: readNullableStr(raw['product_code']),
    product_name: readNullableStr(raw['product_name']),
    output_qty: readNum(raw['output_qty']),
    uom_id: readNullableNum(raw['uom_id']),
    uom_code: readNullableStr(raw['uom_code']),
    notes: readStr(raw['notes']),
    active: readBool(raw['active']),
    odoo_id: readNullableNum(raw['odoo_id']),
    lines_count: readNum(raw['lines_count']),
    created_at: readNullableStr(raw['created_at']),
    updated_at: readNullableStr(raw['updated_at']),
  };
}

/** PURE — detail mentah → `MasterBomDetail` (baris di-parse & dibuang kalau rusak). */
export function readMasterBomDetail(raw: unknown): MasterBomDetail | null {
  const row = readMasterBomRow(raw);
  if (row === null) return null;

  const lines: MasterBomLineRow[] = [];
  const rawLines = isRecord(raw) ? raw['lines'] : undefined;
  if (Array.isArray(rawLines)) {
    for (const item of rawLines) {
      const line = readMasterBomLineRow(item);
      if (line !== null) lines.push(line);
    }
  }

  return { ...row, lines };
}

/** PURE — respons ListPage master BOM. */
export function readMasterBomPage(raw: unknown): MasterBomPage | null {
  return readListPage<MasterBomRow>(raw, readMasterBomRow);
}

/** PURE — baris hasil simpan (+ info sinkronisasi H1.5). */
export function readMasterBomSaved(raw: unknown): MasterBomSaved | null {
  const detail = readMasterBomDetail(raw);
  if (detail === null) return null;

  const extra = isRecord(raw) ? raw : {};

  return {
    ...detail,
    sync_record_id: readNullableNum(extra['sync_record_id']),
    task_id: readNullableStr(extra['task_id']),
    queued: readBool(extra['queued']),
  };
}

/** PURE — satu baris form → body baris backend (trim teks; id/odoo_id opsional). */
export function toMasterBomLineBody(line: MasterBomLineInput): MasterBomLineInput {
  return {
    ...(line.id === null || line.id === undefined ? {} : { id: line.id }),
    ...(line.odoo_id === null || line.odoo_id === undefined ? {} : { odoo_id: line.odoo_id }),
    product_id: line.product_id,
    qty: line.qty,
    uom_id: line.uom_id,
    sequence: line.sequence,
    notes: line.notes.trim(),
  };
}

/** PURE — input UI → body backend (trim teks; baris dipetakan satu per satu). */
export function toMasterBomBody(input: MasterBomInput): Record<string, unknown> {
  return {
    code: input.code.trim(),
    name: input.name.trim(),
    product_id: input.product_id,
    output_qty: input.output_qty,
    uom_id: input.uom_id,
    notes: input.notes.trim(),
    active: input.active,
    lines: input.lines.map(toMasterBomLineBody),
  };
}

function readSaved(res: ApiResponse<unknown>): MasterBomSaved {
  const saved = readMasterBomSaved(unwrap(res));
  if (saved === null) {
    throw new Error('Bentuk respons simpan BOM tidak dikenali.');
  }

  return saved;
}

/** Daftar BOM + filter (halaman memakai `next_cursor`/`has_more` untuk paging). */
export async function fetchBoms(
  client: ApiClient,
  params: MasterBomsParams = {},
): Promise<MasterBomPage> {
  return getParsed(client, buildMasterBomsPath(params), readMasterBomPage, 'daftar master BOM');
}

/** Detail satu BOM (termasuk `lines[]`). Gagal HTTP (404/403) → melempar pesan backend. */
export async function fetchBom(client: ApiClient, id: number): Promise<MasterBomDetail> {
  return getParsed(client, `${MASTER_BOMS_PATH}${id}/`, readMasterBomDetail, 'detail master BOM');
}

/** Buat BOM (POST) — backend membalas 201 + detail + `sync_record_id`/`task_id`. */
export async function createBom(
  client: ApiClient,
  input: MasterBomInput,
): Promise<MasterBomSaved> {
  return readSaved(await client.post<unknown>(MASTER_BOMS_PATH, toMasterBomBody(input)));
}

/** Ubah BOM (PUT) — `lines` menggantikan seluruh baris aktif. */
export async function updateBom(
  client: ApiClient,
  id: number,
  input: MasterBomInput,
): Promise<MasterBomSaved> {
  return readSaved(
    await client.request<unknown>(`${MASTER_BOMS_PATH}${id}/`, {
      method: 'PUT',
      body: toMasterBomBody(input),
    }),
  );
}

/** Nonaktifkan BOM (DELETE = **soft delete**; baris komponen tidak dihapus). */
export async function deleteBom(client: ApiClient, id: number): Promise<void> {
  unwrap(await client.request<unknown>(`${MASTER_BOMS_PATH}${id}/`, { method: 'DELETE' }));
}
