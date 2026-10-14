// ADAPTER - satu-satunya pintu data Reports/KPI (TANPA logic domain).
//
// F3A.CLOSE: SELURUH key `reports*` = REAL (backend B13/B16 + F3A B18–B21).
// Tidak ada lagi import dummy di sini.
import { pickAdapter } from './_adapter';
import * as realCogs from './real/reportCogs';
import * as realEff from './real/reportsLineEfficiency';
import * as realEffByWc from './real/reportsLineEfficiencyByWc';
import * as realLeadTime from './real/reportsLeadTime';
import * as realLeadTimeBundles from './real/reportsLeadTimeBundles';
import * as realOtd from './real/reportsOnTimeDelivery';
import * as realOtdOrders from './real/reportsOnTimeDeliveryOrders';
import * as realPnl from './real/reportPnl';
import * as realProduction from './real/reportProduction';
import * as realPurchases from './real/reportPurchases';
import * as realSales from './real/reportSales';
import * as realStock from './real/reportStock';
import * as realWip from './real/reportsWIP';
import * as realWipByWc from './real/reportsWipByWc';

/** Laporan efisiensi lini (LineEfficiencyPage) — REAL (B13 + G4b). */
export const fetchLineEfficiency = pickAdapter(
  'reportsLineEfficiency',
  realEff.fetchLineEfficiency,
  realEff.fetchLineEfficiency,
);
export {
  buildLineEfficiencyPath,
  LINE_EFFICIENCY_PATH,
  readLineEfficiencyReport,
} from './real/reportsLineEfficiency';
export type {
  LineEfficiencyReport,
  LineEfficiencyRow,
  ReportSeriesPoint,
  ReportTrendPoint,
} from './real/reportsLineEfficiency';

/** Laporan lead time per bundle + stages (LeadTimePage) — REAL (F3A.CLOSE, B19). */
export const fetchLeadTime = pickAdapter(
  'reportsLeadTime',
  realLeadTime.fetchLeadTime,
  realLeadTime.fetchLeadTime,
);
export { buildReportsLeadTimePath, LEAD_TIME_PATH, readLeadTimeReport } from './real/reportsLeadTime';
export type { LeadTimeReport, LeadTimeRow, LeadTimeStage } from './real/reportsLeadTime';

/** Laporan OTD per work order (OnTimeDeliveryPage) — REAL (F3A.CLOSE, B20). */
export const fetchOnTimeDelivery = pickAdapter(
  'reportsOTD',
  realOtd.fetchOnTimeDelivery,
  realOtd.fetchOnTimeDelivery,
);
export { buildReportsOtdPath, ON_TIME_DELIVERY_PATH, readOtdReport } from './real/reportsOnTimeDelivery';
export type { OtdReport, OtdRow } from './real/reportsOnTimeDelivery';

/** Laporan WIP per work center (WIPPage) — REAL (B16 + G4). */
export const fetchWip = pickAdapter('reportsWIP', realWip.fetchWip, realWip.fetchWip);
export { buildReportsWipPath, readWipReport, REPORTS_WIP_PATH } from './real/reportsWIP';
export type { WipReport, WipRow, WipSeriesPoint, WipTrendPoint } from './real/reportsWIP';

/* ------------------------------------------------------------------
   Sub-route detail (F3A.CLOSE / B18 / B19b / B20b / B21) — semuanya REAL.
   ------------------------------------------------------------------ */

/** Tabel efisiensi per work center (LineEfficiencyPage). */
export const fetchLineEfficiencyByWc = pickAdapter(
  'reportsLineEfficiencyByWc',
  realEffByWc.fetchLineEfficiencyByWc,
  realEffByWc.fetchLineEfficiencyByWc,
);
export {
  buildLineEfficiencyByWcPath,
  LINE_EFFICIENCY_BY_WC_PATH,
  readLineEfficiencyByWcReport,
} from './real/reportsLineEfficiencyByWc';
export type {
  LineEfficiencyByWcReport,
  LineEfficiencyByWcRow,
} from './real/reportsLineEfficiencyByWc';

