// REAL - Currency (H5.2). Endpoint: `/api/v1/settings/currencies/`
//   GET|POST `/settings/currencies/` + GET|PUT|DELETE `/settings/currencies/<id>/`
//   GET `/settings/currencies/default/` + POST `/settings/currencies/<id>/set-default/`
//
// Pemetaan UI ↔ backend (tidak ada shape yang dikarang):
//   * envelope ListPage `{rows, total_count, has_more, next_cursor}` (paging offset:
//     `limit` 1..200 default 50, `cursor` = offset);
//   * filter `?search=` (code/name/symbol icontains), `?active=true|false`; urut `code`;
//   * baris `{id, code, name, symbol, rate, is_default, is_active, odoo_id}`;
//   * **POST** 201 → baris baru; **PUT** 200 → baris terbaru; **DELETE** 200 + body
//     `{id, is_active, deleted, is_default, sync_record_id}` (soft delete);
//   * **MES-only**: tanpa `task_id`/`queued` (ledger `SKIPPED`, tidak ada push Odoo).
//
// Catatan: `ApiClient` hanya punya `get`/`post` — PUT/DELETE lewat `client.request()`.
import type { ApiClient } from '@/integrations/api-client';
import type {
  MasterCurrencyCreateInput,
  MasterCurrencyDeleted,
  MasterCurrencyInput,
  MasterCurrencyRow,
} from '@/types/master-currency';
import { unwrap } from '../client';
import {
  buildQueryPath,
  getParsed,
  isRecord,
  readBool,
  readListPage,
  readNullableNum,
  readStr,
  type ListPage,
} from './_shape';

/** Path relatif terhadap `VITE_API_BASE_URL` (`…/api/v1`). */
export const SETTINGS_CURRENCIES_PATH = '/settings/currencies/';

/** Path mata uang default MES. */
export const CURRENCIES_DEFAULT_PATH = `${SETTINGS_CURRENCIES_PATH}default/`;

/** Batas paging backend (`settings/views.py::DEFAULT_LIMIT` / `MAX_LIMIT`). */
export const CURRENCIES_LIMIT_DEFAULT = 50;
export const CURRENCIES_LIMIT_MAX = 200;

export type MasterCurrencyPage = ListPage<MasterCurrencyRow>;

export interface MasterCurrenciesParams {
  search?: string | null;
  active?: boolean | null;
  limit?: number | null;
  cursor?: number | null;
}

/** URL detail satu mata uang (GET/PUT/DELETE). */
export function currencyDetailPath(id: number): string {
  return `${SETTINGS_CURRENCIES_PATH}${id}/`;
}

/** URL aksi jadikan-default satu mata uang. */
export function currencySetDefaultPath(id: number): string {
  return `${SETTINGS_CURRENCIES_PATH}${id}/set-default/`;
}

/** PURE — path + query `GET /settings/currencies/` (hanya param terisi dikirim). */
export function buildMasterCurrenciesPath(params: MasterCurrenciesParams = {}): string {
  return buildQueryPath(SETTINGS_CURRENCIES_PATH, {
    search: params.search,
    active: params.active === null || params.active === undefined ? null : params.active,
    limit: params.limit,
    cursor: params.cursor,
  });
}

/** PURE — satu baris mentah → `MasterCurrencyRow`; `null` kalau tanpa `id` angka. */
export function readMasterCurrencyRow(raw: unknown): MasterCurrencyRow | null {
  if (!isRecord(raw)) return null;

  const id = raw['id'];
  if (typeof id !== 'number' || !Number.isFinite(id)) return null;

  return {
    id,
    code: readStr(raw['code']),
    name: readStr(raw['name']),
    symbol: readStr(raw['symbol']),
    rate: readNullableNum(raw['rate']),
    is_default: readBool(raw['is_default']),
    is_active: readBool(raw['is_active']),
    odoo_id: readNullableNum(raw['odoo_id']),
  };
}

/** PURE — respons ListPage Currency. */
export function readMasterCurrencyPage(raw: unknown): MasterCurrencyPage | null {
  return readListPage<MasterCurrencyRow>(raw, readMasterCurrencyRow);
}

/** PURE — respons `GET …/default/` (`{currency: {…}|null}`) → baris atau `null`. */
export function readMasterCurrencyDefault(raw: unknown): MasterCurrencyRow | null {
  if (!isRecord(raw)) return null;

  return readMasterCurrencyRow(raw['currency']);
}

/** PURE — respons `DELETE` (200 + body) → jejak soft delete. */
export function readMasterCurrencyDeleted(raw: unknown): MasterCurrencyDeleted | null {
  if (!isRecord(raw)) return null;

  const id = raw['id'];
  if (typeof id !== 'number' || !Number.isFinite(id)) return null;

  return {
    id,
    is_active: readBool(raw['is_active']),
    deleted: readBool(raw['deleted']),
    is_default: readBool(raw['is_default']),
    sync_record_id: readNullableNum(raw['sync_record_id']),
  };
}

