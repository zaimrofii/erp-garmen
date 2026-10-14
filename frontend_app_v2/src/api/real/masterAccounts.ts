// REAL - master Account / chart of accounts (H3.4). Endpoint: `/api/v1/master/accounts/`
//   GET `/master/accounts/`  +  GET `/master/accounts/<id>/`   → READ-ONLY
//
// Pemetaan UI ↔ backend (tidak ada shape yang dikarang):
//   * envelope ListPage `{rows, total_count, has_more, next_cursor}` (paging offset:
//     `limit` 1..200 default 50, `cursor` = offset);
//   * filter `?search=` (code/name icontains), `?account_type=` (18 tipe Odoo),
//     `?active=true|false`; urut `code`;
//   * baris `{id, odoo_id, code, name, account_type, account_type_label, reconcile, active}`.
//
// ⚠️ TIDAK ada POST/PUT/DELETE: chart of accounts = wewenang akuntan di Odoo (keputusan
// STEP 0 H3.4) ⇒ request tulis dibalas **405**. Dipakai dropdown akun di form Journal
// Entry; akun tanpa `odoo_id` tidak boleh dipakai (backend menolak saat CONFIRM).
import type { ApiClient } from '@/integrations/api-client';
import type { MasterAccountRow } from '@/types/master-account';
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
export const MASTER_ACCOUNTS_PATH = '/master/accounts/';

/** Batas paging backend (`master/api.py::DEFAULT_LIMIT` / `MAX_LIMIT`). */
export const ACCOUNTS_LIMIT_DEFAULT = 50;
export const ACCOUNTS_LIMIT_MAX = 200;

/** Respons 200 `GET /master/accounts/`. */
export type MasterAccountPage = ListPage<MasterAccountRow>;

export interface MasterAccountsParams {
  search?: string | null;
  /** Salah satu dari 18 `account.account.account_type` Odoo (backend → 400 kalau asing). */
  account_type?: string | null;
  /** `null`/`undefined` = tidak difilter (backend hanya memfilter kalau param dikirim). */
  active?: boolean | null;
  limit?: number | null;
  cursor?: number | null;
}

/** PURE — path + query `GET /master/accounts/` (hanya param terisi yang dikirim). */
export function buildMasterAccountsPath(params: MasterAccountsParams = {}): string {
  return buildQueryPath(MASTER_ACCOUNTS_PATH, {
    search: params.search,
    account_type: params.account_type,
    active: params.active === null || params.active === undefined ? null : params.active,
    limit: params.limit,
    cursor: params.cursor,
  });
}

/** PURE — satu baris mentah → `MasterAccountRow`; `null` kalau tanpa `id` angka. */
export function readMasterAccountRow(raw: unknown): MasterAccountRow | null {
  if (!isRecord(raw)) return null;

  const id = raw['id'];
  if (typeof id !== 'number' || !Number.isFinite(id)) return null;

  return {
    id,
    odoo_id: readNullableNum(raw['odoo_id']),
    code: readStr(raw['code']),
    name: readStr(raw['name']),
    account_type: readStr(raw['account_type']),
    account_type_label: readStr(raw['account_type_label']),
    reconcile: readBool(raw['reconcile']),
    active: readBool(raw['active']),
  };
}

/** PURE — respons `GET /master/accounts/` → ListPage akun. */
export function readMasterAccountPage(raw: unknown): MasterAccountPage | null {
  return readListPage(raw, readMasterAccountRow);
}

/** Daftar akun + filter (form Journal Entry memakai `?active=true&limit=200`). */
export async function fetchAccounts(
  client: ApiClient,
  params: MasterAccountsParams = {},
): Promise<MasterAccountPage> {
  return getParsed(
    client,
    buildMasterAccountsPath(params),
    readMasterAccountPage,
    'daftar master Account',
  );
}

/** Detail satu akun (404 → pesan backend dilempar). */
export async function fetchAccount(client: ApiClient, id: number): Promise<MasterAccountRow> {
  return getParsed(
    client,
    `${MASTER_ACCOUNTS_PATH}${id}/`,
    readMasterAccountRow,
    'detail master Account',
  );
}
