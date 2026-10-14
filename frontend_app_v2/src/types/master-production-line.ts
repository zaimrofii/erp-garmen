/**
 * master-production-line.ts — baris master Production Line dari
 * `/api/v1/master/production-lines/` (H1.8).
 *
 * Field = PERSIS `master/production_line_services.py::production_line_row`
 * (+ detail: `work_centers[]`, `active_bundles_count`):
 *   * `active` = nama publik dari `ProductionLine.is_active` (konsisten H1.1–H1.7);
 *   * `capability_tags` = daftar tag kapabilitas lini (≤ 20 tag, tiap tag ≤ 32 char,
 *     huruf dipertahankan — sama seperti WorkCenter H1.7);
 *   * M2M `work_centers` diekspor ganda: `work_center_ids` + `work_center_names`
 *     (bentuk daftar, TANPA akhiran `_id` pada atribut model) dan `work_centers[]`
 *     nested `{id, code, name}` **hanya di detail**;
 *   * `work_centers_count`/`allocation_rules_count` = hasil `annotate` backend
 *     (list tanpa N+1); `allocation_rules_count` hanya **info** — rule CASCADE dan
 *     soft delete tidak pernah menghapus baris;
 *   * **TIDAK ada `odoo_id`**: H1.8 MES-only (Odoo 17 tidak punya wadah lini —
 *     `mrp.routing` sudah dihapus, `mrp.routing.workcenter` = Operation per-BoM).
 */

/** Satu work center anggota lini (dari M2M `ProductionLine.work_centers`). */
export interface MasterProductionLineWorkCenter {
  id: number;
  code: string;
  name: string;
}

export interface MasterProductionLineRow {
  id: number;
  code: string;
  name: string;
  description: string;
  capability_tags: string[];
  work_centers_count: number;
  work_center_ids: number[];
  work_center_names: string[];
  allocation_rules_count: number;
  active: boolean;
  created_at: string | null;
  updated_at: string | null;
}

/** Detail lini = row + anggota WC (nested) + jumlah bundle aktif (guard soft delete). */
export interface MasterProductionLineDetail extends MasterProductionLineRow {
  work_centers: MasterProductionLineWorkCenter[];
  active_bundles_count: number;
}

/** Body POST/PUT ke backend (nama field backend, bukan nama UI). */
export interface MasterProductionLineInput {
  code: string;
  name: string;
  description: string;
  capability_tags: string[];
  /** Replace penuh anggota lini (`work_centers.set()` di backend, atomic). */
  work_center_ids: number[];
  active: boolean;
}

/**
 * Baris hasil simpan (POST/PUT): detail + jejak sync H1.8 **MES-only**.
 *
 * `sync_status` selalu `'SKIPPED'` (ledger `master.production_line` ditulis dengan
 * status `SKIPPED` + alasan), `task_id`/`queued` selalu `null`/`false` karena tidak
 * ada task push yang di-enqueue. `mes_only: true` menandai hal itu.
 */
export interface MasterProductionLineSaved extends MasterProductionLineDetail {
  sync_record_id: number | null;
  sync_status: string | null;
  task_id: string | null;
  queued: boolean;
  mes_only: boolean;
}
