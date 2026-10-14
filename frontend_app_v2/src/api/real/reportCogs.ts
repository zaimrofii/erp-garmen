// REAL - laporan HPP/laba kotor (H4.4). Endpoint: GET /api/v1/reports/cogs/
//
// Backend `monitoring.ReportsCogsView` (H4.4). NON-ListPage: tanpa
// `total_count`/`has_more`, tapi `rows`/`summary`/`filters`/`period`.
//
// Param (prioritas backend, delegasi pola H4.1): `?period=YYYY-MM` >
// `?date_from`/`?date_to` > `?from`/`?to`; plus `?customer_id=`/`?product_id=`/
// `?order_type=`/`?group_by=period|customer|product`/`?_nocache=1`.
import type { ApiClient } from '@/integrations/api-client';
import type {
  CogsGroupBy,
  CogsMissingCostReason,
  CogsReportFilters,
  CogsReportResponse,
  CogsReportRow,
  CogsReportSummary,
} from '@/types/report-cogs';
import { buildQueryPath, getParsed, isRecord, readBool, readNum, readStr } from './_shape';

/** Path relatif terhadap `VITE_API_BASE_URL` (`.../api/v1`). */
export const REPORTS_COGS_PATH = '/reports/cogs/';

/** Default `group_by` backend (= `period`). */
export const COGS_GROUP_BY_DEFAULT: CogsGroupBy = 'period';

/** Pilihan `group_by` untuk UI (nilai = kontrak backend). */
export const COGS_GROUP_BY_VALUES: CogsGroupBy[] = ['period', 'customer', 'product'];

/** Pilihan `order_type` untuk UI (turunan `Order.OrderType`). */
export const COGS_ORDER_TYPES = ['EXPORT', 'CUSTOM', 'BRAND'] as const;

/** Param UI -> query string (nilai kosong dilewati oleh `buildQueryPath`). */
export interface CogsReportQuery {
  /** `YYYY-MM`; menang atas `dateFrom`/`dateTo` di backend. */
  period?: string | null;
  dateFrom?: string | null;
  dateTo?: string | null;
  /** Alias lama (family report): hanya dipakai kalau `dateFrom`/`dateTo` kosong. */
  from?: string | null;
  to?: string | null;
  customerId?: number | null;
  productId?: number | null;
  orderType?: string | null;
  groupBy?: CogsGroupBy | null;
  /** `true` -> `?_nocache=1` (bypass cache backend; debug/force refresh). */
  nocache?: boolean;
}

/** PURE - alasan COGS hilang (nilai kontrak backend; lain -> `null`). */
export function readMissingCostReason(value: unknown): CogsMissingCostReason | null {
  if (value === 'no_cost' || value === 'no_product') return value;
  return null;
}

function readRow(raw: unknown): CogsReportRow | null {
  if (!isRecord(raw)) return null;

  const row: CogsReportRow = {
    key: readStr(raw['key']),
    label: readStr(raw['label']),
    sales_amount: readNum(raw['sales_amount']),
    cogs_amount: readNum(raw['cogs_amount']),
    gross_profit: readNum(raw['gross_profit']),
    gross_margin_pct: readNum(raw['gross_margin_pct']),
    order_count: readNum(raw['order_count']),
    line_count: readNum(raw['line_count']),
    qty_total: readNum(raw['qty_total']),
    has_missing_cost: readBool(raw['has_missing_cost']),
    missing_cost_reason: readMissingCostReason(raw['missing_cost_reason']),
  };

  if (typeof raw['period'] === 'string') row.period = raw['period'];
  if ('customer_id' in raw) {
    row.customer_id = typeof raw['customer_id'] === 'number' ? raw['customer_id'] : null;
    row.customer_code = readStr(raw['customer_code']);
    row.customer_name = readStr(raw['customer_name']);
  }
  if ('product_id' in raw) {
    row.product_id = typeof raw['product_id'] === 'number' ? raw['product_id'] : null;
    row.product_code = readStr(raw['product_code']);
    row.product_name = readStr(raw['product_name']);
    row.qty = readNum(raw['qty']);
  }

  return row;
}

function readSummary(raw: unknown): CogsReportSummary {
  const source = isRecord(raw) ? raw : {};
  return {
    total_sales: readNum(source['total_sales']),
    total_cogs: readNum(source['total_cogs']),
    total_gross_profit: readNum(source['total_gross_profit']),
    gross_margin_pct: readNum(source['gross_margin_pct']),
    order_count: readNum(source['order_count']),
    line_count: readNum(source['line_count']),
    qty_total: readNum(source['qty_total']),
    rows_with_missing_cost: readNum(source['rows_with_missing_cost']),
    currency: readStr(source['currency']) || 'IDR',
  };
}

function readGroupBy(value: unknown): CogsGroupBy {
  const raw = readStr(value);
  return COGS_GROUP_BY_VALUES.includes(raw as CogsGroupBy)
    ? (raw as CogsGroupBy)
    : COGS_GROUP_BY_DEFAULT;
}

function readFilters(raw: unknown): CogsReportFilters {
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
    customer_id: typeof source['customer_id'] === 'number' ? source['customer_id'] : null,
    product_id: typeof source['product_id'] === 'number' ? source['product_id'] : null,
    order_type: strOrNull(source['order_type']),
    nocache: readBool(source['nocache']),
    resolved_from: readStr(source['resolved_from']),
    resolved_to: readStr(source['resolved_to']),
  };
}

/** PURE - respons mentah -> `CogsReportResponse`; `null` kalau `rows` bukan array. */
export function readCogsReport(raw: unknown): CogsReportResponse | null {
  if (!isRecord(raw)) return null;
  if (!Array.isArray(raw['rows'])) return null;

  const rows: CogsReportRow[] = [];
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

/** PURE - path + query `GET /reports/cogs/` (hanya param terisi yang dikirim). */
export function buildReportsCogsPath(query: CogsReportQuery = {}): string {
  return buildQueryPath(REPORTS_COGS_PATH, {
    period: query.period ?? null,
    date_from: query.dateFrom ?? null,
    date_to: query.dateTo ?? null,
    from: query.from ?? null,
    to: query.to ?? null,
    customer_id: query.customerId ?? null,
    product_id: query.productId ?? null,
    order_type: query.orderType ?? null,
    group_by: query.groupBy ?? null,
    _nocache: query.nocache === true ? 1 : null,
  });
}

/** Baca laporan HPP/laba kotor. Gagal HTTP -> melempar (`unwrap` di `getParsed`). */
export async function fetchCogsReport(
  client: ApiClient,
  query: CogsReportQuery = {},
): Promise<CogsReportResponse> {
  return getParsed(client, buildReportsCogsPath(query), readCogsReport, 'laporan HPP');
}
