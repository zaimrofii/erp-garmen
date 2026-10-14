/**
 * report-sales.ts - kontrak laporan penjualan (H4.1).
 *
 * Endpoint: `GET /api/v1/reports/sales/` (`integrations/erp_sync/monitoring.py:ReportsSalesView`).
 * Read-only, DB murni (tanpa Odoo/Celery), cache backend 300 detik.
 *
 * Field `snake_case` **dipakai apa adanya** dari backend (Aturan Mutlak #5):
 * rencana unit & angka TIDAK dihitung ulang di UI.
 *
 * Catatan semantik (keputusan H4.1, lihat `decisions[]` di docs JSON):
 *   * periode = basis `Order.created_at` (accrual - sales diakui saat order dibuat);
 *   * `summary.invoiced_amount` = piutang (`CustomerInvoiceLine.line_total`,
 *     SEBELUM pajak, invoice CANCELLED dibuang) - bukan kas;
 *   * `summary.paid_amount` = Σ `Payment.amount` INBOUND state SENT/DONE
 *     (`payment_date` dalam periode) - BUKAN dari `CustomerInvoice.amount_total`.
 */

/** Grup agregat yang didukung backend (`?group_by=`). */
export type SalesGroupBy = 'period' | 'customer' | 'product';

/** Nilai `?order_type=` (turunan `Order.OrderType`). */
export type SalesOrderType = 'EXPORT' | 'CUSTOM' | 'BRAND';

/** Satu baris agregat. Field identitas grup hanya ada sesuai `group_by`. */
export interface SalesReportRow {
  /** `YYYY-MM` (period) atau kode master (customer/product); `''` bila master NULL. */
  key: string;
  /** Nama tampil baris (bulan, nama customer, atau nama produk). */
  label: string;
  /** Satuan nilai (`IDR` - nilai uang). */
  unit: string;
  /** Alias `total_amount` (pola G4: `label`/`unit`/`value` untuk chart). */
  value: number;
  total_qty: number;
  total_amount: number;
  order_count: number;
  line_count: number;
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
}

/** Ringkasan periode (order-side + piutang + kas masuk). */
export interface SalesReportSummary {
  total_qty: number;
  total_amount: number;
  count_orders: number;
  count_lines: number;
  invoiced_amount: number;
  invoice_count: number;
  paid_amount: number;
  payment_count: number;
  /** `IDR` (MES-only; Odoo yang menentukan currency dokumennya). */
  currency: string;
}

/** Echo filter efektif dari backend (`null` = klien tidak mengirim param itu). */
export interface SalesReportFilters {
  period: string | null;
  date_from: string | null;
  date_to: string | null;
  from: string | null;
  to: string | null;
  group_by: SalesGroupBy;
  customer_id: number | null;
  product_id: number | null;
  order_type: string | null;
  nocache: boolean;
  /** Rentang yang benar-benar dipakai (ISO-8601). */
  resolved_from: string;
  resolved_to: string;
}

/** Respons `GET /reports/sales/`. */
export interface SalesReportResponse {
  rows: SalesReportRow[];
  summary: SalesReportSummary;
  group_by: SalesGroupBy;
  filters: SalesReportFilters;
  period: { from: string; to: string };
  generated_at: string;
  /** `true` kalau respons diambil dari cache 300 detik backend. */
  cached: boolean;
}
