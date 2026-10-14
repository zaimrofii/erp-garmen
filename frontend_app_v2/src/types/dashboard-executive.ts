/**
 * dashboard-executive.ts - kontrak Dashboard Eksekutif (H4.7).
 *
 * Endpoint: `GET /api/v1/dashboard/executive/` (`integrations/erp_sync/monitoring.py:ExecutiveDashboardView`).
 * Read-only, **ORKESTRASI** helper internal H4.1-H4.6 (tanpa memanggil view HTTP),
 * cache backend 300 detik, budget <= 15 query DB (+ 2 RPC Odoo untuk stok).
 *
 * Field `snake_case` **dipakai apa adanya** dari backend (Aturan Mutlak #5): angka
 * TIDAK dihitung ulang di UI.
 *
 * Catatan semantik (keputusan H4.7, lihat `decisions[]` di docs JSON):
 *   * setiap section = angka dari laporan H4.x pemiliknya (rumus TIDAK diduplikasi):
 *     `sales`/`cogs`/`pnl` bahkan berbagi SATU agregat `OrderLine`;
 *   * `stock` bisa **`null`** - fail-safe PARTIAL: bila Odoo tak terbaca, hanya
 *     section ini yang kosong (+ alert), section lain tetap terisi;
 *   * `pnl.opex` bisa `null` (`opex_source = 'unavailable'`) -> laba bersih = laba kotor;
 *   * `alerts` = `string[]` informatif (BEDA dari B2 `/dashboard/summary/` yang memakai
 *     objek `{code, message, severity}` karena konteksnya operasional);
 *   * metrik top-N (`top_customer`/`top_vendor`) sengaja TIDAK ada - drill-down ke
 *     halaman H4.1/H4.2;
 *   * **BEDA** dari B2 `DashboardSummaryView` (snapshot lantai HARI INI + tren 7 hari):
 *     endpoint H4.7 berdimensi PERIODE bulan dan TIDAK mengubah B2.
 */

import type { PnlOpexSource } from '@/types/report-pnl';

/** Penjualan periode - reuse rumus H4.1 (`Sigma qty x price_unit`). */
export interface ExecutiveSalesSection {
  /** Order non-CANCELLED dengan `Order.created_at` dalam rentang (accrual). */
  total_amount: number;
  count_orders: number;
  count_lines: number;
}

/** Pembelian periode - reuse rumus H4.2/`PurchaseOrder.created_at`. */
export interface ExecutivePurchasesSection {
  total_amount: number;
  count_purchases: number;
  count_lines: number;
}

/** Snapshot stok Odoo (H4.3) - murni kuantitas, TANPA `currency`. */
export interface ExecutiveStockSection {
  total_qty: number;
  product_count: number;
  location_count: number;
  /** Produk Odoo yang belum punya master MES (`Product.odoo_id`) - sumber alert. */
  unmapped_product_count: number;
}

/** HPP/laba kotor periode - reuse rumus H4.4. */
export interface ExecutiveCogsSection {
  /** Sigma `qty x Product.cost_price` (HPP simplified). */
  total_cogs: number;
  gross_profit: number;
  gross_margin_pct: number;
  /** Baris order tanpa HPP (produk belum tersinkron / `cost_price` masih 0). */
  rows_with_missing_cost: number;
}

/** Laba-rugi periode - reuse rantai + metadata opex H4.5. */
export interface ExecutivePnlSection {
  revenue: number;
  cogs: number;
  gross_profit: number;
  gross_margin_pct: number;
  /** `null` bila `opex_source = 'unavailable'` (angka tidak dikarang). */
  opex: number | null;
  net_profit: number;
  net_margin_pct: number;
  opex_source: PnlOpexSource | string;
  /** Tipe akun yang dihitung sebagai opex (transparansi/audit). */
  opex_account_types: string[];
  /** State `JournalEntry` yang dihitung sebagai opex. */
  opex_states: string[];
}

/** Produksi periode - reuse metrik H4.6 (basis ganda: output vs scrap). */
export interface ExecutiveProductionSection {
  output_pcs: number;
  scrap_pcs: number;
  /** `scrap / (output + scrap) x 100`; denominator 0 -> `0`. */
  scrap_pct: number;
  /** Terpisah dari `scrap_pcs` (konsep berbeda). */
  rework_pcs: number;
  /** Terpisah dari `scrap_pcs` (konsep berbeda). */
  end_loss_pcs: number;
  avg_efficiency_pct: number;
  /** Metrik order-level (pola B20). */
  otd_pct: number;
  total_bundles: number;
  total_work_orders: number;
}

/** Echo filter efektif (ADDITIF di H4.7 - konsisten H4.1-H4.6). */
export interface ExecutiveDashboardFilters {
  period: string | null;
  date_from: string | null;
  date_to: string | null;
  from: string | null;
  to: string | null;
  nocache: boolean;
  resolved_from: string;
  resolved_to: string;
}

/** Respons `GET /dashboard/executive/` (nested per laporan + alerts). */
export interface ExecutiveDashboardResponse {
  period: { from: string; to: string };
  filters: ExecutiveDashboardFilters;
  sales: ExecutiveSalesSection;
  purchases: ExecutivePurchasesSection;
  /** `null` = stok tidak terbaca dari Odoo (fail-safe partial; lihat `alerts`). */
  stock: ExecutiveStockSection | null;
  cogs: ExecutiveCogsSection;
  pnl: ExecutivePnlSection;
  production: ExecutiveProductionSection;
  /** Peringatan informatif (urutan: stok, opex, produk tanpa odoo_id, baris tanpa HPP). */
  alerts: string[];
  generated_at: string;
  cached: boolean;
}
