/**
 * master-uom.ts — baris master UoM dari `/api/v1/master/uoms/` (H1.2).
 *
 * Field = PERSIS `django_app/master/uom_services.py::uom_row`:
 *   * `active` = nama publik dari `UoM.is_active` (konsisten H1.1);
 *   * `odoo_id` = kunci idempotensi sync (`null` = belum pernah terkirim ke Odoo);
 *   * `uom_type`/`factor`/`rounding` disimpan di MES karena **wajib** di Odoo
 *     (`uom.uom` menolak create tanpa `category_id`/`uom_type`/`factor`/`rounding`).
 *
 * Respons POST/PUT menambahkan info sinkronisasi (`sync_record_id`/`task_id`/`queued`)
 * → lihat `MasterUomSaved`.
 */

/** Tipe UoM — nilai HARUS sama dengan selection `uom.uom.uom_type` Odoo. */
export type UomType = 'bigger' | 'reference' | 'smaller';

export interface MasterUomRow {
  id: number;
  code: string;
  name: string;
  category: string;
  uom_type: UomType;
  factor: number;
  rounding: number;
  active: boolean;
  odoo_id: number | null;
}

/** Body POST/PUT ke backend (nama field backend, bukan nama UI). */
export interface MasterUomInput {
  code: string;
  name: string;
  category: string;
  uom_type: UomType;
  factor: number;
  rounding: number;
  active: boolean;
}

/**
 * Baris hasil simpan (POST/PUT): row + jejak sinkronisasi H1.2.
 * `queued=false` artinya broker/task tidak menerima pekerjaan (mis. Redis mati) —
 * `SyncRecord` tetap `PENDING` dan bisa dilihat di `/settings/sync`.
 */
export interface MasterUomSaved extends MasterUomRow {
  sync_record_id: number | null;
  task_id: string | null;
  queued: boolean;
}
