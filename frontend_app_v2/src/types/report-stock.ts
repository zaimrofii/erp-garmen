/**
 * report-stock.ts - kontrak laporan stok (H4.3).
 *
 * Endpoint: `GET /api/v1/reports/stock/` (`integrations/erp_sync/monitoring.py:ReportsStockView`).
 * Read-only, snapshot **Odoo `stock.quant` LIVE** via jalur I7 (2 RPC), cache backend 300 detik.
 *
 * Field `snake_case` **dipakai apa adanya** dari backend (Aturan Mutlak #5):
 * angka TIDAK dihitung ulang di UI.
 *
 * Catatan semantik (keputusan H4.3, lihat `decisions[]` di docs JSON):
 *   * **snapshot, BUKAN time-series** - tidak ada `period`/`date_from`/`date_to`;
 *   * sumber = `stock.quant.quantity`/`reserved_quantity` (MES tidak menyimpan tabel
 *     stok, CHANGES-DETAIL bagian 4) - `available_qty = total_qty - reserved_qty`
 *     (dihitung backend);
 *   * **TANPA `currency`** - H4.3 murni quantity (nilai Rupiah / COGS = H4.4);
 *   * `summary.unmapped_product_count`/`unmapped_qty` = produk Odoo yang belum ter-map
 *     ke master MES (ditampilkan transparan supaya total bisa direkonsiliasi).
 */

/** Grup agregat yang didukung backend (`?group_by=`). */
export type StockGroupBy = 'product' | 'location';

/** Satu baris agregat. Field identitas grup hanya ada sesuai `group_by`. */
export interface StockReportRow {
  /** Kode produk (`group_by=product`) atau kode lokasi (`group_by=location`). */
  key: string;
  /** Nama tampil baris (nama produk / nama lokasi). */
  label: string;
  /** Satuan kuantitas fisik (`unit`) - BUKAN `IDR` (H4.3 tanpa nilai uang). */
  unit: string;
  total_qty: number;
  reserved_qty: number;
  available_qty: number;
  /** Hanya `group_by=product` (`null` = tidak ada). */
  product_id?: number | null;
  product_code?: string;
  product_name?: string;
  uom_code?: string;
  locations_count?: number;
  /** Hanya `group_by=location` (`null` = lokasi belum tersinkron ke MES). */
  location_id?: number | null;
  location_code?: string;
  location_name?: string;
  location_odoo_id?: number;
  products_count?: number;
}

/** Ringkasan snapshot (quantity fisik; TANPA `currency`). */
export interface StockReportSummary {
  total_qty: number;
  reserved_qty: number;
  available_qty: number;
  product_count: number;
  location_count: number;
  quant_count: number;
  /** Produk Odoo yang belum ter-map ke master MES (transparansi). */
  unmapped_product_count: number;
  unmapped_qty: number;
}

/** Echo filter efektif dari backend (`null` = klien tidak mengirim param itu). */
export interface StockReportFilters {
  group_by: StockGroupBy;
  location_id: number | null;
  product_id: number | null;
  search: string | null;
  only_nonzero: boolean;
  nocache: boolean;
  /** Selalu `odoo` - stok tidak pernah disimpan di MES. */
  source: string;
}

/** Respons `GET /reports/stock/`. */
export interface StockReportResponse {
  rows: StockReportRow[];
  summary: StockReportSummary;
  group_by: StockGroupBy;
  filters: StockReportFilters;
  generated_at: string;
  /** `true` kalau respons diambil dari cache 300 detik backend. */
  cached: boolean;
  /** `odoo` - sumber angka (snapshot live). */
  source: string;
}
