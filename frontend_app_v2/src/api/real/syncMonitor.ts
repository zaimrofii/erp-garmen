// REAL - monitoring SyncRecord (F15, revive F10). Endpoint: GET /sync/records/
//
// Backend `integrations/erp_sync/monitoring.py::SyncRecordListView` (FASE 4.4):
//   * `IsAuthenticated` → anonim **403** (dulu 404 sebelum Fase 4.4);
//   * envelope `{rows, total_count, has_next, next_cursor}` — paging offset
//     (`limit` 1..200 default 50, `cursor` = offset 0..100000);
//   * filter `stage` (`WIP|FG|SCRAP|INVOICE`) & `status`
//     (`PENDING|SENT|FAILED|DUPLICATE`), keduanya case-insensitive;
//   * baris: `{id, resource, resource_id, stage, status, attempts, last_error, erp_id,
//     sent_at, created_at}` (urut terbaru dulu: `-created_at`, `-id`).
import type { ApiClient } from '@/integrations/api-client';
import { unwrap } from '../client';

/** Path relatif terhadap `VITE_API_BASE_URL`. */
export const SYNC_RECORDS_PATH = '/sync/records/';

/** Batas paging backend (`monitoring.DEFAULT_LIMIT` / `MAX_LIMIT` / `MAX_OFFSET`). */
export const SYNC_LIMIT_DEFAULT = 50;
export const SYNC_LIMIT_MIN = 1;
export const SYNC_LIMIT_MAX = 200;
export const SYNC_CURSOR_MAX = 100000;

/** Tahap sync (`SyncStage`) + status kirim (`SyncStatus`). */
export const SYNC_STAGES = ['WIP', 'FG', 'SCRAP', 'INVOICE'] as const;
export const SYNC_STATUSES = ['PENDING', 'SENT', 'FAILED', 'DUPLICATE'] as const;
export type SyncStage = (typeof SYNC_STAGES)[number];
export type SyncStatus = (typeof SYNC_STATUSES)[number];

/** Satu baris `SyncRecord` (kontrak monitoring). */
export interface SyncRecordRow {
  id: number;
  resource: string;
  resource_id: string;
  stage: string;
  status: string;
  attempts: number;
  last_error: string | null;
  erp_id: string | null;
  sent_at: string | null;
  created_at: string | null;
}

/** Respons 200 `GET /sync/records/`. */
export interface SyncRecordPage {
  rows: SyncRecordRow[];
  total_count: number;
  has_next: boolean;
  next_cursor: number | null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function readNullableNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function readNullableString(value: unknown): string | null {
  return typeof value === 'string' ? value : null;
}

function readText(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

function readCount(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0;
}

/** PURE — stage yang valid (case-insensitive), atau `null`. */
export function parseSyncStage(value: unknown): SyncStage | null {
  if (typeof value !== 'string') return null;

  const candidate = value.trim().toUpperCase();

  return (SYNC_STAGES as readonly string[]).includes(candidate)
    ? (candidate as SyncStage)
    : null;
}

/** PURE — status yang valid (case-insensitive), atau `null`. */
export function parseSyncStatus(value: unknown): SyncStatus | null {
  if (typeof value !== 'string') return null;

  const candidate = value.trim().toUpperCase();

  return (SYNC_STATUSES as readonly string[]).includes(candidate)
    ? (candidate as SyncStatus)
    : null;
}

/** PURE — path + query `GET /sync/records/` (hanya parameter valid yang dikirim). */
export function buildSyncRecordsPath(
  params: {
    stage?: string | null;
    status?: string | null;
    limit?: number | null;
    cursor?: number | null;
  } = {},
): string {
  const qs = new URLSearchParams();
  const stage = parseSyncStage(params.stage);
  const status = parseSyncStatus(params.status);

  if (stage !== null) qs.set('stage', stage);
  if (status !== null) qs.set('status', status);
  if (params.limit != null) qs.set('limit', String(params.limit));
  if (params.cursor != null && params.cursor > 0) qs.set('cursor', String(params.cursor));

  const suffix = qs.toString();

  return suffix.length === 0 ? SYNC_RECORDS_PATH : `${SYNC_RECORDS_PATH}?${suffix}`;
}

/** PURE — satu baris mentah → `SyncRecordRow`; `null` kalau tanpa `id` angka. */
export function readSyncRecordRow(raw: unknown): SyncRecordRow | null {
  if (!isRecord(raw)) return null;

  const id = raw['id'];
  if (typeof id !== 'number' || !Number.isFinite(id)) return null;

  return {
    id,
    resource: readText(raw['resource']),
    resource_id: readText(raw['resource_id']),
    stage: readText(raw['stage']),
    status: readText(raw['status']),
    attempts: readCount(raw['attempts']),
    last_error: readNullableString(raw['last_error']),
    erp_id: readNullableString(raw['erp_id']),
    sent_at: readNullableString(raw['sent_at']),
    created_at: readNullableString(raw['created_at']),
  };
}

/**
 * PURE — respons mentah → `SyncRecordPage`; `null` kalau envelope tidak dikenali.
 * Menerima `has_next` (backend monitoring) maupun `has_more` (kontrak list lama).
 */
export function readSyncRecordPage(raw: unknown): SyncRecordPage | null {
  if (!isRecord(raw)) return null;

  const list = raw['rows'];
  if (!Array.isArray(list)) return null;

  const parsed: SyncRecordRow[] = [];
  for (const item of list) {
    const row = readSyncRecordRow(item);
    if (row !== null) parsed.push(row);
  }

  return {
    rows: parsed,
    total_count: readCount(raw['total_count']),
    has_next: raw['has_next'] === true || raw['has_more'] === true,
    next_cursor: readNullableNumber(raw['next_cursor']),
  };
}

/**
 * Baca daftar SyncRecord. Gagal HTTP (403 tanpa session / 400 param invalid) → melempar
 * pesan backend (`unwrap`); bentuk tak dikenal → melempar pesan jelas.
 */
export async function getSyncRecords(
  client: ApiClient,
  params: {
    stage?: string | null;
    status?: string | null;
    limit?: number | null;
    cursor?: number | null;
  } = {},
): Promise<SyncRecordPage> {
  const res = await client.get<unknown>(buildSyncRecordsPath(params));
  const parsed = readSyncRecordPage(unwrap(res));

  if (parsed === null) {
    throw new Error('Bentuk respons daftar SyncRecord tidak dikenali.');
  }

  return parsed;
}
