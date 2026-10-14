// REAL - laporan efisiensi lini (F2C.2). Endpoint: GET /api/v1/reports/line-efficiency/
//
// Backend `monitoring.ReportsLineEfficiencyView` (B13 + G4b). Non-ListPage.
import type { ApiClient } from '@/integrations/api-client';
import { unwrap } from '../client';

/** Path relatif terhadap `VITE_API_BASE_URL`. */
export const LINE_EFFICIENCY_PATH = '/reports/line-efficiency/';

export interface ReportTrendPoint {
  date: string;
  value: number;
}

export interface ReportSeriesPoint {
  x: string;
  y: number;
}

export interface LineEfficiencyRow {
  wc_code: string;
  wc_name: string;
  bundles_done: number;
  avg_min_per_bundle: number;
  efficiency_pct: number;
  label: string;
  unit: string;
  trend: ReportTrendPoint[];
  series: ReportSeriesPoint[];
}

export interface LineEfficiencyReport {
  rows: LineEfficiencyRow[];
  generated_at: string;
  period: { from: string; to: string };
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

function readTrend(value: unknown): ReportTrendPoint[] {
  if (!Array.isArray(value)) return [];
  return value
    .filter(isRecord)
    .map((row) => ({ date: readStr(row['date']), value: readNum(row['value']) }));
}

function readSeries(value: unknown): ReportSeriesPoint[] {
  if (!Array.isArray(value)) return [];
  return value
    .filter(isRecord)
    .map((row) => ({ x: readStr(row['x']), y: readNum(row['y']) }));
}

function readRow(raw: unknown): LineEfficiencyRow | null {
  if (!isRecord(raw)) return null;
  return {
    wc_code: readStr(raw['wc_code']),
    wc_name: readStr(raw['wc_name']),
    bundles_done: readNum(raw['bundles_done']),
    avg_min_per_bundle: readNum(raw['avg_min_per_bundle']),
    efficiency_pct: readNum(raw['efficiency_pct']),
    label: readStr(raw['label']),
    unit: readStr(raw['unit']),
    trend: readTrend(raw['trend']),
    series: readSeries(raw['series']),
  };
}

/** PURE — respons mentah → `LineEfficiencyReport`; `null` kalau `rows` bukan array. */
export function readLineEfficiencyReport(raw: unknown): LineEfficiencyReport | null {
  if (!isRecord(raw)) return null;
  const rows = raw['rows'];
  if (!Array.isArray(rows)) return null;

  const parsed: LineEfficiencyRow[] = [];
  for (const row of rows) {
    const item = readRow(row);
    if (item !== null) parsed.push(item);
  }

  const period = isRecord(raw['period']) ? raw['period'] : {};

  return {
    rows: parsed,
    generated_at: readStr(raw['generated_at']),
    period: { from: readStr(period['from']), to: readStr(period['to']) },
  };
}

/** PURE — path + query `GET /reports/line-efficiency/`. */
export function buildLineEfficiencyPath(
  params: { from?: string | null; to?: string | null } = {},
): string {
  const qs = new URLSearchParams();
  if (params.from) qs.set('from', params.from);
  if (params.to) qs.set('to', params.to);
  const suffix = qs.toString();
  return suffix.length === 0 ? LINE_EFFICIENCY_PATH : `${LINE_EFFICIENCY_PATH}?${suffix}`;
}

/** Baca laporan efisiensi. Gagal HTTP → melempar (`unwrap`). */
export async function fetchLineEfficiency(
  client: ApiClient,
  params: { from?: string | null; to?: string | null } = {},
): Promise<LineEfficiencyReport> {
  const res = await client.get<unknown>(buildLineEfficiencyPath(params));
  const parsed = readLineEfficiencyReport(unwrap(res));

  if (parsed === null) {
    throw new Error('Bentuk respons laporan efisiensi tidak dikenali.');
  }

  return parsed;
}
