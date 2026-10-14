/**
 * report-pnl.ts - kontrak laporan laba-rugi / PnL (H4.5).
 *
 * Endpoint: `GET /api/v1/reports/pnl/` (`integrations/erp_sync/monitoring.py:ReportsPnlView`).
 * Read-only, DB murni (tanpa Odoo/Celery), cache backend 300 detik.
 *
 * Field `snake_case` **dipakai apa adanya** dari backend (Aturan Mutlak #5):
 * angka TIDAK dihitung ulang di UI.
 *
 * Catatan semantik (keputusan H4.5, lihat `decisions[]` di docs JSON):
 *   * `revenue = qty x price_unit` (reuse H4.1/H4.4) -> `cogs = qty x Product.cost_price`
 *     (HPP simplified H4.4) -> `gross_profit = revenue - cogs`;
 *   * `opex` = Sigma(debit - credit) `JournalEntryLine` H3.4 pada akun
 *     expense/expense_depreciation/expense_direct_cost, state CONFIRMED|SENT|DONE;
 *   * `net_profit = gross_profit - opex`; margin % = laba / revenue x 100
 *     (revenue = 0 -> 0, tanpa divide-by-zero);
 *   * `opex` bisa `null`: chart of accounts belum punya akun expense ->
 *     `opex_source = 'unavailable'` dan `net_profit = gross_profit` (tidak dikarang);
 *   * basis periode = `Order.created_at` (accrual), order CANCELLED dibuang.
 */

/** Grup agregat yang didukung backend (`?group_by=`). */
export type PnlGroupBy = 'period' | 'quarter';

/** Alasan COGS baris hilang (reuse penanda H4.4). */
export type PnlMissingCostReason = 'no_cost' | 'no_product';

/** Sumber opex: dari jurnal H3.4 atau belum tersedia. */
export type PnlOpexSource = 'journal_entry' | 'unavailable';

/** Satu baris agregat (bucket bulan `YYYY-MM` atau kuartal `YYYY-Qn`). */
export interface PnlReportRow {
  key: string;
  label: string;
  revenue: number;
  cogs: number;
  gross_profit: number;
  gross_margin_pct: number;
  /** `null` = sumber opex tidak tersedia (net_profit = gross_profit). */
  opex: number | null;
  net_profit: number;
  net_margin_pct: number;
  order_count: number;
  line_count: number;
  has_missing_cost: boolean;
  missing_cost_reason: PnlMissingCostReason | null;
  /** Hanya `group_by=period`. */
  period?: string;
  /** Hanya `group_by=quarter`. */
  quarter?: string;
}

/** Ringkasan periode (rantai PnL + metadata sumber opex). */
export interface PnlReportSummary {
  revenue: number;
  cogs: number;
  gross_profit: number;
  gross_margin_pct: number;
  /** `null` bila `opex_source = 'unavailable'`. */
  opex: number | null;
  net_profit: number;
  net_margin_pct: number;
  opex_source: PnlOpexSource | string;
  /** Tipe akun yang dihitung sebagai opex (transparansi/audit). */
  opex_account_types: string[];
  /** State JournalEntry yang dihitung sebagai opex. */
  opex_states: string[];
  order_count: number;
  line_count: number;
  rows_with_missing_cost: number;
  /** `IDR` (laporan uang). */
  currency: string;
}

/** Echo filter efektif dari backend (TANPA customer/product - PnL agregat bisnis). */
export interface PnlReportFilters {
  period: string | null;
  date_from: string | null;
  date_to: string | null;
  from: string | null;
  to: string | null;
  group_by: PnlGroupBy;
  nocache: boolean;
  resolved_from: string;
  resolved_to: string;
}

/** Respons `GET /reports/pnl/`. */
export interface PnlReportResponse {
  rows: PnlReportRow[];
  summary: PnlReportSummary;
  group_by: PnlGroupBy;
  filters: PnlReportFilters;
  period: { from: string; to: string };
  generated_at: string;
  cached: boolean;
}
