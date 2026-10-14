/**
 * master-work-center.ts — baris master Work Center dari `/api/v1/master/work-centers/` (H1.7).
 *
 * Field = PERSIS `master/api.py::work_center_row` (+ detail:
 * `active_bundles_count`, `production_lines`):
 *   * `active` = nama publik dari `WorkCenter.is_active` (konsisten H1.1–H1.6);
 *   * `wc_type` = jenis stasiun, **free-form** (mis. `SEWING`/`CUTTING`/`QC` —
 *     konvensi `LineAllocationRule.wc_type`, tanpa enum di kode);
 *   * `capability_tags` = daftar tag kapabilitas (≤ 20 tag, tiap tag ≤ 32 karakter);
 *   * `capacity_per_hour` = target output/jam (dikirim backend sebagai float);
 *   * `config` = field lama (atribut bebas; mis. `target_per_day` yang dibaca monitoring);
 *   * **TIDAK ada `odoo_id`**: H1.7 MES-only (`mrp.workcenter` Odoo mewajibkan
 *     `resource_id` yang tidak ada di MES) → tidak ada push/pull, jadi tidak ada
 *     field id ERP yang disimpan (bukan utang field mati).
 */

/** Satu lini produksi yang memuat work center ini (M2M `ProductionLine.work_centers`). */
export interface MasterWorkCenterLine {
  id: number;
  code: string;
  name: string;
}

export interface MasterWorkCenterRow {
  id: number;
  code: string;
  name: string;
  wc_type: string;
  capability_tags: string[];
  capacity_per_hour: number;
  description: string;
  active: boolean;
  config: Record<string, unknown>;
  created_at: string | null;
  updated_at: string | null;
}

/** Detail work center = row + jejak pemakaian (bundle aktif & lini produksi). */
export interface MasterWorkCenterDetail extends MasterWorkCenterRow {
  /** Bundle aktif di WC ini (state bukan DONE/CANCELLED) — dasar guard soft delete. */
  active_bundles_count: number;
  production_lines: MasterWorkCenterLine[];
}

/** Body POST/PUT ke backend (nama field backend, bukan nama UI). */
export interface MasterWorkCenterInput {
  code: string;
  name: string;
  wc_type: string;
  capability_tags: string[];
  capacity_per_hour: number;
  description: string;
  active: boolean;
}

/**
 * Baris hasil simpan (POST/PUT): detail + jejak sync H1.7 **MES-only**.
 *
 * `sync_status` selalu `'SKIPPED'` (ledger `master.work_center` ditulis dengan
 * status `SKIPPED` + alasan), `task_id`/`queued` selalu `null`/`false` karena
 * tidak ada task push yang di-enqueue. `mes_only: true` menandai hal itu.
 */
export interface MasterWorkCenterSaved extends MasterWorkCenterDetail {
  sync_record_id: number | null;
  sync_status: string | null;
  task_id: string | null;
  queued: boolean;
  mes_only: boolean;
}
