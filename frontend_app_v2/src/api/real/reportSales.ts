// REAL - laporan penjualan agregat (H4.1). Endpoint: GET /api/v1/reports/sales/
//
// Backend `monitoring.ReportsSalesView` (H4.1). NON-ListPage: tanpa
// `total_count`/`has_more`, tapi `rows`/`summary`/`filters`/`period`.
//
// Param (prioritas backend): `?period=YYYY-MM` > `?date_from`/`?date_to` >
// `?from`/`?to`; plus `?customer_id=`/`?product_id=`/`?order_type=`/
// `?group_by=period|customer|product`/`?_nocache=1`.
import type { ApiClient } from '@/integrations/api-client';
import type {
  SalesGroupBy,
  SalesReportFilters,
  SalesReportResponse,
  SalesReportRow,
  SalesReportSummary,
} from '@/types/report-sales';
import { buildQueryPath, getParsed, isRecord, readBool, readNum, readStr } from './_shape';

/** Path relatif terhadap `VITE_API_BASE_URL` (`…/api/v1`). */
export const REPORTS_SALES_PATH = '/reports/sales/';

/** Default `group_by` backend (= `period`). */
export const SALES_GROUP_BY_DEFAULT: SalesGroupBy = 'period';

/** Pilihan `group_by` untuk UI (nilai = kontrak backend). */
export const SALES_GROUP_BY_VALUES: SalesGroupBy[] = ['period', 'customer', 'product'];

/** Pilihan `order_type` untuk UI (turunan `Order.OrderType`). */
export const SALES_ORDER_TYPES = ['EXPORT', 'CUSTOM', 'BRAND'] as const;

/** Param UI → query string (nilai kosong dilewati oleh `buildQueryPath`). */
export interface SalesReportQuery {
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
  groupBy?: SalesGroupBy | null;
  /** `true` → `?_nocache=1` (bypass cache backend; debug/force refresh). */
  nocache?: boolean;
}

function readRow(raw: unknown): SalesReportRow | null {
  if (!isRecord(raw)) return null;

  const row: SalesReportRow = {
    key: readStr(raw['key']),
    label: readStr(raw['label']),
    unit: readStr(raw['unit']),
    value: readNum(raw['value']),
    total_qty: readNum(raw['total_qty']),
    total_amount: readNum(raw['total_amount']),
    order_count: readNum(raw['order_count']),
    line_count: readNum(raw['line_count']),
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
  }

  return row;
}


function readSummary(raw: unknown): SalesReportSummary {
  const source = isRecord(raw) ? raw : {};
  return {
    total_qty: readNum(source['total_qty']),
    total_amount: readNum(source['total_amount']),
    count_orders: readNum(source['count_orders']),
    count_lines: readNum(source['count_lines']),
    invoiced_amount: readNum(source['invoiced_amount']),
    invoice_count: readNum(source['invoice_count']),
    paid_amount: readNum(source['paid_amount']),
    payment_count: readNum(source['payment_count']),
    currency: readStr(source['currency']) || 'IDR',
  };
}

function readGroupBy(value: unknown): SalesGroupBy {
  const raw = readStr(value);
  return SALES_GROUP_BY_VALUES.includes(raw as SalesGroupBy)
    ? (raw as SalesGroupBy)
    : SALES_GROUP_BY_DEFAULT;
}

function readFilters(raw: unknown): SalesReportFilters {
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

/** PURE — respons mentah → `SalesReportResponse`; `null` kalau `rows` bukan array. */
export function readSalesReport(raw: unknown): SalesReportResponse | null {
  if (!isRecord(raw)) return null;
  if (!Array.isArray(raw['rows'])) return null;

  const rows: SalesReportRow[] = [];
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

/** PURE — path + query `GET /reports/sales/` (hanya param terisi yang dikirim). */
export function buildReportsSalesPath(query: SalesReportQuery = {}): string {
  return buildQueryPath(REPORTS_SALES_PATH, {
    period: query.period ?? null,
    date_from: query.dateFrom ?? null,
    date_to: query.dateTo ?? null,
    from: query.from ?? null,
    to: query.to ?? null,
    customer_id: query.customerId ?? null,
    product_id: query.productId ?? null,
    order_type: query.orderType ?? null,
    group_by: query.groupBy ?? null,
    // `?_nocache=1` hanya dikirim saat diminta (escape hatch, bukan default).
    _nocache: query.nocache === true ? 1 : null,
  });
}

/** Baca laporan penjualan. Gagal HTTP → melempar (`unwrap` di `getParsed`). */
export async function fetchSalesReport(
  client: ApiClient,
  query: SalesReportQuery = {},
): Promise<SalesReportResponse> {
  return getParsed(client, buildReportsSalesPath(query), readSalesReport, 'laporan penjualan');
}
