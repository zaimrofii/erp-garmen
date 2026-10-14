// REAL - laporan produksi (H4.6). Endpoint: GET /api/v1/reports/production/
//
// Backend `monitoring.ReportsProductionView` (H4.6) - SUPERSET B13/B16/B18-B21
// dengan dimensi periode. NON-ListPage: `rows`/`summary`/`filters`/`period`.
//
// Param (prioritas backend): `?period=YYYY-MM` > `?date_from`/`?date_to` >
// `?from`/`?to`; plus `?group_by=period|work_center|line`,
// `?work_center_id=`/`?line_id=` (pk MES), `?_nocache=1`.
import type { ApiClient } from '@/integrations/api-client';
import type {
  ProductionGroupBy,
  ProductionReportFilters,
  ProductionReportResponse,
  ProductionReportRow,
  ProductionReportSummary,
} from '@/types/report-production';
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
export const REPORTS_PRODUCTION_PATH = '/reports/production/';

/** Default `group_by` backend (= `period`). */
export const PRODUCTION_GROUP_BY_DEFAULT: ProductionGroupBy = 'period';

/** Pilihan `group_by` untuk UI (nilai = kontrak backend). */
export const PRODUCTION_GROUP_BY_VALUES: ProductionGroupBy[] = [
  'period',
  'work_center',
  'line',
];

/** Param UI -> query string (nilai kosong dilewati oleh `buildQueryPath`). */
export interface ProductionReportQuery {
  /** `YYYY-MM`; menang atas `dateFrom`/`dateTo` di backend. */
  period?: string | null;
  dateFrom?: string | null;
  dateTo?: string | null;
  /** Alias lama (family report): hanya dipakai kalau `dateFrom`/`dateTo` kosong. */
  from?: string | null;
  to?: string | null;
  /** pk MES `garment.WorkCenter`. */
  workCenterId?: number | null;
  /** pk MES `garment.ProductionLine`. */
  lineId?: number | null;
  groupBy?: ProductionGroupBy | null;
  /** `true` -> `?_nocache=1` (bypass cache backend; debug/force refresh). */
  nocache?: boolean;
}

/** PURE - record string (mis. `filters.basis`); bukan record -> `{}`. */
export function readStrRecord(value: unknown): Record<string, string> {
  if (!isRecord(value)) return {};
  const result: Record<string, string> = {};
  for (const [key, item] of Object.entries(value)) {
    if (typeof item === 'string') result[key] = item;
  }
  return result;
}

function readRow(raw: unknown): ProductionReportRow | null {
  if (!isRecord(raw)) return null;

  const row: ProductionReportRow = {
    key: readStr(raw['key']),
    label: readStr(raw['label']),
    output_pcs: readNum(raw['output_pcs']),
    scrap_pcs: readNum(raw['scrap_pcs']),
    scrap_pct: readNum(raw['scrap_pct']),
    efficiency_pct: readNum(raw['efficiency_pct']),
    otd_pct: readNullableNum(raw['otd_pct']),
  };

  if (typeof raw['period'] === 'string') row.period = raw['period'];
  if ('rework_pcs' in raw) row.rework_pcs = readNum(raw['rework_pcs']);
  if ('end_loss_pcs' in raw) row.end_loss_pcs = readNum(raw['end_loss_pcs']);
  if ('bundle_count' in raw) row.bundle_count = readNum(raw['bundle_count']);
  if ('wo_count' in raw) row.wo_count = readNum(raw['wo_count']);
  if ('wc_id' in raw) {
    row.wc_id = typeof raw['wc_id'] === 'number' ? raw['wc_id'] : null;
    row.wc_code = readStr(raw['wc_code']);
    row.wc_name = readStr(raw['wc_name']);
  }
  if ('line_id' in raw) {
    row.line_id = typeof raw['line_id'] === 'number' ? raw['line_id'] : null;
    row.line_code = readStr(raw['line_code']);
    row.line_name = readStr(raw['line_name']);
  }

  return row;
}

function readSummary(raw: unknown): ProductionReportSummary {
  const source = isRecord(raw) ? raw : {};
  return {
    total_output_pcs: readNum(source['total_output_pcs']),
    total_scrap_pcs: readNum(source['total_scrap_pcs']),
    total_rework_pcs: readNum(source['total_rework_pcs']),
    total_end_loss_pcs: readNum(source['total_end_loss_pcs']),
    scrap_pct: readNum(source['scrap_pct']),
    avg_efficiency_pct: readNum(source['avg_efficiency_pct']),
    otd_pct: readNum(source['otd_pct']),
    total_bundles: readNum(source['total_bundles']),
    total_work_orders: readNum(source['total_work_orders']),
  };
}

function readGroupBy(value: unknown): ProductionGroupBy {
  const raw = readStr(value);
  return PRODUCTION_GROUP_BY_VALUES.includes(raw as ProductionGroupBy)
    ? (raw as ProductionGroupBy)
    : PRODUCTION_GROUP_BY_DEFAULT;
}

function readFilters(raw: unknown): ProductionReportFilters {
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
    work_center_id:
      typeof source['work_center_id'] === 'number' ? source['work_center_id'] : null,
    line_id: typeof source['line_id'] === 'number' ? source['line_id'] : null,
    nocache: readBool(source['nocache']),
    basis: readStrRecord(source['basis']),
    resolved_from: readStr(source['resolved_from']),
    resolved_to: readStr(source['resolved_to']),
  };
}

/** PURE - respons mentah -> `ProductionReportResponse`; `null` kalau `rows` bukan array. */
export function readProductionReport(raw: unknown): ProductionReportResponse | null {
  if (!isRecord(raw)) return null;
  if (!Array.isArray(raw['rows'])) return null;

  const rows: ProductionReportRow[] = [];
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

/** PURE - path + query `GET /reports/production/` (hanya param terisi yang dikirim). */
export function buildReportsProductionPath(query: ProductionReportQuery = {}): string {
  return buildQueryPath(REPORTS_PRODUCTION_PATH, {
    period: query.period ?? null,
    date_from: query.dateFrom ?? null,
    date_to: query.dateTo ?? null,
    from: query.from ?? null,
    to: query.to ?? null,
    work_center_id: query.workCenterId ?? null,
    line_id: query.lineId ?? null,
    group_by: query.groupBy ?? null,
    _nocache: query.nocache === true ? 1 : null,
  });
}

/** Baca laporan produksi. Gagal HTTP -> melempar (`unwrap` di `getParsed`). */
export async function fetchProductionReport(
  client: ApiClient,
  query: ProductionReportQuery = {},
): Promise<ProductionReportResponse> {
  return getParsed(
    client,
    buildReportsProductionPath(query),
    readProductionReport,
    'laporan produksi',
  );
}
