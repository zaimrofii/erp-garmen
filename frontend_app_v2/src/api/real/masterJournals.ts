// REAL - master Journal (H3.4). Endpoint: `/api/v1/master/journals/`
//   GET `/master/journals/`  +  GET `/master/journals/<id>/`   → READ-ONLY
//
// Pemetaan UI ↔ backend (tidak ada shape yang dikarang):
//   * envelope ListPage `{rows, total_count, has_more, next_cursor}` (paging offset);
//   * filter `?search=` (code/name icontains), `?type=general|sale|purchase|bank|cash`,
//     `?active=true|false`; urut `code`;
//   * baris `{id, odoo_id, code, name, journal_type, journal_type_label, is_general, active}`.
//
// ⚠️ TIDAK ada POST/PUT/DELETE (journal = konfigurasi akuntansi Odoo; 405 untuk tulis).
// Dipakai dropdown journal di form Journal Entry H3.4 (`?type=general` — entry manual
// HANYA boleh di journal general; keputusan STEP 0).
import type { ApiClient } from '@/integrations/api-client';
import type { MasterJournalRow } from '@/types/master-journal';
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
export const MASTER_JOURNALS_PATH = '/master/journals/';

/** Batas paging backend (`master/api.py::DEFAULT_LIMIT` / `MAX_LIMIT`). */
export const JOURNALS_LIMIT_DEFAULT = 50;
export const JOURNALS_LIMIT_MAX = 200;

/** Respons 200 `GET /master/journals/`. */
export type MasterJournalPage = ListPage<MasterJournalRow>;

export interface MasterJournalsParams {
  search?: string | null;
  /** `general|sale|purchase|bank|cash` (backend → 400 kalau di luar `Journal.JournalType`). */
  type?: string | null;
  active?: boolean | null;
  limit?: number | null;
  cursor?: number | null;
}

/** PURE — path + query `GET /master/journals/` (hanya param terisi yang dikirim). */
export function buildMasterJournalsPath(params: MasterJournalsParams = {}): string {
  return buildQueryPath(MASTER_JOURNALS_PATH, {
    search: params.search,
    type: params.type,
    active: params.active === null || params.active === undefined ? null : params.active,
    limit: params.limit,
    cursor: params.cursor,
  });
}

/** PURE — satu baris mentah → `MasterJournalRow`; `null` kalau tanpa `id` angka. */
export function readMasterJournalRow(raw: unknown): MasterJournalRow | null {
  if (!isRecord(raw)) return null;

  const id = raw['id'];
  if (typeof id !== 'number' || !Number.isFinite(id)) return null;

  return {
    id,
    odoo_id: readNullableNum(raw['odoo_id']),
    code: readStr(raw['code']),
    name: readStr(raw['name']),
    journal_type: readStr(raw['journal_type']),
    journal_type_label: readStr(raw['journal_type_label']),
    is_general: readBool(raw['is_general']),
    active: readBool(raw['active']),
  };
}

/** PURE — respons `GET /master/journals/` → ListPage journal. */
export function readMasterJournalPage(raw: unknown): MasterJournalPage | null {
  return readListPage(raw, readMasterJournalRow);
}

/** Daftar journal + filter (form Journal Entry memakai `?type=general&active=true`). */
export async function fetchJournals(
  client: ApiClient,
  params: MasterJournalsParams = {},
): Promise<MasterJournalPage> {
  return getParsed(
    client,
    buildMasterJournalsPath(params),
    readMasterJournalPage,
    'daftar master Journal',
  );
}

/** Detail satu journal (404 → pesan backend dilempar). */
export async function fetchJournal(client: ApiClient, id: number): Promise<MasterJournalRow> {
  return getParsed(
    client,
    `${MASTER_JOURNALS_PATH}${id}/`,
    readMasterJournalRow,
    'detail master Journal',
  );
}
