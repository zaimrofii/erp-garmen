// REAL - laporan stok snapshot (H4.3). Endpoint: GET /api/v1/reports/stock/
//
// Backend `monitoring.ReportsStockView` (H4.3). NON-ListPage: tanpa
// `total_count`/`has_more`, tapi `rows`/`summary`/`filters`.
//
// Sumber = Odoo `stock.quant` LIVE via jalur I7 (2 RPC), snapshot (bukan
// time-series) -> TANPA param rentang. Param: `?location_id=`/`?product_id=`
// (pk MES), `?search=`, `?group_by=product|location`, `?only_nonzero=1`,
// `?_nocache=1`.
import type { ApiClient } from '@/integrations/api-client';
import type {
  StockGroupBy,
  StockReportFilters,
  StockReportResponse,
  StockReportRow,
  StockReportSummary,
} from '@/types/report-stock';
import { buildQueryPath, getParsed, isRecord, readBool, readNum, readStr } from './_shape';

/** Path relatif terhadap `VITE_API_BASE_URL` (`.../api/v1`). */
export const REPORTS_STOCK_PATH = '/reports/stock/';

/** Default `group_by` backend (= `product`). */
export const STOCK_GROUP_BY_DEFAULT: StockGroupBy = 'product';

/** Pilihan `group_by` untuk UI (nilai = kontrak backend). */
export const STOCK_GROUP_BY_VALUES: StockGroupBy[] = ['product', 'location'];

/** Param UI -> query string (nilai kosong dilewati oleh `buildQueryPath`). */
export interface StockReportQuery {
  locationId?: number | null;
  productId?: number | null;
  search?: string | null;
  groupBy?: StockGroupBy | null;
  /** `true` -> `?only_nonzero=1` (sembunyikan baris qty 0). */
  onlyNonzero?: boolean | null;
  /** `true` -> `?_nocache=1` (bypass cache backend; debug/force refresh). */
  nocache?: boolean;
}

function readRow(raw: unknown): StockReportRow | null {
  if (!isRecord(raw)) return null;

  const row: StockReportRow = {
    key: readStr(raw['key']),
    label: readStr(raw['label']),
    unit: readStr(raw['unit']),
    total_qty: readNum(raw['total_qty']),
    reserved_qty: readNum(raw['reserved_qty']),
    available_qty: readNum(raw['available_qty']),
  };

  if ('product_id' in raw) {
    row.product_id = typeof raw['product_id'] === 'number' ? raw['product_id'] : null;
    row.product_code = readStr(raw['product_code']);
    row.product_name = readStr(raw['product_name']);
    row.uom_code = readStr(raw['uom_code']);
    row.locations_count = readNum(raw['locations_count']);
  }
  if ('location_id' in raw) {
    row.location_id = typeof raw['location_id'] === 'number' ? raw['location_id'] : null;
    row.location_code = readStr(raw['location_code']);
    row.location_name = readStr(raw['location_name']);
    row.location_odoo_id = readNum(raw['location_odoo_id']);
    row.products_count = readNum(raw['products_count']);
  }

  return row;
}

function readSummary(raw: unknown): StockReportSummary {
  const source = isRecord(raw) ? raw : {};
  return {
    total_qty: readNum(source['total_qty']),
    reserved_qty: readNum(source['reserved_qty']),
    available_qty: readNum(source['available_qty']),
    product_count: readNum(source['product_count']),
    location_count: readNum(source['location_count']),
    quant_count: readNum(source['quant_count']),
    unmapped_product_count: readNum(source['unmapped_product_count']),
    unmapped_qty: readNum(source['unmapped_qty']),
  };
}

function readGroupBy(value: unknown): StockGroupBy {
  const raw = readStr(value);
  return STOCK_GROUP_BY_VALUES.includes(raw as StockGroupBy)
    ? (raw as StockGroupBy)
    : STOCK_GROUP_BY_DEFAULT;
}

function readFilters(raw: unknown): StockReportFilters {
  const source = isRecord(raw) ? raw : {};
  return {
    group_by: readGroupBy(source['group_by']),
    location_id: typeof source['location_id'] === 'number' ? source['location_id'] : null,
    product_id: typeof source['product_id'] === 'number' ? source['product_id'] : null,
    search: typeof source['search'] === 'string' ? source['search'] : null,
    only_nonzero: readBool(source['only_nonzero']),
    nocache: readBool(source['nocache']),
    source: readStr(source['source']) || 'odoo',
  };
}

/** PURE - respons mentah -> `StockReportResponse`; `null` kalau `rows` bukan array. */
export function readStockReport(raw: unknown): StockReportResponse | null {
  if (!isRecord(raw)) return null;
  if (!Array.isArray(raw['rows'])) return null;

  const rows: StockReportRow[] = [];
  for (const item of raw['rows']) {
    const row = readRow(item);
    if (row !== null) rows.push(row);
  }

  return {
    rows,
    summary: readSummary(raw['summary']),
    group_by: readGroupBy(raw['group_by']),
    filters: readFilters(raw['filters']),
    generated_at: readStr(raw['generated_at']),
    cached: readBool(raw['cached']),
    source: readStr(raw['source']) || 'odoo',
  };
}

/** PURE - path + query `GET /reports/stock/` (hanya param terisi yang dikirim). */
export function buildReportsStockPath(query: StockReportQuery = {}): string {
  return buildQueryPath(REPORTS_STOCK_PATH, {
    location_id: query.locationId ?? null,
    product_id: query.productId ?? null,
    search: query.search ?? null,
    group_by: query.groupBy ?? null,
    only_nonzero: query.onlyNonzero === true ? 1 : null,
    _nocache: query.nocache === true ? 1 : null,
  });
}

/** Baca laporan stok. Gagal HTTP -> melempar (`unwrap` di `getParsed`). */
export async function fetchStockReport(
  client: ApiClient,
  query: StockReportQuery = {},
): Promise<StockReportResponse> {
  return getParsed(client, buildReportsStockPath(query), readStockReport, 'laporan stok');
}