/** Tabel lead time per bundle, flat (LeadTimePage). */
export const fetchLeadTimeBundles = pickAdapter(
  'reportsLeadTimeBundles',
  realLeadTimeBundles.fetchLeadTimeBundles,
  realLeadTimeBundles.fetchLeadTimeBundles,
);
export {
  buildLeadTimeBundlesPath,
  LEAD_TIME_BUNDLES_PATH,
  readLeadTimeBundlePage,
} from './real/reportsLeadTimeBundles';
export type { LeadTimeBundleRow } from './real/reportsLeadTimeBundles';

/** Tabel ketepatan kirim agregat per order (OnTimeDeliveryPage). */
export const fetchOnTimeDeliveryOrders = pickAdapter(
  'reportsOnTimeDeliveryOrders',
  realOtdOrders.fetchOnTimeDeliveryOrders,
  realOtdOrders.fetchOnTimeDeliveryOrders,
);
export {
  buildOtdOrdersPath,
  ON_TIME_DELIVERY_ORDERS_PATH,
  readOtdOrderPage,
} from './real/reportsOnTimeDeliveryOrders';
export type { OtdOrderRow } from './real/reportsOnTimeDeliveryOrders';

/** Tabel sebaran WIP per work center, flat (WIPPage). */
export const fetchWipByWc = pickAdapter(
  'reportsWipByWc',
  realWipByWc.fetchWipByWc,
  realWipByWc.fetchWipByWc,
);
export { readWipByWcReport, WIP_BY_WC_PATH } from './real/reportsWipByWc';
export type { WipByWcReport, WipByWcRow } from './real/reportsWipByWc';

/* ------------------------------------------------------------------
   H4.1 - laporan penjualan (SalesReportPage) - REAL, DB murni + cache 300 dtk.
   ------------------------------------------------------------------ */

/** Laporan penjualan agregat (SalesReportPage) - REAL (H4.1). */
export const fetchSalesReport = pickAdapter(
  'reportSales',
  realSales.fetchSalesReport,
  realSales.fetchSalesReport,
);
export {
  buildReportsSalesPath,
  readSalesReport,
  REPORTS_SALES_PATH,
  SALES_GROUP_BY_DEFAULT,
  SALES_GROUP_BY_VALUES,
  SALES_ORDER_TYPES,
} from './real/reportSales';
export type { SalesReportQuery } from './real/reportSales';
export type {
  SalesGroupBy,
  SalesOrderType,
  SalesReportFilters,
  SalesReportResponse,
  SalesReportRow,
  SalesReportSummary,
} from '@/types/report-sales';

/* ------------------------------------------------------------------
   H4.2 - laporan pembelian (PurchasesReportPage) - REAL, DB murni + cache 300 dtk.
   ------------------------------------------------------------------ */

/** Laporan pembelian agregat (PurchasesReportPage) - REAL (H4.2). */
export const fetchPurchasesReport = pickAdapter(
  'reportPurchases',
  realPurchases.fetchPurchasesReport,
  realPurchases.fetchPurchasesReport,
);
export {
  buildReportsPurchasesPath,
  readPurchasesReport,
  REPORTS_PURCHASES_PATH,
  PURCHASES_GROUP_BY_DEFAULT,
  PURCHASES_GROUP_BY_VALUES,
  PURCHASES_STATUS_VALUES,
} from './real/reportPurchases';
export type { PurchasesReportQuery } from './real/reportPurchases';
export type {
  PurchasesGroupBy,
  PurchasesReportFilters,
  PurchasesReportResponse,
  PurchasesReportRow,
  PurchasesReportSummary,
  PurchasesStatus,
} from '@/types/report-purchases';

