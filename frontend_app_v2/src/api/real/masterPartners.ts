// REAL - master Partner (H1.6). Endpoint: `/api/v1/master/partners/`
//   GET|POST `/master/partners/`  +  GET|PUT|DELETE `/master/partners/<id>/`
//
// Pemetaan UI ↔ backend (tidak ada shape yang dikarang):
//   * envelope ListPage `{rows, total_count, has_more, next_cursor}` (paging offset:
//     `limit` 1..200 default 50, `cursor` = offset);
//   * filter `?search=` (code/name/email/city icontains), `?is_customer=`,
//     `?is_vendor=`, `?active=true|false`; urut `code`;
//   * baris `{id, code, name, email, phone, city, address, npwp, is_customer,
//     is_vendor, is_company, customer_rank, supplier_rank, active, odoo_id,
//     created_at, updated_at}`; **detail** menambah `orders_count`;
//   * POST/PUT menambah `{sync_record_id, task_id, queued}` (push Odoo async) dan
//     membalas **detail** partner;
//   * **DELETE = soft delete** (`active=False`; baris tidak dihapus dari DB).
//
// Catatan: `ApiClient` hanya punya `get`/`post` — PUT/DELETE lewat `client.request()`.
import type { ApiClient, ApiResponse } from '@/integrations/api-client';
import type {
  MasterPartnerDetail,
  MasterPartnerInput,
  MasterPartnerRow,
  MasterPartnerSaved,
} from '@/types/master-partner';
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
export const MASTER_PARTNERS_PATH = '/master/partners/';

/** Batas paging backend (`master/api.py::DEFAULT_LIMIT` / `MAX_LIMIT`). */
export const PARTNERS_LIMIT_DEFAULT = 50;
export const PARTNERS_LIMIT_MAX = 200;

/** Respons 200 `GET /master/partners/`. */
export type MasterPartnerPage = ListPage<MasterPartnerRow>;

export interface MasterPartnersParams {
  search?: string | null;
  /** `null`/`undefined` = tidak difilter (backend hanya memfilter kalau param dikirim). */
  is_customer?: boolean | null;
  is_vendor?: boolean | null;
  active?: boolean | null;
  limit?: number | null;
  cursor?: number | null;
}

/** PURE — path + query `GET /master/partners/` (hanya param terisi yang dikirim). */
export function buildMasterPartnersPath(params: MasterPartnersParams = {}): string {
  return buildQueryPath(MASTER_PARTNERS_PATH, {
    search: params.search,
    is_customer:
      params.is_customer === null || params.is_customer === undefined ? null : params.is_customer,
    is_vendor:
      params.is_vendor === null || params.is_vendor === undefined ? null : params.is_vendor,
    active: params.active === null || params.active === undefined ? null : params.active,
    limit: params.limit,
    cursor: params.cursor,
  });
}

/** PURE — baris list mentah → `MasterPartnerRow`; `null` kalau tanpa `id` angka. */
export function readMasterPartnerRow(raw: unknown): MasterPartnerRow | null {
  if (!isRecord(raw)) return null;

  const id = raw['id'];
  if (typeof id !== 'number' || !Number.isFinite(id)) return null;

  return {
    id,
    code: readStr(raw['code']),
    name: readStr(raw['name']),
    email: readStr(raw['email']),
    phone: readStr(raw['phone']),
    city: readStr(raw['city']),
    address: readStr(raw['address']),
    npwp: readStr(raw['npwp']),
    is_customer: readBool(raw['is_customer']),
    is_vendor: readBool(raw['is_vendor']),
    is_company: readBool(raw['is_company']),
    customer_rank: readNum(raw['customer_rank']),
    supplier_rank: readNum(raw['supplier_rank']),
    active: readBool(raw['active']),
    odoo_id: readNullableNum(raw['odoo_id']),
    created_at: readNullableStr(raw['created_at']),
    updated_at: readNullableStr(raw['updated_at']),
  };
}

/** PURE — detail mentah → `MasterPartnerDetail` (menambah `orders_count`). */
export function readMasterPartnerDetail(raw: unknown): MasterPartnerDetail | null {
  const row = readMasterPartnerRow(raw);
  if (row === null) return null;

  const extra = isRecord(raw) ? raw : {};

  return { ...row, orders_count: readNum(extra['orders_count']) };
}

/** PURE — respons ListPage master Partner. */
export function readMasterPartnerPage(raw: unknown): MasterPartnerPage | null {
  return readListPage<MasterPartnerRow>(raw, readMasterPartnerRow);
}

/** PURE — baris hasil simpan (+ info sinkronisasi H1.6). */
export function readMasterPartnerSaved(raw: unknown): MasterPartnerSaved | null {
  const detail = readMasterPartnerDetail(raw);
  if (detail === null) return null;

  const extra = isRecord(raw) ? raw : {};

  return {
    ...detail,
    sync_record_id: readNullableNum(extra['sync_record_id']),
    task_id: readNullableStr(extra['task_id']),
    queued: readBool(extra['queued']),
  };
}

/** PURE — input UI → body backend (trim teks; NPWP digit-only). */
export function toMasterPartnerBody(input: MasterPartnerInput): Record<string, unknown> {
  return {
    code: input.code.trim(),
    name: input.name.trim(),
    email: input.email.trim(),
    phone: input.phone.trim(),
    city: input.city.trim(),
    address: input.address.trim(),
    npwp: input.npwp.trim(),
    is_customer: input.is_customer,
    is_vendor: input.is_vendor,
    is_company: input.is_company,
    active: input.active,
  };
}

function readSaved(res: ApiResponse<unknown>): MasterPartnerSaved {
  const saved = readMasterPartnerSaved(unwrap(res));
  if (saved === null) {
    throw new Error('Bentuk respons simpan partner tidak dikenali.');
  }

  return saved;
}

/** Daftar partner + filter (halaman memakai `next_cursor`/`has_more` untuk paging). */
export async function fetchPartners(
  client: ApiClient,
  params: MasterPartnersParams = {},
): Promise<MasterPartnerPage> {
  return getParsed(
    client,
    buildMasterPartnersPath(params),
    readMasterPartnerPage,
    'daftar master partner',
  );
}

/** Detail satu partner (+ `orders_count`). 404/403 → melempar pesan backend. */
export async function fetchPartner(
  client: ApiClient,
  id: number,
): Promise<MasterPartnerDetail> {
  return getParsed(
    client,
    `${MASTER_PARTNERS_PATH}${id}/`,
    readMasterPartnerDetail,
    'detail master partner',
  );
}

/** Buat partner (POST) — backend membalas 201 + detail + `sync_record_id`/`task_id`. */
export async function createPartner(
  client: ApiClient,
  input: MasterPartnerInput,
): Promise<MasterPartnerSaved> {
  return readSaved(await client.post<unknown>(MASTER_PARTNERS_PATH, toMasterPartnerBody(input)));
}

/** Ubah partner (PUT) — hanya field yang dikirim yang berubah. */
export async function updatePartner(
  client: ApiClient,
  id: number,
  input: MasterPartnerInput,
): Promise<MasterPartnerSaved> {
  return readSaved(
    await client.request<unknown>(`${MASTER_PARTNERS_PATH}${id}/`, {
      method: 'PUT',
      body: toMasterPartnerBody(input),
    }),
  );
}

/** Nonaktifkan partner (DELETE = **soft delete**; baris tidak dihapus dari DB). */
export async function deletePartner(client: ApiClient, id: number): Promise<void> {
  unwrap(await client.request<unknown>(`${MASTER_PARTNERS_PATH}${id}/`, { method: 'DELETE' }));
}