/** PURE — body `POST` (code auto-upper & trim; field opsional diisi bila ada). */
export function toMasterCurrencyCreateBody(
  input: MasterCurrencyCreateInput,
): Record<string, unknown> {
  const body: Record<string, unknown> = {
    code: input.code.trim().toUpperCase(),
    name: input.name.trim(),
    symbol: input.symbol?.trim() ?? '',
  };
  if (input.rate !== undefined && input.rate !== null) body['rate'] = input.rate;
  if (input.is_default !== undefined) body['is_default'] = input.is_default;

  return body;
}

/** PURE — body `PUT` (hanya field yang dikirim; `code` auto-upper & di-trim). */
export function toMasterCurrencyUpdateBody(
  input: MasterCurrencyInput,
): Record<string, unknown> {
  const body: Record<string, unknown> = {};
  if (input.code !== undefined) body['code'] = input.code.trim().toUpperCase();
  if (input.name !== undefined) body['name'] = input.name.trim();
  if (input.symbol !== undefined) body['symbol'] = input.symbol.trim();
  if (input.rate !== undefined) body['rate'] = input.rate;
  if (input.active !== undefined) body['active'] = input.active;
  if (input.is_default !== undefined) body['is_default'] = input.is_default;

  return body;
}

/** List mata uang. Gagal HTTP → melempar. */
export async function fetchCurrencies(
  client: ApiClient,
  params: MasterCurrenciesParams = {},
): Promise<MasterCurrencyPage> {
  return getParsed(
    client,
    buildMasterCurrenciesPath(params),
    readMasterCurrencyPage,
    'daftar mata uang',
  );
}

/** Detail satu mata uang. Gagal HTTP → melempar. */
export async function fetchCurrency(
  client: ApiClient,
  id: number,
): Promise<MasterCurrencyRow> {
  return getParsed(client, currencyDetailPath(id), readMasterCurrencyRow, 'detail mata uang');
}

/**
 * Mata uang default MES (`null` = belum ada mata uang sama sekali).
 *
 * Backend membalas `{"currency": null}` (200), jadi `getParsed` TIDAK dipakai di sini
 * (helper itu melempar untuk hasil `null`) — pola `fetchDefaultTax` (H3.6).
 */
export async function fetchDefaultCurrency(
  client: ApiClient,
): Promise<MasterCurrencyRow | null> {
  return readMasterCurrencyDefault(unwrap(await client.get<unknown>(CURRENCIES_DEFAULT_PATH)));
}

/** Buat mata uang (POST, ADMIN/OWNER) → baris baru. */
export async function createCurrency(
  client: ApiClient,
  input: MasterCurrencyCreateInput,
): Promise<MasterCurrencyRow> {
  const row = readMasterCurrencyRow(
    unwrap(
      await client.post<unknown>(
        SETTINGS_CURRENCIES_PATH,
        toMasterCurrencyCreateBody(input),
      ),
    ),
  );
  if (row === null) {
    throw new Error('Bentuk respons buat mata uang tidak dikenali.');
  }

  return row;
}

/** Ubah mata uang (PUT, ADMIN/OWNER) → baris terbaru. */
export async function updateCurrency(
  client: ApiClient,
  id: number,
  input: MasterCurrencyInput,
): Promise<MasterCurrencyRow> {
  const row = readMasterCurrencyRow(
    unwrap(
      await client.request<unknown>(currencyDetailPath(id), {
        method: 'PUT',
        body: toMasterCurrencyUpdateBody(input),
      }),
    ),
  );
  if (row === null) {
    throw new Error('Bentuk respons ubah mata uang tidak dikenali.');
  }

  return row;
}

/**
 * Nonaktifkan mata uang (DELETE = **soft delete**; 200 + body).
 *
 * Backend menolak **400** kalau mata uang masih dipakai: `is_default` (default MES),
 * kode terlindungi (IDR/USD), atau baris hasil pull I1 (`odoo_id`).
 */
export async function deleteCurrency(
  client: ApiClient,
  id: number,
): Promise<MasterCurrencyDeleted> {
  const deleted = readMasterCurrencyDeleted(
    unwrap(await client.request<unknown>(currencyDetailPath(id), { method: 'DELETE' })),
  );
  if (deleted === null) {
    throw new Error('Bentuk respons nonaktifkan mata uang tidak dikenali.');
  }

  return deleted;
}

/** Jadikan mata uang default MES (POST `set-default/`) — atomik, maksimal satu. */
export async function setDefaultCurrency(
  client: ApiClient,
  id: number,
): Promise<MasterCurrencyRow> {
  const row = readMasterCurrencyRow(
    unwrap(await client.post<unknown>(currencySetDefaultPath(id), {})),
  );
  if (row === null) {
    throw new Error('Bentuk respons mata uang default tidak dikenali.');
  }

  return row;
}

