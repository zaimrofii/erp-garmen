// REAL - laporan laba-rugi / PnL (H4.5). Endpoint: GET /api/v1/reports/pnl/
//
// Backend `monitoring.ReportsPnlView` (H4.5). NON-ListPage: tanpa
// `total_count`/`has_more`, tapi `rows`/`summary`/`filters`/`period`.
//
// Param (prioritas backend): `?period=YYYY-MM` > `?date_from`/`?date_to` >
// `?from`/`?to`; plus `?group_by=period|quarter`/`?_nocache=1`.
// TANPA `?customer_id`/`?product_id` (PnL = agregat bisnis).
import type { ApiClient } from '@/integrations/api-client';
import type {
  PnlGroupBy,
  PnlMissingCostReason,
  PnlReportFilters,
  PnlReportResponse,
  PnlReportRow,
  PnlReportSummary,
} from '@/types/report-pnl';
import {
  buildQueryPath,
  getParsed,
  isRecord,
  readBool,
  readNullableNum,
  readNum,
  readStr,
} from './_shape';

/** Path relatif terhadap `VITE_API_BASE_URL` (`.../api/v1`). */
export const REPORTS_PNL_PATH = '/reports/pnl/';

/** Default `group_by` backend (= `period`). */
export const PNL_GROUP_BY_DEFAULT: PnlGroupBy = 'period';

/** Pilihan `group_by` untuk UI (nilai = kontrak backend). */
export const PNL_GROUP_BY_VALUES: PnlGroupBy[] = ['period', 'quarter'];

/** Param UI -> query string (nilai kosong dilewati oleh `buildQueryPath`). */
export interface PnlReportQuery {
  /** `YYYY-MM`; menang atas `dateFrom`/`dateTo` di backend. */
  period?: string | null;
  dateFrom?: string | null;
  dateTo?: string | null;
  /** Alias lama (family report): hanya dipakai kalau `dateFrom`/`dateTo` kosong. */
  from?: string | null;
  to?: string | null;
  groupBy?: PnlGroupBy | null;
  /** `true` -> `?_nocache=1` (bypass cache backend; debug/force refresh). */
  nocache?: boolean;
}

/** PURE - daftar string dari respons (`[]` kalau bukan array of string). */
export function readStrList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string => typeof item === 'string');
}

/** PURE - alasan COGS hilang (nilai kontrak backend; lain -> `null`). */
export function readPnlMissingReason(value: unknown): PnlMissingCostReason | null {
  if (value === 'no_cost' || value === 'no_product') return value;
  return null;
}

function readRow(raw: unknown): PnlReportRow | null {
  if (!isRecord(raw)) return null;

  const row: PnlReportRow = {
    key: readStr(raw['key']),
    label: readStr(raw['label']),
    revenue: readNum(raw['revenue']),
    cogs: readNum(raw['cogs']),
    gross_profit: readNum(raw['gross_profit']),
    gross_margin_pct: readNum(raw['gross_margin_pct']),
    opex: readNullableNum(raw['opex']),
    net_profit: readNum(raw['net_profit']),
    net_margin_pct: readNum(raw['net_margin_pct']),
    order_count: readNum(raw['order_count']),
    line_count: readNum(raw['line_count']),
    has_missing_cost: readBool(raw['has_missing_cost']),
    missing_cost_reason: readPnlMissingReason(raw['missing_cost_reason']),
  };

  if (typeof raw['period'] === 'string') row.period = raw['period'];
  if (typeof raw['quarter'] === 'string') row.quarter = raw['quarter'];

  return row;
}

function readSummary(raw: unknown): PnlReportSummary {
  const source = isRecord(raw) ? raw : {};
  return {
    revenue: readNum(source['revenue']),
    cogs: readNum(source['cogs']),
    gross_profit: readNum(source['gross_profit']),
    gross_margin_pct: readNum(source['gross_margin_pct']),
    opex: readNullableNum(source['opex']),
    net_profit: readNum(source['net_profit']),
    net_margin_pct: readNum(source['net_margin_pct']),
    opex_source: readStr(source['opex_source']) || 'unavailable',
    opex_account_types: readStrList(source['opex_account_types']),
    opex_states: readStrList(source['opex_states']),
    order_count: readNum(source['order_count']),
    line_count: readNum(source['line_count']),
    rows_with_missing_cost: readNum(source['rows_with_missing_cost']),
    currency: readStr(source['currency']) || 'IDR',
  };
}

function readGroupBy(value: unknown): PnlGroupBy {
  const raw = readStr(value);
  return PNL_GROUP_BY_VALUES.includes(raw as PnlGroupBy)
    ? (raw as PnlGroupBy)
    : PNL_GROUP_BY_DEFAULT;
}

function readFilters(raw: unknown): PnlReportFilters {
  const source = isRecord(raw) ? raw : {};
  const strOrNull = (value: unknown): string | null =>
    typeof value === 'string' ? value : null;

  return {
    period: strOrNull(source['period']),
    date_from: strOrNull(source['date_from']),
    date_to: strOrNull(source['date_to']),
    from: strOrNull(source['from']),
    to: strOrNull(source['to']),
    group_by: readGroupBy(source['group_by']),
    nocache: readBool(source['nocache']),
    resolved_from: readStr(source['resolved_from']),
    resolved_to: readStr(source['resolved_to']),
  };
}

/** PURE - respons mentah -> `PnlReportResponse`; `null` kalau `rows` bukan array. */
export function readPnlReport(raw: unknown): PnlReportResponse | null {
  if (!isRecord(raw)) return null;
  if (!Array.isArray(raw['rows'])) return null;

  const rows: PnlReportRow[] = [];
  for (const item of raw['rows']) {
    const row = readRow(item);
    if (row !== null) rows.push(row);
  }

  const periodRaw = isRecord(raw['period']) ? raw['period'] : {};

  return {
    rows,
    summary: readSummary(raw['summary']),
    group_by: readGroupBy(raw['group_by']),
    filters: readFilters(raw['filters']),
    period: { from: readStr(periodRaw['from']), to: readStr(periodRaw['to']) },
    generated_at: readStr(raw['generated_at']),
    cached: readBool(raw['cached']),
  };
}

/** PURE - path + query `GET /reports/pnl/` (hanya param terisi yang dikirim). */
export function buildReportsPnlPath(query: PnlReportQuery = {}): string {
  return buildQueryPath(REPORTS_PNL_PATH, {
    period: query.period ?? null,
    date_from: query.dateFrom ?? null,
    date_to: query.dateTo ?? null,
    from: query.from ?? null,
    to: query.to ?? null,
    group_by: query.groupBy ?? null,
    _nocache: query.nocache === true ? 1 : null,
  });
}

/** Baca laporan laba-rugi. Gagal HTTP -> melempar (`unwrap` di `getParsed`). */
export async function fetchPnlReport(
  client: ApiClient,
  query: PnlReportQuery = {},
): Promise<PnlReportResponse> {
  return getParsed(client, buildReportsPnlPath(query), readPnlReport, 'laporan laba-rugi');
}
