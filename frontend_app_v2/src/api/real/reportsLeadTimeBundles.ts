// REAL - lead time per bundle, FLAT tanpa stages (F3A.CLOSE flip / backend B19b).
// Endpoint: GET /api/v1/reports/lead-time/bundles/ (ListPage, urut hours DESC).
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

export const LEAD_TIME_BUNDLES_PATH = '/reports/lead-time/bundles/';

export interface LeadTimeBundleRow {
  bundle_code: string;
  hours_total: number;
  /** Proksi jumlah WC = jumlah stage (BundleEvent tak punya wc_id). */
  wc_count: number;
  done_at: string | null;
}

/** PURE — respons mentah → `ListPage<LeadTimeBundleRow>`; `null` bila bukan ListPage. */
export function readLeadTimeBundlePage(
  raw: unknown,
): ListPage<LeadTimeBundleRow> | null {
  return readListPage<LeadTimeBundleRow>(raw, (row) => {
    if (!isRecord(row)) return null;
    return {
      bundle_code: readStr(row['bundle_code']),
      hours_total: readNum(row['hours_total']),
      wc_count: readNum(row['wc_count']),
      done_at: readNullableStr(row['done_at']),
    };
  });
}

/** PURE — path + `?limit=&cursor=&from=&to=`. */
export function buildLeadTimeBundlesPath(
  params: {
    limit?: number | null;
    cursor?: number | null;
    from?: string | null;
    to?: string | null;
  } = {},
): string {
  return buildQueryPath(LEAD_TIME_BUNDLES_PATH, {
    limit: params.limit,
    cursor: params.cursor,
    from: params.from,
    to: params.to,
  });
}

/** Baca daftar lead time per bundle (flat). Gagal HTTP → melempar. */
export async function fetchLeadTimeBundles(
  client: ApiClient,
  params: {
    limit?: number | null;
    cursor?: number | null;
    from?: string | null;
    to?: string | null;
  } = {},
): Promise<ListPage<LeadTimeBundleRow>> {
  return getParsed(
    client,
    buildLeadTimeBundlesPath(params),
    readLeadTimeBundlePage,
    'lead time per bundle',
  );
}
