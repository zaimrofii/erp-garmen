/**
 * master-location.ts — baris master Location dari `/api/v1/master/locations/` (H1.4).
 *
 * Field = PERSIS `django_app/master/location_services.py::location_row`:
 *   * `active` = nama publik dari `Location.is_active` (konsisten H1.1–H1.3);
 *   * `odoo_id` = kunci idempotensi sync (`null` = belum pernah terkirim ke Odoo);
 *   * `parent_id`/`parent_name` = induk (Odoo `location_id`); `null` = lokasi akar;
 *   * `warehouse_id`/`warehouse_name` = gudang pemilik (`master.Warehouse`); `null`
 *     = lokasi global/milik Odoo (mis. `view`); di Odoo field ini **dihitung dari
 *     hierarki**, jadi MES hanya menyimpan relasinya dan tidak mengirimkannya saat push;
 *   * `children_count` = jumlah anak langsung (backend memakai satu `annotate(Count)`;
 *     daftar anak TIDAK ikut supaya tidak N+1);
 *   * `complete_name` = **DERIVED** (`Induk/Anak`) — tidak ada kolomnya di DB.
 */

/** Jenis lokasi — nilai HARUS sama dengan selection `stock.location.usage` Odoo (7). */
export type LocationUsage =
  | 'supplier'
  | 'view'
  | 'internal'
  | 'customer'
  | 'inventory'
  | 'production'
  | 'transit';

export interface MasterLocationRow {
  id: number;
  code: string;
  name: string;
  usage: LocationUsage;
  parent_id: number | null;
  parent_name: string | null;
  warehouse_id: number | null;
  warehouse_name: string | null;
  active: boolean;
  odoo_id: number | null;
  children_count: number;
  complete_name: string;
}

/** Body POST/PUT ke backend (nama field backend, bukan nama UI). */
export interface MasterLocationInput {
  code: string;
  name: string;
  usage: LocationUsage;
  /** `null` = jadikan lokasi akar (memindahkan/menanggalkan induk). */
  parent_id: number | null;
  /** `null` = tanpa gudang (lokasi global/view). */
  warehouse_id: number | null;
  active: boolean;
}

/**
 * Baris hasil simpan (POST/PUT): row + jejak sinkronisasi H1.4.
 * `queued=false` artinya broker/task tidak menerima pekerjaan (mis. Redis mati) —
 * `SyncRecord` tetap `PENDING` dan bisa dilihat di `/settings/sync`.
 */
export interface MasterLocationSaved extends MasterLocationRow {
  sync_record_id: number | null;
  task_id: string | null;
  queued: boolean;
}