/* ------------------------------------------------------------------
   H4.3 - laporan stok (StockReportPage) - REAL, snapshot Odoo via I7 + cache 300 dtk.
   ------------------------------------------------------------------ */

/** Laporan stok snapshot (StockReportPage) - REAL (H4.3). */
export const fetchStockReport = pickAdapter(
  'reportStock',
  realStock.fetchStockReport,
  realStock.fetchStockReport,
);
export {
  buildReportsStockPath,
  readStockReport,
  REPORTS_STOCK_PATH,
  STOCK_GROUP_BY_DEFAULT,
  STOCK_GROUP_BY_VALUES,
} from './real/reportStock';
export type { StockReportQuery } from './real/reportStock';
export type {
  StockGroupBy,
  StockReportFilters,
  StockReportResponse,
  StockReportRow,
  StockReportSummary,
} from '@/types/report-stock';

/* ------------------------------------------------------------------
   H4.4 - laporan HPP/laba kotor (CogsReportPage) - REAL, DB murni + cache 300 dtk.
   ------------------------------------------------------------------ */

/** Laporan HPP/laba kotor agregat (CogsReportPage) - REAL (H4.4). */
export const fetchCogsReport = pickAdapter(
  'reportCogs',
  realCogs.fetchCogsReport,
  realCogs.fetchCogsReport,
);
export {
  buildReportsCogsPath,
  readCogsReport,
  readMissingCostReason,
  REPORTS_COGS_PATH,
  COGS_GROUP_BY_DEFAULT,
  COGS_GROUP_BY_VALUES,
  COGS_ORDER_TYPES,
} from './real/reportCogs';
export type { CogsReportQuery } from './real/reportCogs';
export type {
  CogsGroupBy,
  CogsMissingCostReason,
  CogsOrderType,
  CogsReportFilters,
  CogsReportResponse,
  CogsReportRow,
  CogsReportSummary,
} from '@/types/report-cogs';

/* ------------------------------------------------------------------
   H4.5 - laporan laba-rugi / PnL (PnlReportPage) - REAL, DB murni + cache 300 dtk.
   ------------------------------------------------------------------ */

/** Laporan laba-rugi agregat (PnlReportPage) - REAL (H4.5). */
export const fetchPnlReport = pickAdapter(
  'reportPnl',
  realPnl.fetchPnlReport,
  realPnl.fetchPnlReport,
);
export {
  buildReportsPnlPath,
  readPnlReport,
  readPnlMissingReason,
  readStrList,
  REPORTS_PNL_PATH,
  PNL_GROUP_BY_DEFAULT,
  PNL_GROUP_BY_VALUES,
} from './real/reportPnl';
export type { PnlReportQuery } from './real/reportPnl';
export type {
  PnlGroupBy,
  PnlMissingCostReason,
  PnlOpexSource,
  PnlReportFilters,
  PnlReportResponse,
  PnlReportRow,
  PnlReportSummary,
} from '@/types/report-pnl';

/* ------------------------------------------------------------------
   H4.6 - laporan produksi (ProductionReportPage) - REAL, DB murni + cache 300 dtk.
   ------------------------------------------------------------------ */

/** Laporan produksi agregat (ProductionReportPage) - REAL (H4.6). */
export const fetchProductionReport = pickAdapter(
  'reportProduction',
  realProduction.fetchProductionReport,
  realProduction.fetchProductionReport,
);
export {
  buildReportsProductionPath,
  readProductionReport,
  readStrRecord,
  REPORTS_PRODUCTION_PATH,
  PRODUCTION_GROUP_BY_DEFAULT,
  PRODUCTION_GROUP_BY_VALUES,
} from './real/reportProduction';
export type { ProductionReportQuery } from './real/reportProduction';
export type {
  ProductionGroupBy,
  ProductionReportFilters,
  ProductionReportResponse,
  ProductionReportRow,
  ProductionReportSummary,
} from '@/types/report-production';

