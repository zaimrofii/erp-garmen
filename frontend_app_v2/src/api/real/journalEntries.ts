// REAL - Journal Entry manual MES (H3.4). Endpoint: `/api/v1/finance/journal-entries/`
//   GET|POST `/finance/journal-entries/` + GET|PUT|DELETE `…/<id>/`
//   POST `…/<id>/confirm/` | `…/<id>/done/` | `…/<id>/cancel/`
//
// Pemetaan UI ↔ backend (tidak ada shape yang dikarang):
//   * envelope ListPage `{rows, total_count, has_more, next_cursor}` (paging offset);
//   * filter `?search=` (kode/ref/memo/kode & nama journal), `?state=`, `?journal_id=`,
//     `?date_from=`/`?date_to=` (ISO `YYYY-MM-DD`, `entry_date`);
//   * baris `{id, code, journal_id, journal_code, journal_name, journal_type, entry_date,
//     ref, memo, total_debit, total_credit, state, odoo_id, …}`;
//   * detail menambah `{lines[], line_count, odoo_sync_status, odoo_sync_error,
//     allowed_actions}`; baris = `{id, account_id, account_code, account_name, partner_id,
//     partner_name, name, debit, credit}`;
//   * POST/PUT/aksi menambah `{sync_record_id, task_id, queued}`.
//
// ⚠️ Keputusan STEP 0 H3.4 yang terlihat dari sisi UI:
//   * entry manual **hanya** boleh di journal `general` (backend menolak dengan 400);
//   * `journal_id` & setiap `account_id` wajib sudah punya `odoo_id` (hasil pull) —
//     kalau belum, CONFIRM dibalas 400 (entry tetap DRAFT);
//   * MES **tidak mem-posting**: entry dikirim sebagai `account.move` `move_type='entry'`
//     **draft**; akuntan Odoo yang mem-posting & merekonsiliasi.
//
// Catatan: `ApiClient` hanya punya `get`/`post` — PUT/DELETE lewat `client.request()`.
import type { ApiClient, ApiResponse } from '@/integrations/api-client';
import type {
  JournalEntryDetail,
  JournalEntryInput,
  JournalEntryLineInput,
  JournalEntryLineRow,
  JournalEntryRow,
  JournalEntrySaved,
  JournalEntryState,
} from '@/types/journal-entry';
import { unwrap } from '../client';
import {
  buildQueryPath,
  getParsed,
  isRecord,
  readListPage,
  readNullableNum,
  readNullableStr,
  readNum,
  readStr,
  type ListPage,
} from './_shape';

/** Path relatif terhadap `VITE_API_BASE_URL` (`…/api/v1`). */
export const JOURNAL_ENTRIES_PATH = '/finance/journal-entries/';

/** Batas paging backend (`garment/api/journal_entries.py::DEFAULT_LIMIT`/`MAX_LIMIT`). */
export const JOURNAL_ENTRIES_LIMIT_DEFAULT = 50;
export const JOURNAL_ENTRIES_LIMIT_MAX = 200;

/** Aksi transisi yang dikenal backend. */
export const JOURNAL_ENTRY_ACTIONS = ['confirm', 'done', 'cancel'] as const;
export type JournalEntryAction = (typeof JOURNAL_ENTRY_ACTIONS)[number];

/** Respons 200 `GET /finance/journal-entries/`. */
export type JournalEntryPage = ListPage<JournalEntryRow>;

export interface JournalEntriesParams {
  search?: string | null;
  state?: JournalEntryState | null;
  journal_id?: number | null;
  /** ISO `YYYY-MM-DD` (backend → 400 kalau bukan ISO). */
  date_from?: string | null;
  date_to?: string | null;
  limit?: number | null;
  cursor?: number | null;
}

/** PURE — path + query `GET /finance/journal-entries/`. */
export function buildJournalEntriesPath(params: JournalEntriesParams = {}): string {
  return buildQueryPath(JOURNAL_ENTRIES_PATH, {
    search: params.search,
    state: params.state,
    journal_id: params.journal_id,
    date_from: params.date_from,
    date_to: params.date_to,
    limit: params.limit,
    cursor: params.cursor,
  });
}

