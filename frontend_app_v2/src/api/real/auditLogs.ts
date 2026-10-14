// REAL - Audit Log Viewer (H5.5). Endpoint: `/api/v1/settings/audit/` (READ-ONLY)
//   GET `/settings/audit/`      → ListPage {rows, total_count, has_more, next_cursor}
//   GET `/settings/audit/<id>/` → {audit: {…row, payload, metadata, user_agent}}
//
// Backend `apps_industry/garment/api/settings/views.py::SettingsAuditView`:
//   * guard **ADMIN/OWNER** (`_require_admin`) → anonim & operator **403**;
//   * filter `user_id`, `action` (exact, atau **prefix** bila diakhiri titik),
//     `resource` (alias `resource_type`), `resource_id`, `result`, `date_from`,
//     `date_to` (inklusif; tanggal-saja = sampai akhir hari), `search`
//     (username/nama/action/resource);
//   * paging offset `limit` (1..200, default 50) + `cursor` (0..100000);
//   * rahasia di `payload`/`metadata` **sudah** di-mask `***` oleh backend
//     (`core/audit/services.py::mask_sensitive`) — UI tidak mem-mask ulang.
//
// Catatan: `ApiClient` hanya punya `get`/`post` — cukup, endpoint ini GET saja.
import type { ApiClient } from '@/integrations/api-client';
import type {
  AuditLogDetail,
  AuditLogFilters,
  AuditLogPage,
  AuditLogRow,
} from '@/types/audit-log';
import { AUDIT_LIMIT_MAX, AUDIT_CURSOR_MAX, AUDIT_RESULTS } from '@/types/audit-log';
import { unwrap } from '../client';
import { isRecord, readNum, readNullableStr, readStr } from './_shape';

/** Path relatif terhadap `VITE_API_BASE_URL` (`…/api/v1`). */
export const SETTINGS_AUDIT_PATH = '/settings/audit/';

/** Path detail satu audit. */
export function auditLogDetailPath(id: number): string {
  return `${SETTINGS_AUDIT_PATH}${String(id)}/`;
}

/** Nilai filter default (semua kosong = tanpa filter). */
export const EMPTY_AUDIT_FILTERS: AuditLogFilters = {
  user_id: '',
  action: '',
  resource: '',
  resource_id: '',
  result: '',
  date_from: '',
  date_to: '',
  search: '',
};

/** PURE — `result` valid (case-insensitive) atau `''`. */
export function parseAuditResult(value: unknown): string {
  if (typeof value !== 'string') return '';

  const candidate = value.trim().toUpperCase();

  return (AUDIT_RESULTS as readonly string[]).includes(candidate) ? candidate : '';
}

/** PURE — `user_id` angka ≥ 1 atau `null` (kosong/invalid = diabaikan). */
export function parseUserId(value: unknown): number | null {
  if (typeof value === 'number' && Number.isInteger(value) && value >= 1) return value;
  if (typeof value !== 'string') return null;

  const text = value.trim();
  if (text === '') return null;

  const parsed = Number(text);

  return Number.isInteger(parsed) && parsed >= 1 ? parsed : null;
}

/**
 * PURE — path + query `GET /settings/audit/` (hanya filter terisi yang dikirim).
 *
 * `limit`/`cursor` hanya ikut bila masuk rentang backend (kalau tidak, dibiarkan agar
 * server memakai default-nya — bukan error 400 karena UI).
 */
export function buildAuditLogsPath(
  filters: Partial<AuditLogFilters> = {},
  page: { limit?: number | null; cursor?: number | null } = {},
): string {
  const qs = new URLSearchParams();
  const merged = { ...EMPTY_AUDIT_FILTERS, ...filters };

  const userId = parseUserId(merged.user_id);
  if (userId !== null) qs.set('user_id', String(userId));

  const text = (value: string): string => value.trim();
  const result = parseAuditResult(merged.result);

  if (text(merged.action) !== '') qs.set('action', text(merged.action));
  if (text(merged.resource) !== '') qs.set('resource', text(merged.resource));
  if (text(merged.resource_id) !== '') qs.set('resource_id', text(merged.resource_id));
  if (result !== '') qs.set('result', result);
  if (text(merged.date_from) !== '') qs.set('date_from', text(merged.date_from));
  if (text(merged.date_to) !== '') qs.set('date_to', text(merged.date_to));
  if (text(merged.search) !== '') qs.set('search', text(merged.search));

  if (page.limit != null && page.limit >= 1 && page.limit <= AUDIT_LIMIT_MAX) {
    qs.set('limit', String(page.limit));
  }
  if (page.cursor != null && page.cursor > 0 && page.cursor <= AUDIT_CURSOR_MAX) {
    qs.set('cursor', String(page.cursor));
  }

  const suffix = qs.toString();

  return suffix.length === 0 ? SETTINGS_AUDIT_PATH : `${SETTINGS_AUDIT_PATH}?${suffix}`;
}

