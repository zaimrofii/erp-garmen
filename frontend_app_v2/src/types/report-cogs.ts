/**
 * report-cogs.ts - kontrak laporan HPP/laba kotor (H4.4).
 *
 * Endpoint: `GET /api/v1/reports/cogs/` (`integrations/erp_sync/monitoring.py:ReportsCogsView`).
 * Read-only, DB murni (tanpa Odoo/Celery), cache backend 300 detik.
 *
 * Field `snake_case` **dipakai apa adanya** dari backend (Aturan Mutlak #5):
 * angka TIDAK dihitung ulang di UI.
 *
 * Catatan semantik (keputusan H4.4, lihat `decisions[]` di docs JSON):
 *   * HPP **simplified**: `cogs = qty x Product.cost_price` (tenaga kerja +
 *     overhead = sprint terpisah); omzet = `qty x OrderLine.price_unit`;
 *   * `gross_profit = sales - cogs`; `gross_margin_pct = gross_profit / sales x 100`
 *     (`sales = 0` -> `0`, tanpa divide-by-zero);
 *   * `cost_price = 0` atau `product` NULL -> COGS 0 (**tidak difabrikasi**);
 *     baris agregat ditandai `has_missing_cost` + `missing_cost_reason`
 *     (`no_product` menang atas `no_cost`), total di `summary.rows_with_missing_cost`;
 *   * basis periode = `Order.created_at` (accrual, konsisten H4.1), order CANCELLED dibuang.
 */

/** Grup agregat yang didukung backend (`?group_by=`). */
export type CogsGroupBy = 'period' | 'customer' | 'product';

/** Nilai `?order_type=` (turunan `Order.OrderType`). */
export type CogsOrderType = 'EXPORT' | 'CUSTOM' | 'BRAND';

/** Alasan COGS baris hilang: produk belum tersinkron atau `cost_price` masih 0. */
export type CogsMissingCostReason = 'no_cost' | 'no_product';

/** Satu baris agregat. Field identitas grup hanya ada sesuai `group_by`. */
export interface CogsReportRow {
  /** `YYYY-MM` (period) atau kode master (customer/product); `''` bila master NULL. */
  key: string;
  /** Nama tampil baris (bulan, nama customer, atau nama produk). */
  label: string;
  sales_amount: number;
  cogs_amount: number;
  gross_profit: number;
  gross_margin_pct: number;
  order_count: number;
  line_count: number;
  qty_total: number;
  /** `true` kalau baris ini memuat baris order yang COGS-nya tidak bisa dihitung. */
  has_missing_cost: boolean;
  /** `null` kalau `has_missing_cost = false`. */
  missing_cost_reason: CogsMissingCostReason | null;
  /** Hanya `group_by=period`. */
  period?: string;
  /** Hanya `group_by=customer` (`null` = order tanpa customer). */
  customer_id?: number | null;
  customer_code?: string;
  customer_name?: string;
  /** Hanya `group_by=product` (`null` = baris tanpa produk). */
  product_id?: number | null;
  product_code?: string;
  product_name?: string;
  /** Hanya `group_by=product` (sama dengan `qty_total`). */
  qty?: number;
}

/** Ringkasan periode (omzet, HPP, laba kotor, margin %, penanda data hilang). */
export interface CogsReportSummary {
  total_sales: number;
  total_cogs: number;
  total_gross_profit: number;
  gross_margin_pct: number;
  order_count: number;
  line_count: number;
  qty_total: number;
  /** Jumlah baris OrderLine yang COGS-nya tidak bisa dihitung (`cost_price=0` / produk NULL). */
  rows_with_missing_cost: number;
  /** `IDR` (laporan uang; konsisten H4.1/H4.2). */
  currency: string;
}

/** Echo filter efektif dari backend (`null` = klien tidak mengirim param itu). */
export interface CogsReportFilters {
  period: string | null;
  date_from: string | null;
  date_to: string | null;
  from: string | null;
  to: string | null;
  group_by: CogsGroupBy;
  customer_id: number | null;
  product_id: number | null;
  order_type: string | null;
  nocache: boolean;
  /** Rentang yang benar-benar dipakai (ISO-8601). */
  resolved_from: string;
  resolved_to: string;
}

/** Respons `GET /reports/cogs/`. */
export interface CogsReportResponse {
  rows: CogsReportRow[];
  summary: CogsReportSummary;
  group_by: CogsGroupBy;
  filters: CogsReportFilters;
  period: { from: string; to: string };
  generated_at: string;
  /** `true` kalau respons diambil dari cache 300 detik backend. */
  cached: boolean;
}
