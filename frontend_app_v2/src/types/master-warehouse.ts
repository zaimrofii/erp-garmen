/**
 * master-warehouse.ts — baris master Warehouse dari `/api/v1/master/warehouses/` (H1.3).
 *
 * Field = PERSIS `django_app/master/warehouse_services.py::warehouse_row`:
 *   * `active` = nama publik dari `Warehouse.is_active` (konsisten H1.1/H1.2);
 *   * `odoo_id` = kunci idempotensi sync (`null` = belum pernah terkirim ke Odoo;
 *     push H1.3 **update-only**, jadi `null` = task akan FAILED sampai H1.4 Location
 *     menyediakan `view_location_id`/`lot_stock_id`/`company_id`);
 *   * `reception_steps`/`delivery_steps` = alur in/out gudang di Odoo (`required`
 *     di `stock.warehouse`), disimpan di MES supaya push pakai nilai nyata.
 *
 * `usage` TIDAK ada di sini — di Odoo `usage` milik `stock.location` (H1.4).
 */

/** Alur penerimaan — nilai HARUS sama dengan selection `stock.warehouse.reception_steps`. */
export type ReceptionSteps = 'one_step' | 'two_steps' | 'three_steps';

/** Alur pengiriman — nilai HARUS sama dengan selection `stock.warehouse.delivery_steps`. */
export type DeliverySteps = 'ship_only' | 'pick_ship' | 'pick_pack_ship';

export interface MasterWarehouseRow {
  id: number;
  code: string;
  name: string;
  reception_steps: ReceptionSteps;
  delivery_steps: DeliverySteps;
  active: boolean;
  odoo_id: number | null;
}

/** Body POST/PUT ke backend (nama field backend, bukan nama UI). */
export interface MasterWarehouseInput {
  code: string;
  name: string;
  reception_steps: ReceptionSteps;
  delivery_steps: DeliverySteps;
  active: boolean;
}

/**
 * Baris hasil simpan (POST/PUT): row + jejak sinkronisasi H1.3.
 * `queued=false` artinya broker/task tidak menerima pekerjaan (mis. Redis mati) —
 * `SyncRecord` tetap `PENDING` dan bisa dilihat di `/settings/sync`.
 */
export interface MasterWarehouseSaved extends MasterWarehouseRow {
  sync_record_id: number | null;
  task_id: string | null;
  queued: boolean;
}