/** PURE — satu baris mentah → `AuditLogRow`; `null` kalau tanpa `id` angka. */
export function readAuditLogRow(raw: unknown): AuditLogRow | null {
  if (!isRecord(raw)) return null;

  const id = raw['id'];
  if (typeof id !== 'number' || !Number.isFinite(id)) return null;

  const userId = raw['user_id'];

  return {
    id,
    timestamp: readNullableStr(raw['timestamp']),
    user_id: typeof userId === 'number' && Number.isFinite(userId) ? userId : null,
    username: readNullableStr(raw['username']),
    full_name: readStr(raw['full_name']),
    action: readStr(raw['action']),
    resource: readStr(raw['resource']),
    resource_id: readStr(raw['resource_id']),
    result: readStr(raw['result']),
    request_id: readStr(raw['request_id']),
    ip_address: readNullableStr(raw['ip_address']),
    metadata_preview: readStr(raw['metadata_preview']),
  };
}

/**
 * PURE — respons mentah → `AuditLogPage`; `null` kalau `rows` bukan array.
 * Menerima `has_more` (H5.5) maupun `has_next` (kontrak monitoring lama).
 */
export function readAuditLogPage(raw: unknown): AuditLogPage | null {
  if (!isRecord(raw)) return null;

  const list = raw['rows'];
  if (!Array.isArray(list)) return null;

  const rows: AuditLogRow[] = [];
  for (const item of list) {
    const row = readAuditLogRow(item);
    if (row !== null) rows.push(row);
  }

  const cursor = raw['next_cursor'];

  return {
    rows,
    total_count: readNum(raw['total_count']),
    has_more: raw['has_more'] === true || raw['has_next'] === true,
    next_cursor:
      typeof cursor === 'number' && Number.isFinite(cursor) ? cursor : null,
  };
}

/** PURE — objek JSON bebas (payload/metadata) → `Record` (bukan objek = `{}`). */
export function readJsonObject(value: unknown): Record<string, unknown> {
  return isRecord(value) ? value : {};
}

/** PURE — respons detail mentah → `AuditLogDetail`; `null` kalau bentuk rusak. */
export function readAuditLogDetail(raw: unknown): AuditLogDetail | null {
  if (!isRecord(raw)) return null;

  const row = readAuditLogRow(raw);
  if (row === null) return null;

  return {
    ...row,
    payload: readJsonObject(raw['payload']),
    metadata: readJsonObject(raw['metadata']),
    user_agent: readStr(raw['user_agent']),
  };
}

/** Daftar audit (READ-ONLY). Gagal HTTP (403 non-admin) → melempar pesan backend. */
export async function fetchAuditLogs(
  client: ApiClient,
  filters: Partial<AuditLogFilters> = {},
  page: { limit?: number | null; cursor?: number | null } = {},
): Promise<AuditLogPage> {
  const page_data = readAuditLogPage(
    unwrap(await client.get<unknown>(buildAuditLogsPath(filters, page))),
  );
  if (page_data === null) {
    throw new Error('Bentuk respons daftar audit tidak dikenali.');
  }

  return page_data;
}

/** Detail satu audit (`{audit: …}` → `AuditLogDetail`). 404 → melempar. */
export async function fetchAuditLog(
  client: ApiClient,
  id: number,
): Promise<AuditLogDetail> {
  const raw = unwrap(await client.get<unknown>(auditLogDetailPath(id)));
  const detail = readAuditLogDetail(
    isRecord(raw) && raw['audit'] !== undefined ? raw['audit'] : raw,
  );
  if (detail === null) {
    throw new Error('Bentuk respons detail audit tidak dikenali.');
  }

  return detail;
}

