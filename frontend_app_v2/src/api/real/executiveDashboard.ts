// REAL - dashboard eksekutif (H4.7). Endpoint: GET /api/v1/dashboard/executive/
//
// Backend `monitoring.ExecutiveDashboardView` (H4.7) - ORKESTRASI helper internal
// H4.1-H4.6 (bukan memanggil view HTTP, bukan menyalin rumus). Non-ListPage:
// respons NESTED per laporan + `alerts[]`.
//
// Param (prioritas backend): `?period=YYYY-MM` > `?date_from`/`?date_to` >
// `?from`/`?to` (default bulan berjalan) + `?_nocache=1`.
import type { ApiClient } from '@/integrations/api-client';
import type {
  ExecutiveCogsSection,
  ExecutiveDashboardFilters,
  ExecutiveDashboardResponse,
  ExecutivePnlSection,
  ExecutiveProductionSection,
  ExecutivePurchasesSection,
  ExecutiveSalesSection,
  ExecutiveStockSection,
} from '@/types/dashboard-executive';
import { buildQueryPath, getParsed, isRecord, readBool, readNum, readStr } from './_shape';

/** Path relatif terhadap `VITE_API_BASE_URL` (`.../api/v1`). */
export const EXECUTIVE_DASHBOARD_PATH = '/dashboard/executive/';

/** Param UI -> query string (nilai kosong dilewati oleh `buildQueryPath`). */
export interface ExecutiveDashboardQuery {
  /** `YYYY-MM`; default backend = bulan berjalan. */
  period?: string | null;
  dateFrom?: string | null;
  dateTo?: string | null;
  /** Alias lama (family report): hanya dipakai kalau `dateFrom`/`dateTo` kosong. */
  from?: string | null;
  to?: string | null;
  /** `true` -> `?_nocache=1` (bypass cache backend; debug/force refresh). */
  nocache?: boolean;
}

/** PURE - daftar string (mis. `alerts`, `opex_account_types`); bukan array -> `[]`. */
function readStrArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string => typeof item === 'string');
}

function readSales(raw: unknown): ExecutiveSalesSection {
  const source = isRecord(raw) ? raw : {};
  return {
    total_amount: readNum(source['total_amount']),
    count_orders: readNum(source['count_orders']),
    count_lines: readNum(source['count_lines']),
  };
}

function readPurchases(raw: unknown): ExecutivePurchasesSection {
  const source = isRecord(raw) ? raw : {};
  return {
    total_amount: readNum(source['total_amount']),
    count_purchases: readNum(source['count_purchases']),
    count_lines: readNum(source['count_lines']),
  };
}

/** `null` = Odoo tak terbaca (fail-safe partial H4.7) - BUKAN nol. */
function readStock(raw: unknown): ExecutiveStockSection | null {
  if (!isRecord(raw)) return null;
  return {
    total_qty: readNum(raw['total_qty']),
    product_count: readNum(raw['product_count']),
    location_count: readNum(raw['location_count']),
    unmapped_product_count: readNum(raw['unmapped_product_count']),
  };
}

function readCogs(raw: unknown): ExecutiveCogsSection {
  const source = isRecord(raw) ? raw : {};
  return {
    total_cogs: readNum(source['total_cogs']),
    gross_profit: readNum(source['gross_profit']),
    gross_margin_pct: readNum(source['gross_margin_pct']),
    rows_with_missing_cost: readNum(source['rows_with_missing_cost']),
  };
}

function readPnl(raw: unknown): ExecutivePnlSection {
  const source = isRecord(raw) ? raw : {};
  return {
    revenue: readNum(source['revenue']),
    cogs: readNum(source['cogs']),
    gross_profit: readNum(source['gross_profit']),
    gross_margin_pct: readNum(source['gross_margin_pct']),
    // `null` = opex belum tersedia (jangan ditampilkan sebagai 0).
    opex:
      typeof source['opex'] === 'number' && Number.isFinite(source['opex'])
        ? source['opex']
        : null,
    net_profit: readNum(source['net_profit']),
    net_margin_pct: readNum(source['net_margin_pct']),
    opex_source: readStr(source['opex_source']),
    opex_account_types: readStrArray(source['opex_account_types']),
    opex_states: readStrArray(source['opex_states']),
  };
}

function readProduction(raw: unknown): ExecutiveProductionSection {
  const source = isRecord(raw) ? raw : {};
  return {
    output_pcs: readNum(source['output_pcs']),
    scrap_pcs: readNum(source['scrap_pcs']),
    scrap_pct: readNum(source['scrap_pct']),
    rework_pcs: readNum(source['rework_pcs']),
    end_loss_pcs: readNum(source['end_loss_pcs']),
    avg_efficiency_pct: readNum(source['avg_efficiency_pct']),
    otd_pct: readNum(source['otd_pct']),
    total_bundles: readNum(source['total_bundles']),
    total_work_orders: readNum(source['total_work_orders']),
  };
}

function readFilters(raw: unknown): ExecutiveDashboardFilters {
  const source = isRecord(raw) ? raw : {};
  const strOrNull = (value: unknown): string | null =>
    typeof value === 'string' ? value : null;

  return {
    period: strOrNull(source['period']),
    date_from: strOrNull(source['date_from']),
    date_to: strOrNull(source['date_to']),
    from: strOrNull(source['from']),
    to: strOrNull(source['to']),
    nocache: readBool(source['nocache']),
    resolved_from: readStr(source['resolved_from']),
    resolved_to: readStr(source['resolved_to']),
  };
}

/** PURE - respons mentah -> `ExecutiveDashboardResponse`; `null` kalau bentuk inti rusak. */
export function readExecutiveDashboard(raw: unknown): ExecutiveDashboardResponse | null {
  if (!isRecord(raw)) return null;
  // Bentuk inti WAJIB ada: `period` + `sales` + `pnl` (section lain punya default aman).
  if (!isRecord(raw['period']) || !isRecord(raw['sales']) || !isRecord(raw['pnl'])) {
    return null;
  }

  const period = raw['period'];

  return {
    period: { from: readStr(period['from']), to: readStr(period['to']) },
    filters: readFilters(raw['filters']),
    sales: readSales(raw['sales']),
    purchases: readPurchases(raw['purchases']),
    stock: readStock(raw['stock']),
    cogs: readCogs(raw['cogs']),
    pnl: readPnl(raw['pnl']),
    production: readProduction(raw['production']),
    alerts: readStrArray(raw['alerts']),
    generated_at: readStr(raw['generated_at']),
    cached: readBool(raw['cached']),
  };
}

/** PURE - path + query `GET /dashboard/executive/` (hanya param terisi yang dikirim). */
export function buildExecutiveDashboardPath(query: ExecutiveDashboardQuery = {}): string {
  return buildQueryPath(EXECUTIVE_DASHBOARD_PATH, {
    period: query.period ?? null,
    date_from: query.dateFrom ?? null,
    date_to: query.dateTo ?? null,
    from: query.from ?? null,
    to: query.to ?? null,
    _nocache: query.nocache === true ? 1 : null,
  });
}

/** Baca dashboard eksekutif. Gagal HTTP -> melempar (`unwrap` di `getParsed`). */
export async function fetchExecutiveDashboard(
  client: ApiClient,
  query: ExecutiveDashboardQuery = {},
): Promise<ExecutiveDashboardResponse> {
  return getParsed(
    client,
    buildExecutiveDashboardPath(query),
    readExecutiveDashboard,
    'dashboard eksekutif',
  );
}
