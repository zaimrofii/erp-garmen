// ADAPTER - satu-satunya pintu riwayat rekonsiliasi stok MES vs Odoo (TANPA logic domain).
//
// Halaman WAJIB mengimpor dari sini - JANGAN dari `./real/*` langsung.
//
// F9/9.0 - MODE `reconciliation` === 'real': `GET /reconciliation/report/?days=N` (§6.2),
// `IsAuthenticated` (anon 403), `days` 1..90 (di luar itu 400 dari backend).
// Belum ada versi dummy -> slot dummy diisi implementasi real (pola `api/readiness.ts`).
import { pickAdapter } from './_adapter';
import * as real from './real/reconciliation';

/** Riwayat rekonsiliasi `days` hari terakhir (§6.2). */
export const getReconciliationReport = pickAdapter(
  'reconciliation',
  real.getReconciliationReport,
  real.getReconciliationReport,
);

export {
  buildReconciliationReportPath,
  parseReconciliationDays,
  readReconciliationEntry,
  readReconciliationReport,
  RECONCILIATION_DAYS_DEFAULT,
  RECONCILIATION_DAYS_MAX,
  RECONCILIATION_DAYS_MIN,
  RECONCILIATION_REPORT_PATH,
} from './real/reconciliation';
export type { ReconciliationEntry, ReconciliationReport } from './real/reconciliation';
