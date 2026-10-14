/**
 * customer-invoice.ts — baris Customer Invoice MES dari
 * `/api/v1/finance/customer-invoices/` (H3.1).
 *
 * Field = PERSIS `django_app/apps_industry/garment/services/customer_invoice_services.py`:
 *   * `state` = state BISNIS (`DRAFT`/`CONFIRMED`/`SENT`/`DONE`/`CANCELLED`);
 *     kegagalan push **bukan** state — terlihat di `odoo_sync_status` (`SyncRecord`);
 *   * `amount_total` = Σ(qty × price_unit) **sebelum pajak** (pajak dihitung Odoo);
 *   * `odoo_id` = id `account.move` Odoo (kunci idempotensi push; `null` = belum terkirim).
 *
 * Respons POST/PUT/aksi menambahkan `{sync_record_id, task_id, queued}` → `Saved`.
 * Berbeda dari F15 `/finance/invoices/` (antrean I5 read-only dari SyncRecord).
 */

/** State bisnis invoice (harus sama dengan `CustomerInvoice.State` backend). */
export type CustomerInvoiceState = 'DRAFT' | 'CONFIRMED' | 'SENT' | 'DONE' | 'CANCELLED';

/** Baris invoice (nested di detail; `tax_ids` = pk MES, `tax_odoo_ids` = id Odoo). */
export interface CustomerInvoiceLineRow {
  id: number;
  order_line_id: number | null;
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

export interface CustomerInvoiceRow {
  id: number;
  code: string;
  order_id: number;
  order_no: string | null;
  customer_id: number;
  customer_name: string | null;
  customer_code: string | null;
  invoice_date: string | null;
  due_date: string | null;
  state: CustomerInvoiceState;
  notes: string;
  lines_count: number;
  amount_total: string;
  odoo_id: number | null;
  created_at: string | null;
  updated_at: string | null;
}

/** Detail invoice = baris list + `lines[]` + info sync Odoo + aksi yang boleh. */
export interface CustomerInvoiceDetail extends CustomerInvoiceRow {
  lines: CustomerInvoiceLineRow[];
  odoo_sync_status: string | null;
  odoo_sync_error: string | null;
  allowed_actions: string[];
}

/** Body satu baris saat create/update. */
export interface CustomerInvoiceLineInput {
  product_id: number;
  qty: number;
  price_unit: number;
  tax_ids: number[];
  order_line_id?: number | null;
}

/** Body POST/PUT: `lines` opsional (kosong = auto-fill backend dari OrderLine). */
export interface CustomerInvoiceInput {
  order_id: number;
  customer_id?: number | null;
  invoice_date: string;
  due_date?: string | null;
  notes?: string;
  lines?: CustomerInvoiceLineInput[];
}

/** Baris hasil simpan (POST/PUT/aksi): row + jejak sinkronisasi H3.1. */
export interface CustomerInvoiceSaved extends CustomerInvoiceDetail {
  sync_record_id: number | null;
  task_id: string | null;
  queued: boolean;
  duplicate_warning?: string | null;
}

/** Label state invoice (bahasa Indonesia) untuk badge/tabel. */
export const CUSTOMER_INVOICE_STATE_LABELS: Record<CustomerInvoiceState, string> = {
  DRAFT: 'Draft',
  CONFIRMED: 'Terkonfirmasi',
  SENT: 'Terkirim ke Odoo',
  DONE: 'Selesai',
  CANCELLED: 'Dibatalkan',
};
