// REAL - laporan pembelian agregat (H4.2). Endpoint: GET /api/v1/reports/purchases/
//
// Backend `monitoring.ReportsPurchasesView` (H4.2). NON-ListPage: tanpa
// `total_count`/`has_more`, tapi `rows`/`summary`/`filters`/`period`.
//
// Param (prioritas backend): `?period=YYYY-MM` > `?date_from`/`?date_to` >
// `?from`/`?to`; plus `?vendor_id=`/`?product_id=`/`?status=`/
// `?group_by=period|vendor|product`/`?_nocache=1`.
import type { ApiClient } from '@/integrations/api-client';
import type {
  PurchasesGroupBy,
  PurchasesReportFilters,
  PurchasesReportResponse,
  PurchasesReportRow,
  PurchasesReportSummary,
} from '@/types/report-purchases';
import { buildQueryPath, getParsed, isRecord, readBool, readNum, readStr } from './_shape';

/** Path relatif terhadap `VITE_API_BASE_URL` (`.../api/v1`). */
export const REPORTS_PURCHASES_PATH = '/reports/purchases/';

/** Default `group_by` backend (= `period`). */
export const PURCHASES_GROUP_BY_DEFAULT: PurchasesGroupBy = 'period';

/** Pilihan `group_by` untuk UI (nilai = kontrak backend). */
export const PURCHASES_GROUP_BY_VALUES: PurchasesGroupBy[] = ['period', 'vendor', 'product'];

/** Pilihan `status` untuk UI (state `PurchaseOrder` MES H2.2). */
export const PURCHASES_STATUS_VALUES = ['DRAFT', 'CONFIRMED', 'DONE', 'CANCELLED'] as const;

/** Param UI -> query string (nilai kosong dilewati oleh `buildQueryPath`). */
export interface PurchasesReportQuery {
  /** `YYYY-MM`; menang atas `dateFrom`/`dateTo` di backend. */
  period?: string | null;
  dateFrom?: string | null;
  dateTo?: string | null;
  /** Alias lama (family report): hanya dipakai kalau `dateFrom`/`dateTo` kosong. */
  from?: string | null;
  to?: string | null;
  vendorId?: number | null;
  productId?: number | null;
  status?: string | null;
  groupBy?: PurchasesGroupBy | null;
  /** `true` -> `?_nocache=1` (bypass cache backend; debug/force refresh). */
  nocache?: boolean;
}

function readRow(raw: unknown): PurchasesReportRow | null {
  if (!isRecord(raw)) return null;

  const row: PurchasesReportRow = {
    key: readStr(raw['key']),
    label: readStr(raw['label']),
    unit: readStr(raw['unit']),
    value: readNum(raw['value']),
    total_qty: readNum(raw['total_qty']),
    total_amount: readNum(raw['total_amount']),
    purchase_count: readNum(raw['purchase_count']),
    line_count: readNum(raw['line_count']),
  };

  if (typeof raw['period'] === 'string') row.period = raw['period'];
  if ('vendor_id' in raw) {
    row.vendor_id = typeof raw['vendor_id'] === 'number' ? raw['vendor_id'] : null;
    row.vendor_code = readStr(raw['vendor_code']);
    row.vendor_name = readStr(raw['vendor_name']);
  }
  if ('product_id' in raw) {
    row.product_id = typeof raw['product_id'] === 'number' ? raw['product_id'] : null;
    row.product_code = readStr(raw['product_code']);
    row.product_name = readStr(raw['product_name']);
  }

  return row;
}

function readSummary(raw: unknown): PurchasesReportSummary {
  const source = isRecord(raw) ? raw : {};
  return {
    total_qty: readNum(source['total_qty']),
    total_amount: readNum(source['total_amount']),
    count_purchases: readNum(source['count_purchases']),
    count_lines: readNum(source['count_lines']),
    billed_amount: readNum(source['billed_amount']),
    bill_count: readNum(source['bill_count']),
    paid_amount: readNum(source['paid_amount']),
    payment_count: readNum(source['payment_count']),
    currency: readStr(source['currency']) || 'IDR',
  };
}

function readGroupBy(value: unknown): PurchasesGroupBy {
  const raw = readStr(value);
  return PURCHASES_GROUP_BY_VALUES.includes(raw as PurchasesGroupBy)
    ? (raw as PurchasesGroupBy)
    : PURCHASES_GROUP_BY_DEFAULT;
}

function readFilters(raw: unknown): PurchasesReportFilters {
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
    vendor_id: typeof source['vendor_id'] === 'number' ? source['vendor_id'] : null,
    product_id: typeof source['product_id'] === 'number' ? source['product_id'] : null,
    status: strOrNull(source['status']),
    nocache: readBool(source['nocache']),
    resolved_from: readStr(source['resolved_from']),
    resolved_to: readStr(source['resolved_to']),
  };
}

/** PURE - respons mentah -> `PurchasesReportResponse`; `null` kalau `rows` bukan array. */
export function readPurchasesReport(raw: unknown): PurchasesReportResponse | null {
  if (!isRecord(raw)) return null;
  if (!Array.isArray(raw['rows'])) return null;

  const rows: PurchasesReportRow[] = [];
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

/** PURE - path + query `GET /reports/purchases/` (hanya param terisi yang dikirim). */
export function buildReportsPurchasesPath(query: PurchasesReportQuery = {}): string {
  return buildQueryPath(REPORTS_PURCHASES_PATH, {
    period: query.period ?? null,
    date_from: query.dateFrom ?? null,
    date_to: query.dateTo ?? null,
    from: query.from ?? null,
    to: query.to ?? null,
    vendor_id: query.vendorId ?? null,
    product_id: query.productId ?? null,
    status: query.status ?? null,
    group_by: query.groupBy ?? null,
    // `?_nocache=1` hanya dikirim saat diminta (escape hatch, bukan default).
    _nocache: query.nocache === true ? 1 : null,
  });
}

/** Baca laporan pembelian. Gagal HTTP -> melempar (`unwrap` di `getParsed`). */
export async function fetchPurchasesReport(
  client: ApiClient,
  query: PurchasesReportQuery = {},
): Promise<PurchasesReportResponse> {
  return getParsed(
    client,
    buildReportsPurchasesPath(query),
    readPurchasesReport,
    'laporan pembelian',
  );
}
