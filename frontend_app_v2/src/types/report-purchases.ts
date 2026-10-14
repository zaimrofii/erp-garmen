/**
 * report-purchases.ts - kontrak laporan pembelian (H4.2).
 *
 * Endpoint: `GET /api/v1/reports/purchases/` (`integrations/erp_sync/monitoring.py:ReportsPurchasesView`).
 * Read-only, DB murni (tanpa Odoo/Celery), cache backend 300 detik.
 *
 * Field `snake_case` **dipakai apa adanya** dari backend (Aturan Mutlak #5):
 * rencana unit & angka TIDAK dihitung ulang di UI.
 *
 * Catatan semantik (keputusan H4.2, lihat `decisions[]` di docs JSON):
 *   * periode = basis `PurchaseOrder.created_at` (accrual - pembelian diakui saat PO dibuat);
 *   * `summary.billed_amount` = utang (`VendorBillLine.line_total`, SEBELUM pajak,
 *     bill CANCELLED dibuang) - bukan kas;
 *   * `summary.paid_amount` = Sum `Payment.amount` OUTBOUND state SENT/DONE
 *     (`payment_date` dalam periode) - BUKAN dari `VendorBill.amount_total`;
 *   * `total_qty` **float** (qty pembelian boleh pecahan, mis. benang 0.3).
 */

/** Grup agregat yang didukung backend (`?group_by=`). */
export type PurchasesGroupBy = 'period' | 'vendor' | 'product';

/** Nilai `?status=` (state `PurchaseOrder` MES H2.2). */
export type PurchasesStatus = 'DRAFT' | 'CONFIRMED' | 'DONE' | 'CANCELLED';

/** Satu baris agregat. Field identitas grup hanya ada sesuai `group_by`. */
export interface PurchasesReportRow {
  /** `YYYY-MM` (period) atau kode master (vendor/product); `''` bila master NULL. */
  key: string;
  /** Nama tampil baris (bulan, nama vendor, atau nama produk). */
  label: string;
  /** Satuan nilai (`IDR` - nilai uang). */
  unit: string;
  /** Alias `total_amount` (pola G4: `label`/`unit`/`value` untuk chart). */
  value: number;
  /** **float** - qty pembelian boleh pecahan (mis. benang 0.3). */
  total_qty: number;
  total_amount: number;
  purchase_count: number;
  line_count: number;
  /** Hanya `group_by=period`. */
  period?: string;
  /** Hanya `group_by=vendor` (`null` = baris tanpa vendor; di MES vendor WAJIB). */
  vendor_id?: number | null;
  vendor_code?: string;
  vendor_name?: string;
  /** Hanya `group_by=product` (`null` = baris tanpa produk). */
  product_id?: number | null;
  product_code?: string;
  product_name?: string;
}

/** Ringkasan periode (PO-side + utang bill + kas keluar). */
export interface PurchasesReportSummary {
  total_qty: number;
  total_amount: number;
  count_purchases: number;
  count_lines: number;
  billed_amount: number;
  bill_count: number;
  paid_amount: number;
  payment_count: number;
  /** `IDR` (MES-only; Odoo yang menentukan currency dokumennya). */
  currency: string;
}

/** Echo filter efektif dari backend (`null` = klien tidak mengirim param itu). */
export interface PurchasesReportFilters {
  period: string | null;
  date_from: string | null;
  date_to: string | null;
  from: string | null;
  to: string | null;
  group_by: PurchasesGroupBy;
  vendor_id: number | null;
  product_id: number | null;
  status: string | null;
  nocache: boolean;
  /** Rentang yang benar-benar dipakai (ISO-8601). */
  resolved_from: string;
  resolved_to: string;
}

/** Respons `GET /reports/purchases/`. */
export interface PurchasesReportResponse {
  rows: PurchasesReportRow[];
  summary: PurchasesReportSummary;
  group_by: PurchasesGroupBy;
  filters: PurchasesReportFilters;
  period: { from: string; to: string };
  generated_at: string;
  /** `true` kalau respons diambil dari cache 300 detik backend. */
  cached: boolean;
}
