// REAL - defect QC (F2C.2). Endpoint: GET /api/v1/quality/defects/
//
// Backend `monitoring.QualityDefectsView` (B4 + G3). ListPage.
import type { ApiClient } from '@/integrations/api-client';
import { unwrap } from '../client';

/** Path relatif terhadap `VITE_API_BASE_URL`. */
export const QUALITY_DEFECTS_PATH = '/quality/defects/';

export interface DefectEntry {
  type: string;
  qty: number;
  location: string | null;
  note: string;
}

export interface DefectRow {
  bundle_code: string | null;
  wc_code: string | null;
  defect_type: string;
  qty: number;
  reason: string;
  recorded_at: string | null;
  location: string | null;
  action: string | null;
  defect_entries: DefectEntry[];
}

export interface DefectPage {
  rows: DefectRow[];
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

function readStr(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

function readNullableStr(value: unknown): string | null {
  return typeof value === 'string' ? value : null;
}

function readEntries(value: unknown): DefectEntry[] {
  if (!Array.isArray(value)) return [];
  return value
    .filter(isRecord)
    .map((row) => ({
      type: readStr(row['type']),
      qty: readNum(row['qty']),
      location: readNullableStr(row['location']),
      note: readStr(row['note']),
    }));
}

/** PURE — satu baris defect mentah → `DefectRow`. */
export function readDefectRow(raw: unknown): DefectRow | null {
  if (!isRecord(raw)) return null;
  return {
    bundle_code: readNullableStr(raw['bundle_code']),
    wc_code: readNullableStr(raw['wc_code']),
    defect_type: readStr(raw['defect_type']),
    qty: readNum(raw['qty']),
    reason: readStr(raw['reason']),
    recorded_at: readNullableStr(raw['recorded_at']),
    location: readNullableStr(raw['location']),
    action: readNullableStr(raw['action']),
    defect_entries: readEntries(raw['defect_entries']),
  };
}

/** PURE — respons mentah → `DefectPage`; `null` kalau `rows` bukan array. */
export function readDefectPage(raw: unknown): DefectPage | null {
  if (!isRecord(raw)) return null;
  const rows = raw['rows'];
  if (!Array.isArray(rows)) return null;

  const parsed: DefectRow[] = [];
  for (const row of rows) {
    const item = readDefectRow(row);
    if (item !== null) parsed.push(item);
  }

  return {
    rows: parsed,
    total_count: readNum(raw['total_count']),
    has_more: raw['has_more'] === true,
    next_cursor: typeof raw['next_cursor'] === 'number' ? raw['next_cursor'] : null,
  };
}

/** PURE — path + query `GET /quality/defects/`. */
export function buildQualityDefectsPath(
  params: { limit?: number | null; cursor?: number | null; wc?: string | null } = {},
): string {
  const qs = new URLSearchParams();
  if (params.limit != null) qs.set('limit', String(params.limit));
  if (params.cursor != null && params.cursor > 0) qs.set('cursor', String(params.cursor));
  const wc = params.wc?.trim();
  if (wc) qs.set('wc', wc);
  const suffix = qs.toString();
  return suffix.length === 0 ? QUALITY_DEFECTS_PATH : `${QUALITY_DEFECTS_PATH}?${suffix}`;
}

/** Baca daftar defect (rows saja). Gagal HTTP → melempar (`unwrap`). */
export async function fetchDefects(
  client: ApiClient,
  params: { limit?: number | null; cursor?: number | null; wc?: string | null } = {},
): Promise<DefectRow[]> {
  const res = await client.get<unknown>(buildQualityDefectsPath(params));
  const page = readDefectPage(unwrap(res));

  if (page === null) {
    throw new Error('Bentuk respons daftar defect tidak dikenali.');
  }

  return page.rows;
}
