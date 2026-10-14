// REAL - riwayat rework QC (F2C.2). Endpoint: GET /api/v1/quality/rework/
//
// Backend `monitoring.QualityReworkView` (B6). ListPage (`CycleInstance` QC_REWORK).
import type { ApiClient } from '@/integrations/api-client';
import { unwrap } from '../client';

/** Path relatif terhadap `VITE_API_BASE_URL`. */
export const QUALITY_REWORK_PATH = '/quality/rework/';

export interface ReworkRow {
  bundle_code: string | null;
  /** SELALU `null` (backend tidak menyimpan step — `CycleInstance` tanpa metadata). */
  from_step: string | null;
  to_step: string | null;
  iteration: number;
  started_at: string | null;
  closed_at: string | null;
  is_open: boolean;
}

export interface ReworkPage {
  rows: ReworkRow[];
  total_count: number;
  has_more: boolean;
  next_cursor: number | null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function readNum(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0;
}

function readNullableStr(value: unknown): string | null {
  return typeof value === 'string' ? value : null;
}

/** PURE — satu baris rework mentah → `ReworkRow`. */
export function readReworkRow(raw: unknown): ReworkRow | null {
  if (!isRecord(raw)) return null;
  return {
    bundle_code: readNullableStr(raw['bundle_code']),
    from_step: readNullableStr(raw['from_step']),
    to_step: readNullableStr(raw['to_step']),
    iteration: readNum(raw['iteration']),
    started_at: readNullableStr(raw['started_at']),
    closed_at: readNullableStr(raw['closed_at']),
    is_open: raw['is_open'] === true,
  };
}

/** PURE — respons mentah → `ReworkPage`; `null` kalau `rows` bukan array. */
export function readReworkPage(raw: unknown): ReworkPage | null {
  if (!isRecord(raw)) return null;
  const rows = raw['rows'];
  if (!Array.isArray(rows)) return null;

  const parsed: ReworkRow[] = [];
  for (const row of rows) {
    const item = readReworkRow(row);
    if (item !== null) parsed.push(item);
  }

  return {
    rows: parsed,
    total_count: readNum(raw['total_count']),
    has_more: raw['has_more'] === true,
    next_cursor: typeof raw['next_cursor'] === 'number' ? raw['next_cursor'] : null,
  };
}

/** PURE — path + query `GET /quality/rework/`. */
export function buildQualityReworkPath(
  params: { limit?: number | null; cursor?: number | null; open?: boolean | null } = {},
): string {
  const qs = new URLSearchParams();
  if (params.limit != null) qs.set('limit', String(params.limit));
  if (params.cursor != null && params.cursor > 0) qs.set('cursor', String(params.cursor));
  if (params.open != null) qs.set('open', String(params.open));
  const suffix = qs.toString();
  return suffix.length === 0 ? QUALITY_REWORK_PATH : `${QUALITY_REWORK_PATH}?${suffix}`;
}

/** Baca daftar rework (rows saja). Gagal HTTP → melempar (`unwrap`). */
export async function fetchRework(
  client: ApiClient,
  params: { limit?: number | null; cursor?: number | null; open?: boolean | null } = {},
): Promise<ReworkRow[]> {
  const res = await client.get<unknown>(buildQualityReworkPath(params));
  const page = readReworkPage(unwrap(res));

  if (page === null) {
    throw new Error('Bentuk respons daftar rework tidak dikenali.');
  }

  return page.rows;
}
