/**
 * purchase-order.ts — kontrak **Purchase Order MES** (H2.2).
 *
 * Endpoint: `/api/v1/garmen/purchase-orders/` (`+ /<id>/`, `/<id>/confirm|done|cancel/`,
 * `/<id>/sync-odoo-state/`) di `apps_industry/garment/api/purchase_orders.py`; bentuk
 * baris = PERSIS `apps_industry/garment/services/purchase_order_services.py`
 * (`purchase_order_row` / `purchase_order_detail_row` / `purchase_order_line_row`).
 *
 * Beda dari B10 (`src/api/real/purchaseOrders.ts`, monitoring read-only dari Odoo):
 *   * ini **data MES** (tabel `PurchaseOrder`), bukan tarikan Odoo;
 *   * `qty`/`price_unit`/`subtotal`/`amount_total` = **string** (Decimal backend);
 *   * `state` MES = `DRAFT → CONFIRMED → DONE` / `CANCELLED` (§14) — `DONE` murni MES
 *     (Odoo `done` = *Locked* yang dipicu receipt);
 *   * push satu arah saat `CONFIRMED` (create **draft** di Odoo, `partner_ref` =
 *     nomor MES `PO-<TAHUN>-<SEQ>`).
 *
 * `snake_case` backend dipakai apa adanya (pola H1/H2.1).
 */

/** State PO MES yang sah (backend `purchase_order_services.PO_STATES`). */
export type PurchaseOrderState = 'DRAFT' | 'CONFIRMED' | 'DONE' | 'CANCELLED';

/** Baris PO untuk daftar (tanpa `lines[]`). */
export interface PurchaseOrderMesRow {
  id: number;
  code: string;
  partner_ref: string;
  vendor_id: number | null;
  vendor_name: string | null;
  vendor_code: string | null;
  state: string;
  expected_date: string | null;
  notes: string;
  lines_count: number;
  amount_total: string;
  odoo_id: number | null;
  created_at: string | null;
  updated_at: string | null;
}

/** Satu baris PO (produk + qty + harga + pajak + tanggal rencana). */
export interface PurchaseOrderMesLineRow {
  id: number;
  product_id: number | null;
  product_code: string | null;
  product_name: string | null;
  qty: string;
  price_unit: string;
  subtotal: string;
  tax_ids: number[];
  date_planned: string | null;
  odoo_id: number | null;
  created_at: string | null;
  updated_at: string | null;
}

/** Detail PO = baris list + `lines[]` + info sync & aksi yang diizinkan. */
export interface PurchaseOrderMesDetail extends PurchaseOrderMesRow {
  lines: PurchaseOrderMesLineRow[];
  odoo_sync_status: string | null;
  allowed_actions: string[];
}

/** Satu baris yang dikirim ke backend (`lines[]` nested). */
export interface PurchaseOrderMesLineInput {
  product_id: number;
  qty: string;
  price_unit: string;
  tax_ids: number[];
  date_planned: string | null;
}

/** Body POST/PUT ke backend (nama field backend, bukan nama UI). */
export interface PurchaseOrderMesInput {
  vendor_id: number | null;
  expected_date: string | null;
  notes: string;
  lines: PurchaseOrderMesLineInput[];
}

/**
 * Hasil simpan/transisi: detail PO + jejak push.
 * `queued=false` artinya task push tidak masuk broker (Redis mati) — `SyncRecord`
 * tetap `PENDING` dan terlihat di `/settings/sync`.
 */
export interface PurchaseOrderMesSaved extends PurchaseOrderMesDetail {
  sync_record_id: number | null;
  task_id: string | null;
  queued: boolean;
}

/** Respons **read-only** `POST /purchase-orders/<id>/sync-odoo-state/`. */
export interface PurchaseOrderOdooState {
  odoo_id: number;
  odoo_state: string | null;
  odoo_name: string | null;
}
