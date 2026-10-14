/**
 * master-bom.ts — baris master BOM dari `/api/v1/master/boms/` (H1.5).
 *
 * Field = PERSIS `django_app/master/bom_services.py::bom_row` /
 * `bom_detail_row` / `line_row`:
 *   * `active` = nama publik dari `BOM.is_active` (konsisten H1.1–H1.4);
 *   * `odoo_id` = kunci idempotensi sync (`null` = belum pernah terkirim ke Odoo);
 *   * `product_id`/`product_code`/`product_name` = produk hasil (boleh `null`:
 *     BOM hasil *tarikan* Odoo bisa belum punya produk);
 *   * `output_qty` + `uom_id`/`uom_code` = jumlah output & satuannya (Odoo:
 *     `product_qty` + `product_uom_id`);
 *   * `lines_count` = jumlah baris komponen **aktif** (list dihitung satu
 *     `annotate(Count)`; `lines[]` hanya ada di detail);
 *   * baris komponen: `qty` (= kolom `product_qty` di DB), `sequence`, `uom_id`.
 *
 * `notes` murni catatan internal MES (tidak dikirim ke Odoo).
 */

/** Header BOM untuk daftar (tanpa `lines[]`). */
export interface MasterBomRow {
  id: number;
  code: string;
  name: string;
  product_id: number | null;
  product_code: string | null;
  product_name: string | null;
  output_qty: number;
  uom_id: number | null;
  uom_code: string | null;
  notes: string;
  active: boolean;
  odoo_id: number | null;
  lines_count: number;
  created_at: string | null;
  updated_at: string | null;
}

/** Satu baris komponen BOM. */
export interface MasterBomLineRow {
  id: number;
  product_id: number | null;
  product_code: string | null;
  product_name: string | null;
  qty: number;
  uom_id: number | null;
  uom_code: string | null;
  sequence: number;
  notes: string;
  active: boolean;
  odoo_id: number | null;
}

/** Detail BOM = header + daftar baris komponen aktif. */
export interface MasterBomDetail extends MasterBomRow {
  lines: MasterBomLineRow[];
}

/** Satu baris komponen yang dikirim ke backend (`id`/`odoo_id` untuk mencocokkan). */
export interface MasterBomLineInput {
  id?: number | null;
  odoo_id?: number | null;
  product_id: number | null;
  qty: number;
  uom_id: number | null;
  sequence: number;
  notes: string;
}

/** Body POST/PUT ke backend (nama field backend, bukan nama UI). */
export interface MasterBomInput {
  code: string;
  name: string;
  product_id: number | null;
  output_qty: number;
  uom_id: number | null;
  notes: string;
  active: boolean;
  /** Baris komponen — **seluruhnya** menggantikan baris aktif yang lama. */
  lines: MasterBomLineInput[];
}

/**
 * Baris hasil simpan (POST/PUT): detail BOM (termasuk `lines[]`) + jejak sync.
 * `queued=false` artinya broker/task tidak menerima pekerjaan (mis. Redis mati) —
 * `SyncRecord` tetap `PENDING` dan bisa dilihat di `/settings/sync`.
 */
export interface MasterBomSaved extends MasterBomDetail {
  sync_record_id: number | null;
  task_id: string | null;
  queued: boolean;
}
