// REAL - laporan WIP (F2C.2). Endpoint: GET /api/v1/reports/wip/
//
// Backend `monitoring.ReportsWipView` (B16 + G4). Non-ListPage.
// `group_by=none` → response TANPA `rows` (di sini `rows` = []).
import type { ApiClient } from '@/integrations/api-client';
import { unwrap } from '../client';

/** Path relatif terhadap `VITE_API_BASE_URL`. */
export const REPORTS_WIP_PATH = '/reports/wip/';

export interface WipTrendPoint {
  date: string;
  value: number;
}

export interface WipSeriesPoint {
  x: string;
  y: number;
}

export interface WipRow {
  wc_code: string;
  wc_name: string;
  wip_qty: number;
  queue_depth: number;
  label: string;
  unit: string;
  trend: WipTrendPoint[];
  series: WipSeriesPoint[];
}

export interface WipReport {
  rows: WipRow[];
  total_wip: number;
  group_by: string;
  generated_at: string;
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

function readTrend(value: unknown): WipTrendPoint[] {
  if (!Array.isArray(value)) return [];
  return value
    .filter(isRecord)
    .map((row) => ({ date: readStr(row['date']), value: readNum(row['value']) }));
}

function readSeries(value: unknown): WipSeriesPoint[] {
  if (!Array.isArray(value)) return [];
  return value
    .filter(isRecord)
    .map((row) => ({ x: readStr(row['x']), y: readNum(row['y']) }));
}

function readRow(raw: unknown): WipRow | null {
  if (!isRecord(raw)) return null;
  return {
    wc_code: readStr(raw['wc_code']),
    wc_name: readStr(raw['wc_name']),
    wip_qty: readNum(raw['wip_qty']),
    queue_depth: readNum(raw['queue_depth']),
    label: readStr(raw['label']),
    unit: readStr(raw['unit']),
    trend: readTrend(raw['trend']),
    series: readSeries(raw['series']),
  };
}

/** PURE — respons mentah → `WipReport`; `null` kalau bukan objek. */
export function readWipReport(raw: unknown): WipReport | null {
  if (!isRecord(raw)) return null;

  const rowsRaw = Array.isArray(raw['rows']) ? raw['rows'] : [];
  const rows: WipRow[] = [];
  for (const row of rowsRaw) {
    const item = readRow(row);
    if (item !== null) rows.push(item);
  }

  return {
    rows,
    total_wip: readNum(raw['total_wip']),
    group_by: readStr(raw['group_by']),
    generated_at: readStr(raw['generated_at']),
  };
}

/** PURE — path + query `GET /reports/wip/`. */
export function buildReportsWipPath(params: { groupBy?: string | null } = {}): string {
  const groupBy = params.groupBy?.trim();
  return groupBy ? `${REPORTS_WIP_PATH}?group_by=${encodeURIComponent(groupBy)}` : REPORTS_WIP_PATH;
}

/** Baca laporan WIP. Gagal HTTP → melempar (`unwrap`). */
export async function fetchWip(
  client: ApiClient,
  params: { groupBy?: string | null } = {},
): Promise<WipReport> {
  const res = await client.get<unknown>(buildReportsWipPath(params));
  const parsed = readWipReport(unwrap(res));

  if (parsed === null) {
    throw new Error('Bentuk respons laporan WIP tidak dikenali.');
  }

  return parsed;
}
