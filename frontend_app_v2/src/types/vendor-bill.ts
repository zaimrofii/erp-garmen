/**
 * vendor-bill.ts — baris Vendor Bill MES dari `/api/v1/finance/vendor-bills/` (H3.2).
 *
 * Field = PERSIS `django_app/apps_industry/garment/services/vendor_bill_services.py`:
 *   * `state` = state BISNIS (`DRAFT`/`CONFIRMED`/`SENT`/`DONE`/`CANCELLED`);
 *     kegagalan push **bukan** state — terlihat di `odoo_sync_status` (`SyncRecord`);
 *   * `amount_total` = Σ(qty × price_unit) **sebelum pajak** (pajak dihitung Odoo);
 *   * `odoo_id` = id `account.move` **in_invoice** Odoo (`null` = belum terkirim);
 *   * `ref` = nomor bill dari **vendor** (best-effort: boleh kosong/duplikat);
 *   * `purchase_order_id`/`purchase_order_no` = **nullable** (bill tanpa PO, mis.
 *     biaya jasa) dan satu PO boleh >1 bill (termin/partial).
 *
 * Berbeda dari I6 (`MaterialReadiness.vendor_bill_*`, hasil tarikan Odoo) dan dari
 * B10 `purchaseOrders` (monitoring read-only) — keduanya tidak diubah H3.2.
 */

/** State bisnis bill (harus sama dengan `VendorBill.State` backend). */
export type VendorBillState = 'DRAFT' | 'CONFIRMED' | 'SENT' | 'DONE' | 'CANCELLED';

/** Baris bill (nested di detail; `tax_ids` = pk MES, `tax_odoo_ids` = id Odoo). */
export interface VendorBillLineRow {
  id: number;
  po_line_id: number | null;
  product_id: number;
  product_code: string | null;
  product_name: string | null;
  qty: string;
  price_unit: string;
  subtotal: string;
  tax_ids: number[];
  tax_odoo_ids: number[];
  line_total: string;
  created_at: string | null;
  updated_at: string | null;
}

export interface VendorBillRow {
  id: number;
  code: string;
  purchase_order_id: number | null;
  purchase_order_no: string | null;
  vendor_id: number;
  vendor_name: string | null;
  vendor_code: string | null;
  ref: string;
  invoice_date: string | null;
  due_date: string | null;
  state: VendorBillState;
  notes: string;
  lines_count: number;
  amount_total: string;
  odoo_id: number | null;
  created_at: string | null;
  updated_at: string | null;
}

/** Detail bill = baris list + `lines[]` + info sync Odoo + aksi yang boleh. */
export interface VendorBillDetail extends VendorBillRow {
  lines: VendorBillLineRow[];
  odoo_sync_status: string | null;
  odoo_sync_error: string | null;
  allowed_actions: string[];
}

/** Body satu baris saat create/update. */
export interface VendorBillLineInput {
  product_id: number;
  qty: number;
  price_unit: number;
  tax_ids: number[];
  po_line_id?: number | null;
}

/** Body POST/PUT: `lines` opsional (belum ada PO = wajib, backend 400 bila kosong). */
export interface VendorBillInput {
  vendor_id: number;
  purchase_order_id?: number | null;
  ref?: string;
  invoice_date: string;
  due_date?: string | null;
  notes?: string;
  lines?: VendorBillLineInput[];
}

/** Baris hasil simpan (POST/PUT/aksi): row + jejak sinkronisasi H3.2. */
export interface VendorBillSaved extends VendorBillDetail {
  sync_record_id: number | null;
  task_id: string | null;
  queued: boolean;
  duplicate_warning?: string | null;
}

/** Label state bill (bahasa Indonesia) untuk badge/tabel. */
export const VENDOR_BILL_STATE_LABELS: Record<VendorBillState, string> = {
  DRAFT: 'Draft',
  CONFIRMED: 'Terkonfirmasi',
  SENT: 'Terkirim ke Odoo',
  DONE: 'Selesai',
  CANCELLED: 'Dibatalkan',
};
