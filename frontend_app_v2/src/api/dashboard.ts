// ADAPTER - satu-satunya pintu data Dashboard (TANPA logic domain).
//
// F2C.2: MODE `dashboard` === 'real' (`GET /api/v1/dashboard/summary/`, B1 + G1).
import { pickAdapter } from './_adapter';
import * as real from './real/dashboard';
import * as realExecutive from './real/executiveDashboard';

/** Ringkasan pabrik (DashboardPage / SupervisorDashboardPage). */
export const fetchDashboardSummary = pickAdapter(
  'dashboard',
  real.fetchDashboardSummary,
  real.fetchDashboardSummary,
);

export { DASHBOARD_SUMMARY_PATH, readDashboardSummary } from './real/dashboard';
export type {
  DashboardAlert,
  DashboardBundleCounts,
  DashboardLineEfficiency,
  DashboardOrderCounts,
  DashboardSummary,
  DashboardTrendPoint,
} from './real/dashboard';

/* ------------------------------------------------------------------
   H4.7 - dashboard eksekutif (ExecutiveDashboardPage) - REAL, orkestrasi
   H4.1-H4.6 (cache 300 dtk). PARALEL dengan B2 `dashboard` di atas
   (`/dashboard/summary/` TIDAK diubah).
   ------------------------------------------------------------------ */

/** Dashboard eksekutif agregat (ExecutiveDashboardPage) - REAL (H4.7). */
export const fetchExecutiveDashboard = pickAdapter(
  'executiveDashboard',
  realExecutive.fetchExecutiveDashboard,
  realExecutive.fetchExecutiveDashboard,
);
export {
  buildExecutiveDashboardPath,
  readExecutiveDashboard,
  EXECUTIVE_DASHBOARD_PATH,
} from './real/executiveDashboard';
export type { ExecutiveDashboardQuery } from './real/executiveDashboard';
export type {
  ExecutiveCogsSection,
  ExecutiveDashboardFilters,
  ExecutiveDashboardResponse,
  ExecutivePnlSection,
  ExecutiveProductionSection,
  ExecutivePurchasesSection,
  ExecutiveSalesSection,
  ExecutiveStockSection,
} from '@/types/dashboard-executive';

