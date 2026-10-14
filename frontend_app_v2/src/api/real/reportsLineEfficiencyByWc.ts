// REAL - detail efisiensi lini per WC (F3A.CLOSE flip / backend B18).
// Endpoint: GET /api/v1/reports/line-efficiency/by-wc/
import type { ApiClient } from '@/integrations/api-client';
import {
  buildQueryPath,
  getParsed,
  isRecord,
  readNum,
  readStr,
} from './_shape';

export const LINE_EFFICIENCY_BY_WC_PATH = '/reports/line-efficiency/by-wc/';

export interface LineEfficiencyByWcRow {
  wc_code: string;
  wc_name: string;
  bundles_done: number;
  avg_min_per_bundle: number;
  efficiency_pct: number;
  /** Delta vs periode sebelumnya yang sama panjangnya (bisa negatif). */
  pct_delta_vs_prev: number;
}

export interface LineEfficiencyByWcReport {
  rows: LineEfficiencyByWcRow[];
  generated_at: string;
  period: { from: string; to: string };
}

/** PURE — respons mentah → `LineEfficiencyByWcReport`; `null` kalau `rows` bukan array. */
export function readLineEfficiencyByWcReport(
  raw: unknown,
): LineEfficiencyByWcReport | null {
  if (!isRecord(raw)) return null;
  const rows = raw['rows'];
  if (!Array.isArray(rows)) return null;

  const parsed: LineEfficiencyByWcRow[] = [];
  for (const row of rows) {
    if (!isRecord(row)) continue;
    parsed.push({
      wc_code: readStr(row['wc_code']),
      wc_name: readStr(row['wc_name']),
      bundles_done: readNum(row['bundles_done']),
      avg_min_per_bundle: readNum(row['avg_min_per_bundle']),
      efficiency_pct: readNum(row['efficiency_pct']),
      pct_delta_vs_prev: readNum(row['pct_delta_vs_prev']),
    });
  }

  const period = isRecord(raw['period']) ? raw['period'] : {};
  return {
    rows: parsed,
    generated_at: readStr(raw['generated_at']),
    period: { from: readStr(period['from']), to: readStr(period['to']) },
  };
}

/** PURE — path + `?from=&to=`. */
export function buildLineEfficiencyByWcPath(
  params: { from?: string | null; to?: string | null } = {},
): string {
  return buildQueryPath(LINE_EFFICIENCY_BY_WC_PATH, {
    from: params.from,
    to: params.to,
  });
}

/** Baca laporan efisiensi per WC. Gagal HTTP → melempar. */
export async function fetchLineEfficiencyByWc(
  client: ApiClient,
  params: { from?: string | null; to?: string | null } = {},
): Promise<LineEfficiencyByWcReport> {
  return getParsed(
    client,
    buildLineEfficiencyByWcPath(params),
    readLineEfficiencyByWcReport,
    'efisiensi per work center',
  );
}
