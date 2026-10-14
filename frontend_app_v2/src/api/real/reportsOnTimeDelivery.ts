// REAL - on-time delivery per work order selesai (F3A.CLOSE flip / backend B20).
// Endpoint: GET /api/v1/reports/on-time-delivery/ (ListPage + `otd_pct`).
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

export const ON_TIME_DELIVERY_PATH = '/reports/on-time-delivery/';

export interface OtdRow {
  order_code: string;
  deadline: string | null;
  finished_at: string | null;
  /** `null` bila deadline/waktu selesai belum diketahui. */
  on_time: boolean | null;
  delay_hours: number;
}

export interface OtdReport extends ListPage<OtdRow> {
  otd_pct: number;
}

function readOnTime(value: unknown): boolean | null {
  return typeof value === 'boolean' ? value : null;
}

/** PURE — respons mentah → `OtdReport`; `null` kalau `rows` bukan array. */
export function readOtdReport(raw: unknown): OtdReport | null {
  const page = readListPage<OtdRow>(raw, (row) => {
    if (!isRecord(row)) return null;
    return {
      order_code: readStr(row['order_code']),
      deadline: readNullableStr(row['deadline']),
      finished_at: readNullableStr(row['finished_at']),
      on_time: readOnTime(row['on_time']),
      delay_hours: readNum(row['delay_hours']),
    };
  });
  if (page === null) return null;

  const rawPct = isRecord(raw) ? raw['otd_pct'] : 0;
  return { ...page, otd_pct: readNum(rawPct) };
}

/** PURE — path + `?limit=&cursor=&from=&to=&on_time=`. */
export function buildReportsOtdPath(
  params: {
    limit?: number | null;
    cursor?: number | null;
    from?: string | null;
    to?: string | null;
    onTime?: boolean | null;
  } = {},
): string {
  return buildQueryPath(ON_TIME_DELIVERY_PATH, {
    limit: params.limit,
    cursor: params.cursor,
    from: params.from,
    to: params.to,
    on_time: params.onTime === null || params.onTime === undefined ? null : params.onTime,
  });
}

/** Baca laporan OTD. Gagal HTTP → melempar. */
export async function fetchOnTimeDelivery(
  client: ApiClient,
  params: {
    limit?: number | null;
    cursor?: number | null;
    from?: string | null;
    to?: string | null;
    onTime?: boolean | null;
  } = {},
): Promise<OtdReport> {
  return getParsed(client, buildReportsOtdPath(params), readOtdReport, 'on-time delivery');
}