/** PURE — path aksi transisi (`confirm`/`done`/`cancel`). */
export function journalEntryActionPath(id: number, action: JournalEntryAction): string {
  return `${JOURNAL_ENTRIES_PATH}${id}/${action}/`;
}

/** PURE — state backend yang sah; lain → `DRAFT` (defensif). */
export function readJournalEntryState(value: unknown): JournalEntryState {
  return value === 'CONFIRMED' || value === 'SENT' || value === 'DONE' || value === 'CANCELLED'
    ? value
    : 'DRAFT';
}

/** PURE — satu baris jurnal mentah → `JournalEntryLineRow`; `null` tanpa `id` angka. */
export function readJournalEntryLineRow(raw: unknown): JournalEntryLineRow | null {
  if (!isRecord(raw)) return null;

  const id = raw['id'];
  if (typeof id !== 'number' || !Number.isFinite(id)) return null;

  return {
    id,
    account_id: readNum(raw['account_id']),
    account_code: readNullableStr(raw['account_code']),
    account_name: readNullableStr(raw['account_name']),
    partner_id: readNullableNum(raw['partner_id']),
    partner_name: readNullableStr(raw['partner_name']),
    name: readStr(raw['name']),
    debit: readStr(raw['debit']),
    credit: readStr(raw['credit']),
  };
}

/** PURE — satu baris mentah → `JournalEntryRow`; `null` kalau tanpa `id` angka. */
export function readJournalEntryRow(raw: unknown): JournalEntryRow | null {
  if (!isRecord(raw)) return null;

  const id = raw['id'];
  if (typeof id !== 'number' || !Number.isFinite(id)) return null;

  return {
    id,
    code: readStr(raw['code']),
    journal_id: readNum(raw['journal_id']),
    journal_code: readNullableStr(raw['journal_code']),
    journal_name: readNullableStr(raw['journal_name']),
    journal_type: readStr(raw['journal_type']),
    entry_date: readNullableStr(raw['entry_date']),
    ref: readStr(raw['ref']),
    memo: readStr(raw['memo']),
    total_debit: readStr(raw['total_debit']),
    total_credit: readStr(raw['total_credit']),
    state: readJournalEntryState(raw['state']),
    odoo_id: readNullableNum(raw['odoo_id']),
    created_at: readNullableStr(raw['created_at']),
    updated_at: readNullableStr(raw['updated_at']),
  };
}

/** PURE — respons `GET /finance/journal-entries/` → ListPage entry. */
export function readJournalEntryPage(raw: unknown): JournalEntryPage | null {
  return readListPage(raw, readJournalEntryRow);
}

/** PURE — `lines[]` mentah → baris jurnal (entri tanpa `id` dibuang). */
export function readJournalEntryLines(raw: unknown): JournalEntryLineRow[] {
  if (!Array.isArray(raw)) return [];

  const lines: JournalEntryLineRow[] = [];
  for (const line of raw) {
    const parsed = readJournalEntryLineRow(line);
    if (parsed !== null) lines.push(parsed);
  }

  return lines;
}

/** PURE — `allowed_actions` backend → daftar string (state target). */
export function readAllowedActions(raw: unknown): string[] {
  if (!Array.isArray(raw)) return [];

  return raw.filter((value): value is string => typeof value === 'string');
}

/** PURE — satu detail mentah → `JournalEntryDetail`; `null` kalau baris dasarnya rusak. */
export function readJournalEntryDetail(raw: unknown): JournalEntryDetail | null {
  const row = readJournalEntryRow(raw);
  if (row === null || !isRecord(raw)) return null;

  return {
    ...row,
    lines: readJournalEntryLines(raw['lines']),
    line_count: readNum(raw['line_count']),
    odoo_sync_status: readNullableStr(raw['odoo_sync_status']),
    odoo_sync_error: readNullableStr(raw['odoo_sync_error']),
    allowed_actions: readAllowedActions(raw['allowed_actions']),
  };
}

