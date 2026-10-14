// Tipe **Stock Transfer** (H2.6) — cermin `stock_transfer_services.py`
// (`transfer_row`/`transfer_detail_row`).
//
// PRINSIP (docs/CHANGES-DETAIL-H1H5.md §4): **MES TIDAK menyimpan stok**. Baris di sini
// = LOG transfer antar dua lokasi internal (`DRAFT → COMMITTED → SYNCED/FAILED`);
// saldo tetap di Odoo dan tidak pernah dicache di MES.

/** State MES transfer (bukan seed Odoo). */
export const TRANSFER_STATES = ['DRAFT', 'COMMITTED', 'SYNCED', 'FAILED'] as const;

export type TransferState = (typeof TRANSFER_STATES)[number];

/** Satu baris audit log transfer (picking internal Odoo). */
export interface StockTransferRow {
  id: number;
  code: string;
  product_id: number;
  product_code: string | null;
  product_name: string | null;
  from_location_id: number;
  from_location_code: string | null;
  from_location_name: string | null;
  to_location_id: number;
  to_location_code: string | null;
  to_location_name: string | null;
  /** Decimal sebagai string (mis. `"5.00"`). */
  qty: string;
  /** Snapshot on-hand lokasi asal (nullable = tidak terbaca; informatif saja). */
  qty_before: string | null;
  reason: string;
  state: TransferState;
  /** id `stock.picking` Odoo (null sebelum sukses). */
  odoo_picking_id: number | null;
  /** Nama picking Odoo (mis. `WH/INT/00003`). */
  odoo_picking_name: string;
  last_error: string;
  created_by: string | null;
  created_at: string | null;
  updated_at: string | null;
}

/** Blok `sync` pada detail (ledger `STOCK_TRANSFER` terakhir). */
export interface StockTransferSync {
  record_id: number | null;
  status: string | null;
  erp_id: string | null;
  attempts: number;
}

/** Detail transfer (`transfer_detail_row` backend). */
export interface StockTransferDetail extends StockTransferRow {
  sync: StockTransferSync;
}

/** Halaman list (amplop §3: `has_more`, bukan `has_next`). */
export interface StockTransferPage {
  rows: StockTransferRow[];
  total_count: number;
  has_more: boolean;
  next_cursor: number | null;
}

/** Input form create (`POST /inventory/transfer/`). */
export interface StockTransferCreateInput {
  product_id: number;
  from_location_id: number;
  to_location_id: number;
  qty: string;
  reason: string;
}

/** Hasil create; `?commit=true` menambahkan blok `commit`. */
export interface StockTransferCreated extends StockTransferDetail {
  commit?: {
    ok: boolean;
    detail?: string;
    ledger_id?: number | null;
    task_id?: string | null;
    queued?: boolean;
  };
}

/** Hasil commit (`POST /inventory/transfers/<id>/commit/`). */
export interface StockTransferCommitResult extends StockTransferDetail {
  ledger_id: number | null;
  task_id: string | null;
  queued: boolean;
}
