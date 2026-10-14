// REAL - lead time per bundle + rincian stage (F3A.CLOSE flip / backend B19).
// Endpoint: GET /api/v1/reports/lead-time/ (ListPage + `avg_hours`).
import type { ApiClient } from '@/integrations/api-client';
import {
  buildQueryPath,
  getParsed,
  isRecord,
  readListPage,
  readNum,
  readNullableStr,
  readStr,
  type ListPage,
} from './_shape';

export const LEAD_TIME_PATH = '/reports/lead-time/';

export interface LeadTimeStage {
  /** Bisa `null` (BundleEvent tidak menyimpan wc_id). */
  wc_code: string | null;
  minutes: number;
}

export interface LeadTimeRow {
  bundle_code: string;
  created_at: string | null;
  finished_at: string | null;
  hours_total: number;
  stages: LeadTimeStage[];
}

export interface LeadTimeReport extends ListPage<LeadTimeRow> {
  avg_hours: number;
}

function readStages(value: unknown): LeadTimeStage[] {
  if (!Array.isArray(value)) return [];
  return value.filter(isRecord).map((row) => ({
    wc_code: readNullableStr(row['wc_code']),
    minutes: readNum(row['minutes']),
  }));
}

/** PURE — respons mentah → `LeadTimeReport`; `null` kalau `rows` bukan array. */
export function readLeadTimeReport(raw: unknown): LeadTimeReport | null {
  const page = readListPage<LeadTimeRow>(raw, (row) => {
    if (!isRecord(row)) return null;
    return {
      bundle_code: readStr(row['bundle_code']),
      created_at: readNullableStr(row['created_at']),
      finished_at: readNullableStr(row['finished_at']),
      hours_total: readNum(row['hours_total']),
      stages: readStages(row['stages']),
    };
  });
  if (page === null) return null;

  const rawAvg = isRecord(raw) ? raw['avg_hours'] : 0;
  return { ...page, avg_hours: readNum(rawAvg) };
}

/** PURE — path + `?limit=&cursor=&from=&to=`. */
export function buildReportsLeadTimePath(
  params: {
    limit?: number | null;
    cursor?: number | null;
    from?: string | null;
    to?: string | null;
  } = {},
): string {
  return buildQueryPath(LEAD_TIME_PATH, {
    limit: params.limit,
    cursor: params.cursor,
    from: params.from,
    to: params.to,
  });
}

/** Baca laporan lead time. Gagal HTTP → melempar. */
export async function fetchLeadTime(
  client: ApiClient,
  params: {
    limit?: number | null;
    cursor?: number | null;
    from?: string | null;
    to?: string | null;
  } = {},
): Promise<LeadTimeReport> {
  return getParsed(
    client,
    buildReportsLeadTimePath(params),
    readLeadTimeReport,
    'lead time',
  );
}
