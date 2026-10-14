/**
 * sales-order.ts — kontrak Sales Order + OrderLine (H2.1).
 *
 * Endpoint: `/api/v1/garmen/orders/` (+ `/<id>/`, `/<id>/confirm|done|cancel/`)
 * di `apps_industry/garment/api/orders.py`, bentuk baris = PERSIS
 * `apps_industry/garment/services/order_services.py::order_row` / `order_detail_row`
 * / `line_row`.
 *
 * Catatan penting:
 *   * `price_unit`/`subtotal`/`amount_total` dikirim backend sebagai **string**
 *     (nilai `Decimal` → `str`) supaya tidak ada galat pembulatan float;
 *   * `deadline`/`created_at`/`updated_at` = ISO-8601 atau `null`;
 *   * `state` MES = `DRAFT → CONFIRMED → DONE` / `CANCELLED` (§14) — `DONE` murni
 *     MES (Odoo 17 tidak punya state `done` untuk `sale.order`);
 *   * push ke Odoo = **satu arah** & hanya saat `CONFIRMED` (create **draft** di
 *     Odoo, `client_order_ref` = nomor MES `SO-<TAHUN>-<SEQ>`).
 *
 * `snake_case` backend dipakai apa adanya (pola H1.1–H1.9/Sprint C).
 */

/** State MES yang sah (backend `order_services.ORDER_STATES`). */
export type SalesOrderState = 'DRAFT' | 'CONFIRMED' | 'DONE' | 'CANCELLED';

/** Baris order untuk daftar (tanpa `lines[]`). */
export interface SalesOrderRow {
  id: number;
  code: string;
  client_order_ref: string;
  customer_id: number | null;
  customer_name: string | null;
  order_type: string;
  state: string;
  priority: number;
  deadline: string | null;
  lines_count: number;
  amount_total: string;
  odoo_id: number | null;
  created_at: string | null;
  updated_at: string | null;
}

/** Satu baris order (produk + qty + harga + pajak). */
export interface SalesOrderLineRow {
  id: number;
  product_id: number | null;
  product_code: string | null;
  product_name: string | null;
  qty: number;
  tag: string;
  ticket_code: string | null;
  price_unit: string;
  subtotal: string;
  tax_ids: number[];
  odoo_id: number | null;
  created_at: string | null;
  updated_at: string | null;
}

/** Detail order = baris list + `lines[]` + info sync & aksi yang diizinkan. */
export interface SalesOrderDetail extends SalesOrderRow {
  lines: SalesOrderLineRow[];
  work_orders_count: number;
  odoo_sync_status: string | null;
  allowed_actions: string[];
}

/** Satu baris yang dikirim ke backend (`lines[]` nested). */
export interface SalesOrderLineInput {
  product_id: number;
  qty: number;
  price_unit: string;
  tag: string;
  tax_ids: number[];
}

/** Body POST/PUT ke backend (nama field backend, bukan nama UI). */
export interface SalesOrderInput {
  customer_id: number | null;
  order_type: string;
  priority: number;
  deadline: string | null;
  lines: SalesOrderLineInput[];
}

/**
 * Hasil simpan/transisi: detail order + jejak push.
 * `queued=false` artinya task push tidak masuk broker (Redis mati) — `SyncRecord`
 * tetap `PENDING` dan terlihat di `/settings/sync`.
 */
export interface SalesOrderSaved extends SalesOrderDetail {
  sync_record_id: number | null;
  task_id: string | null;
  queued: boolean;
}
