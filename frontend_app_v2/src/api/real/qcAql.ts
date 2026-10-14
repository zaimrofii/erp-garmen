// REAL - AQL per work center (F3A.CLOSE flip / backend B5).
// Endpoint: GET /api/v1/quality/aql/ — sumber BundleEvent (FINISH=sampel, scrap=defect).
import type { ApiClient } from '@/integrations/api-client';
import { unwrap } from '../client';

export const QUALITY_AQL_PATH = '/quality/aql/';

export type AqlSeverity = 'pass' | 'warn' | 'fail';

export interface AqlRow {
  wc_code: string;
  wc_name: string;
  sample_qty: number;
  defect_qty: number;
  aql_pct: number;
  severity: AqlSeverity;
}

export interface AqlReport {
  rows: AqlRow[];
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

function readSeverity(value: unknown): AqlSeverity {
  return value === 'fail' || value === 'warn' ? value : 'pass';
}

/** PURE — respons mentah → `AqlReport`; `null` kalau `rows` bukan array. */
export function readAqlReport(raw: unknown): AqlReport | null {
  if (!isRecord(raw)) return null;
  const rows = raw['rows'];
  if (!Array.isArray(rows)) return null;

  const parsed: AqlRow[] = [];
  for (const row of rows) {
    if (!isRecord(row)) continue;
    parsed.push({
      wc_code: readStr(row['wc_code']),
      wc_name: readStr(row['wc_name']),
      sample_qty: readNum(row['sample_qty']),
      defect_qty: readNum(row['defect_qty']),
      aql_pct: readNum(row['aql_pct']),
      severity: readSeverity(row['severity']),
    });
  }

  const period = isRecord(raw['period']) ? raw['period'] : {};
  return {
    rows: parsed,
    generated_at: readStr(raw['generated_at']),
    period: { from: readStr(period['from']), to: readStr(period['to']) },
  };
}

/** PURE — path + query `GET /quality/aql/`. */
export function buildQualityAqlPath(params: { from?: string | null; to?: string | null } = {}): string {
  const qs = new URLSearchParams();
  if (params.from) qs.set('from', params.from);
  if (params.to) qs.set('to', params.to);
  const suffix = qs.toString();
  return suffix.length === 0 ? QUALITY_AQL_PATH : `${QUALITY_AQL_PATH}?${suffix}`;
}

/** Baca laporan AQL. Gagal HTTP → melempar (`unwrap`). */
export async function fetchAqlSummary(
  client: ApiClient,
  params: { from?: string | null; to?: string | null } = {},
): Promise<AqlReport> {
  const res = await client.get<unknown>(buildQualityAqlPath(params));
  const parsed = readAqlReport(unwrap(res));

  if (parsed === null) {
    throw new Error('Bentuk respons laporan AQL tidak dikenali.');
  }

  return parsed;
}
