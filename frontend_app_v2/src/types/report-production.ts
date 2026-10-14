/**
 * report-production.ts - kontrak laporan produksi (H4.6).
 *
 * Endpoint: `GET /api/v1/reports/production/` (`integrations/erp_sync/monitoring.py:ReportsProductionView`).
 * Read-only, DB murni (tanpa Odoo/Celery), cache backend 300 detik.
 *
 * Field `snake_case` **dipakai apa adanya** dari backend (Aturan Mutlak #5):
 * angka TIDAK dihitung ulang di UI.
 *
 * Catatan semantik (keputusan H4.6, lihat `decisions[]` di docs JSON):
 *   * **superset** B13/B16/B18-B21: menambah dimensi PERIODE ke metrik produksi
 *     yang sudah ada (endpoint existing tidak diubah);
 *   * **basis waktu per metrik** (`filters.basis`): output/efisiensi/OTD =
 *     realisasi `BundleEvent.ts`; scrap = `ScrapAccumulator.created_at`;
 *   * `output_pcs` = Sigma `Bundle.qty_done` (bundle `state != CANCELLED`, ada FINISH
 *     dalam rentang; satu bundle dihitung sekali);
 *   * `scrap_pcs` = Sigma `ScrapAccumulator.qty`; `rework_qty`/`end_loss_qty`
 *     DIPISAH (3 konsep berbeda) - `scrap_pct = scrap / (output + scrap) x 100`;
 *   * `efficiency_pct` = rumus identik B13; `otd_pct` = metrik **order-level**
 *     (pola B20) - hanya di `group_by=period` + summary, `null` di baris WC/line;
 *   * **TANPA `currency`** - H4.6 murni kuantitas (pcs) + persentase (pola H4.3).
 */

/** Grup agregat yang didukung backend (`?group_by=`). */
export type ProductionGroupBy = 'period' | 'work_center' | 'line';

/** Satu baris agregat. Field identitas grup hanya ada sesuai `group_by`. */
export interface ProductionReportRow {
  /** `YYYY-MM` (period) atau kode master (work_center/line); `''` bila belum tersinkron. */
  key: string;
  label: string;
  output_pcs: number;
  scrap_pcs: number;
  /** `scrap / (output + scrap) x 100`; denominator 0 -> `0`. */
  scrap_pct: number;
  /** Rumus identik B13 (`bundles_done / (target_per_day x hari) x 100`) per grup. */
  efficiency_pct: number;
  /** Metrik order-level; `null` pada `group_by=work_center`/`line`. */
  otd_pct: number | null;
  /** Hanya `group_by=period`. */
  period?: string;
  /** Hanya `group_by=period` (drill-down; tidak dicampur ke `scrap_pcs`). */
  rework_pcs?: number;
  end_loss_pcs?: number;
  /** Jumlah bundle unik pada baris ini (`period`, `work_center`, atau `line`). */
  bundle_count?: number;
  /** Hanya `group_by=period`. */
  wo_count?: number;
  /** Hanya `group_by=work_center`. */
  wc_id?: number | null;
  wc_code?: string;
  wc_name?: string;
  /** Hanya `group_by=line`. */
  line_id?: number | null;
  line_code?: string;
  line_name?: string;
}

/** Ringkasan rentang (kuantitas + persentase; TANPA `currency`). */
export interface ProductionReportSummary {
  total_output_pcs: number;
  total_scrap_pcs: number;
  /** Terpisah dari `total_scrap_pcs` (konsep berbeda). */
  total_rework_pcs: number;
  /** Terpisah dari `total_scrap_pcs` (konsep berbeda). */
  total_end_loss_pcs: number;
  scrap_pct: number;
  avg_efficiency_pct: number;
  /** Order-level (pola B20). */
  otd_pct: number;
  total_bundles: number;
  total_work_orders: number;
}

/** Echo filter efektif + basis waktu per metrik (transparansi H4.6). */
export interface ProductionReportFilters {
  period: string | null;
  date_from: string | null;
  date_to: string | null;
  from: string | null;
  to: string | null;
  group_by: ProductionGroupBy;
  work_center_id: number | null;
  line_id: number | null;
  nocache: boolean;
  /** Basis waktu per metrik (output/efficiency/otd/scrap). */
  basis: Record<string, string>;
  resolved_from: string;
  resolved_to: string;
}

/** Respons `GET /reports/production/`. */
export interface ProductionReportResponse {
  rows: ProductionReportRow[];
  summary: ProductionReportSummary;
  group_by: ProductionGroupBy;
  filters: ProductionReportFilters;
  period: { from: string; to: string };
  generated_at: string;
  cached: boolean;
}
