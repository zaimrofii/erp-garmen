/**
 * payment.ts — baris Payment MES dari `/api/v1/finance/payments/` (H3.3).
 *
 * Field = PERSIS `django_app/apps_industry/garment/services/payment_services.py`:
 *   * `payment_type` = arah bayar (`INBOUND` customer bayar kita / `OUTBOUND` kita
 *     bayar vendor) — satu model dua arah, padanan `account.payment` Odoo;
 *   * `state` = state BISNIS (`DRAFT`/`CONFIRMED`/`SENT`/`DONE`/`CANCELLED`);
 *     kegagalan push **bukan** state — terlihat di `odoo_sync_status` (`SyncRecord`);
 *   * `source_type`/`source_label` = dokumen sumber (customer invoice ATAU vendor bill);
 *   * `amount` = jumlah dibayar (string Decimal); `currency` = kode MES-only;
 *   * `odoo_id` = id `account.payment` Odoo (`null` = belum terkirim).
 *
 * Detail menambah `source_amount_total` + `source_remaining_amount` (sisa dokumen
 * setelah payment ini) — dipakai UI untuk menyarankan jumlah bayar.
 * Rekonsiliasi BUKAN di MES (Odoo/akuntan) — tidak ada field reconcile di sini.
 */

/** Arah pembayaran (harus sama dengan `Payment.PaymentType` backend). */
export type PaymentType = 'INBOUND' | 'OUTBOUND';

/** State bisnis payment (harus sama dengan `Payment.State` backend). */
export type PaymentState = 'DRAFT' | 'CONFIRMED' | 'SENT' | 'DONE' | 'CANCELLED';

/** Cara bayar MES-only (tidak dikirim ke Odoo). */
export type PaymentMethod = 'manual' | 'bank' | 'cash';

/** Jenis dokumen sumber yang ditampilkan UI. */
export type PaymentSourceType = 'CUSTOMER_INVOICE' | 'VENDOR_BILL' | 'UNKNOWN';

export interface PaymentRow {
  id: number;
  code: string;
  payment_type: PaymentType;
  partner_id: number;
  partner_name: string | null;
  partner_code: string | null;
  customer_invoice_id: number | null;
  customer_invoice_code: string | null;
  vendor_bill_id: number | null;
  vendor_bill_code: string | null;
  source_type: PaymentSourceType;
  source_label: string;
  amount: string;
  currency: string;
  payment_date: string | null;
  payment_method: PaymentMethod;
  reference: string;
  memo: string;
  state: PaymentState;
  odoo_id: number | null;
  created_at: string | null;
  updated_at: string | null;
}

/** Detail payment = baris list + info sync + sisa dokumen + aksi yang boleh. */
export interface PaymentDetail extends PaymentRow {
  odoo_sync_status: string | null;
  odoo_sync_error: string | null;
  allowed_actions: string[];
  source_amount_total: string | null;
  source_remaining_amount: string | null;
}

/** Body POST/PUT: tepat satu dari `customer_invoice_id`/`vendor_bill_id`. */
export interface PaymentInput {
  payment_type: PaymentType;
  customer_invoice_id?: number | null;
  vendor_bill_id?: number | null;
  /** Opsional — backend menurunkan dari dokumen sumber bila kosong. */
  partner_id?: number | null;
  amount: number;
  currency?: string;
  payment_date: string;
  payment_method?: PaymentMethod;
  reference?: string;
  memo?: string;
  notes?: string;
}

/** Baris hasil simpan (POST/PUT/aksi): row + jejak sinkronisasi H3.3. */
export interface PaymentSaved extends PaymentDetail {
  sync_record_id: number | null;
  task_id: string | null;
  queued: boolean;
}

/** Label arah pembayaran untuk badge/tabel. */
export const PAYMENT_TYPE_LABELS: Record<PaymentType, string> = {
  INBOUND: 'Masuk (customer)',
  OUTBOUND: 'Keluar (vendor)',
};

/** Label state payment (bahasa Indonesia) untuk badge/tabel. */
export const PAYMENT_STATE_LABELS: Record<PaymentState, string> = {
  DRAFT: 'Draft',
  CONFIRMED: 'Terkonfirmasi',
  SENT: 'Terkirim ke Odoo',
  DONE: 'Selesai',
  CANCELLED: 'Dibatalkan',
};

/** Label cara bayar (MES-only) untuk form/detail. */
export const PAYMENT_METHOD_LABELS: Record<PaymentMethod, string> = {
  manual: 'Manual',
  bank: 'Transfer Bank',
  cash: 'Kas',
};
