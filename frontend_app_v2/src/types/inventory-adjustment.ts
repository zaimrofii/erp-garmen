// Tipe **Inventory Adjustment** (H2.5) — cermin `bundle_services`/`inventory_adjustment_services`
// (`adjustment_row`/`adjustment_detail_row`) di
// `django_app/apps_industry/garment/services/inventory_adjustment_services.py`.
//
// PRINSIP (docs/CHANGES-DETAIL-H1H5.md §4): **MES TIDAK menyimpan stok**. Baris di sini
// = LOG adjustment (`DRAFT → COMMITTED → SYNCED/FAILED`); nilai on-hand selalu dibaca
// on-demand dari Odoo (`/api/v1/inventory/stock-qty/`, read-only).

/** State MES adjustment (bukan seed Odoo). */
export const ADJUSTMENT_STATES = ['DRAFT', 'COMMITTED', 'SYNCED', 'FAILED'] as const;

export type AdjustmentState = (typeof ADJUSTMENT_STATES)[number];

/** Satu baris audit log adjustment (`adjustment_row` backend). */
export interface InventoryAdjustmentRow {
  id: number;
  code: string;
  product_id: number;
  product_code: string | null;
  product_name: string | null;
  location_id: number;
  location_code: string | null;
  location_name: string | null;
  location_usage: string | null;
  /** Decimal sebagai string (mis. `"5.00"`, `"-2.50"`). */
  qty_delta: string;
  qty_before: string | null;
  qty_after: string | null;
  reason: string;
  state: AdjustmentState;
  /** id `stock.move` Odoo hasil `action_apply_inventory()` (null sebelum sukses). */
  odoo_move_id: number | null;
  odoo_reference: string;
  last_error: string;
  created_by: string | null;
  created_at: string | null;
  updated_at: string | null;
}

/** Blok `sync` pada detail (ledger `INVENTORY_ADJUST` terakhir). */
export interface InventoryAdjustmentSync {
  record_id: number | null;
  status: string | null;
  erp_id: string | null;
  attempts: number;
}

/** Detail adjustment (`adjustment_detail_row` backend). */
export interface InventoryAdjustmentDetail extends InventoryAdjustmentRow {
  sync: InventoryAdjustmentSync;
}

/** Halaman list (amplop §3: `has_more`, bukan `has_next`). */
export interface InventoryAdjustmentPage {
  rows: InventoryAdjustmentRow[];
  total_count: number;
  has_more: boolean;
  next_cursor: number | null;
}

/** Input form create (`POST /inventory/adjust/`). */
export interface InventoryAdjustmentCreateInput {
  product_id: number;
  location_id: number;
  qty_delta: string;
  reason: string;
}

/** Hasil create; `?commit=true` menambahkan blok `commit`. */
export interface InventoryAdjustmentCreated extends InventoryAdjustmentDetail {
  commit?: {
    ok: boolean;
    detail?: string;
    ledger_id?: number | null;
    task_id?: string | null;
    queued?: boolean;
  };
}

/** Hasil commit (`POST /inventory/adjustments/<id>/commit/`). */
export interface InventoryAdjustmentCommitResult extends InventoryAdjustmentDetail {
  ledger_id: number | null;
  task_id: string | null;
  queued: boolean;
}

/** Hasil pembacaan on-hand Odoo (read-only, tanpa cache di MES). */
export interface InventoryStockQty {
  product_id: number;
  product_code: string;
  product_odoo_id: number | null;
  location_id: number;
  location_code: string;
  location_odoo_id: number | null;
  /** `null` = Odoo belum bisa dibaca (odoo_id belum ada / kredensial kosong). */
  qty: string | null;
  source: string;
  stock_owner: string;
}