/** PURE — respons simpan (POST/PUT/aksi) → `JournalEntrySaved`; `null` kalau rusak. */
export function readJournalEntrySaved(raw: unknown): JournalEntrySaved | null {
  const detail = readJournalEntryDetail(raw);
  if (detail === null || !isRecord(raw)) return null;

  return {
    ...detail,
    sync_record_id: readNullableNum(raw['sync_record_id']),
    task_id: readNullableStr(raw['task_id']),
    queued: raw['queued'] === true,
  };
}

/** PURE — satu baris form → body backend (baris tanpa akun dibuang di `lib/journal-entry`). */
export function toJournalEntryLineBody(line: JournalEntryLineInput): Record<string, unknown> {
  const body: Record<string, unknown> = {
    account_id: line.account_id,
    debit: line.debit,
    credit: line.credit,
  };

  if (line.partner_id !== undefined && line.partner_id !== null) {
    body['partner_id'] = line.partner_id;
  }
  if (line.name !== undefined && line.name.trim() !== '') {
    body['name'] = line.name.trim();
  }

  return body;
}

/** PURE — input UI → body backend (angka apa adanya; teks di-trim). */
export function toJournalEntryBody(input: JournalEntryInput): Record<string, unknown> {
  const body: Record<string, unknown> = {
    journal_id: input.journal_id,
    entry_date: input.entry_date,
    lines: input.lines.map(toJournalEntryLineBody),
  };

  if (input.ref !== undefined) body['ref'] = input.ref.trim();
  if (input.memo !== undefined) body['memo'] = input.memo.trim();
  if (input.notes !== undefined) body['notes'] = input.notes;

  return body;
}

function readSaved(res: ApiResponse<unknown>): JournalEntrySaved {
  const saved = readJournalEntrySaved(unwrap(res));
  if (saved === null) {
    throw new Error('Bentuk respons simpan journal entry tidak dikenali.');
  }

  return saved;
}

/** Daftar journal entry + filter (halaman memakai `next_cursor`/`has_more`). */
export async function fetchJournalEntries(
  client: ApiClient,
  params: JournalEntriesParams = {},
): Promise<JournalEntryPage> {
  return getParsed(
    client,
    buildJournalEntriesPath(params),
    readJournalEntryPage,
    'daftar journal entry',
  );
}

/** Detail journal entry. Gagal HTTP (404/403) → melempar pesan backend. */
export async function fetchJournalEntry(
  client: ApiClient,
  id: number,
): Promise<JournalEntryDetail> {
  return getParsed(
    client,
    `${JOURNAL_ENTRIES_PATH}${id}/`,
    readJournalEntryDetail,
    'detail journal entry',
  );
}

/** Buat entry (POST) — backend menegakkan balance & ≥ 2 baris. */
export async function createJournalEntry(
  client: ApiClient,
  input: JournalEntryInput,
): Promise<JournalEntrySaved> {
  return readSaved(await client.post<unknown>(JOURNAL_ENTRIES_PATH, toJournalEntryBody(input)));
}

/** Ubah entry (PUT) — DRAFT-only; baris jurnal diganti menyatu. */
export async function updateJournalEntry(
  client: ApiClient,
  id: number,
  input: JournalEntryInput,
): Promise<JournalEntrySaved> {
  return readSaved(
    await client.request<unknown>(`${JOURNAL_ENTRIES_PATH}${id}/`, {
      method: 'PUT',
      body: toJournalEntryBody(input),
    }),
  );
}

/** Hapus entry (DELETE) — DRAFT-only (hard delete di backend). */
export async function deleteJournalEntry(client: ApiClient, id: number): Promise<void> {
  unwrap(await client.request<unknown>(`${JOURNAL_ENTRIES_PATH}${id}/`, { method: 'DELETE' }));
}

/** Transisi entry (`confirm` → enqueue push draft ke Odoo, `done`, `cancel`). */
export async function actJournalEntry(
  client: ApiClient,
  id: number,
  action: JournalEntryAction,
): Promise<JournalEntrySaved> {
  return readSaved(await client.post<unknown>(journalEntryActionPath(id, action), {}));
}
