/**
 * payment.ts — logic PURE halaman Payment (H3.3).
 *
 * Dipisah dari halaman supaya bisa diuji TANPA DOM (jsdom tidak jalan di bun —
 * `.clinerules` §ENVIRONMENT): validasi form, konversi row/detail ↔ form, sisa
 * dokumen, label state/tipe, dan opsi filter semuanya fungsi murni di sini.
 *
 * Angka dibiarkan **string** selama di form (pola H3.1/H3.2); konversi ke `number`
 * hanya saat submit (`paymentInputFromForm`). `amount` **disarankan** dari sisa
 * dokumen sumber (`remainingForSource`) tetapi tetap bisa diubah operator —
 * backend tetap menegakkan guard anti-overpay.
 */
import { displayOrDash, parseFormNumber } from '@/lib/master-uom';
import {
  PAYMENT_METHOD_LABELS,
  PAYMENT_STATE_LABELS,
  PAYMENT_TYPE_LABELS,
  type PaymentDetail,
  type PaymentInput,
  type PaymentMethod,
  type PaymentRow,
  type PaymentState,
  type PaymentType,
} from '@/types/payment';

/** Nilai form payment (header saja — tidak ada baris). */
export interface PaymentFormValues {
  payment_type: PaymentType;
  customer_invoice_id: string;
  vendor_bill_id: string;
  amount: string;
  currency: string;
  payment_date: string;
  payment_method: PaymentMethod;
  reference: string;
  memo: string;
}

export interface PaymentFormErrors {
  payment_type?: string;
  source?: string;
  amount?: string;
  payment_date?: string;
  reference?: string;
}

/** Batas `reference` backend (`payment_services.MAX_REF_LENGTH`). */
export const PAYMENT_REF_MAX_LENGTH = 64;

/** Form kosong (INBOUND, belum ada sumber — pola form H3.1/H3.2). */
export const EMPTY_PAYMENT_FORM: PaymentFormValues = {
  payment_type: 'INBOUND',
  customer_invoice_id: '',
  vendor_bill_id: '',
  amount: '',
  currency: 'IDR',
  payment_date: '',
  payment_method: 'manual',
  reference: '',
  memo: '',
};

/** Opsi "kosong" untuk `<select>` sumber dokumen. */
export const NO_INVOICE_OPTION = { value: '', label: '— Pilih customer invoice —' };
export const NO_BILL_OPTION = { value: '', label: '— Pilih vendor bill —' };

/** Opsi arah bayar untuk radio/segmented control. */
export const PAYMENT_TYPE_OPTIONS: { id: PaymentType; label: string; description: string }[] = [
  {
    id: 'INBOUND',
    label: 'Pembayaran Masuk',
    description: 'Customer membayar kita — sumber: customer invoice (H3.1)',
  },
  {
    id: 'OUTBOUND',
    label: 'Pembayaran Keluar',
    description: 'Kita membayar vendor — sumber: vendor bill (H3.2)',
  },
];

/** Opsi cara bayar (MES-only). */
export const PAYMENT_METHOD_OPTIONS: { value: PaymentMethod; label: string }[] = [
  { value: 'manual', label: PAYMENT_METHOD_LABELS.manual },
  { value: 'bank', label: PAYMENT_METHOD_LABELS.bank },
  { value: 'cash', label: PAYMENT_METHOD_LABELS.cash },
];

/** Filter state di halaman daftar (`all` = tidak difilter). */
export const PAYMENT_STATE_FILTERS: { id: string; label: string }[] = [
  { id: 'all', label: 'Semua' },
  { id: 'DRAFT', label: 'Draft' },
  { id: 'CONFIRMED', label: 'Terkonfirmasi' },
  { id: 'SENT', label: 'Terkirim' },
  { id: 'DONE', label: 'Selesai' },
  { id: 'CANCELLED', label: 'Dibatalkan' },
];

/** Filter arah bayar di halaman daftar (`all` = tidak difilter). */
export const PAYMENT_TYPE_FILTERS: { id: string; label: string }[] = [
  { id: 'all', label: 'Semua arah' },
  { id: 'INBOUND', label: 'Masuk' },
  { id: 'OUTBOUND', label: 'Keluar' },
];

const STATE_FILTER_IDS: readonly string[] = PAYMENT_STATE_FILTERS.map((filter) => filter.id);
const TYPE_FILTER_IDS: readonly string[] = PAYMENT_TYPE_FILTERS.map((filter) => filter.id);

/** PURE - menyempitkan `string` dari Tabs ke filter state TANPA cast `as`. */
export function isPaymentStateFilter(value: string): value is 'all' | PaymentState {
  return STATE_FILTER_IDS.includes(value);
}

/** PURE - menyempitkan `string` dari Tabs ke filter arah bayar TANPA cast `as`. */
export function isPaymentTypeFilter(value: string): value is 'all' | PaymentType {
  return TYPE_FILTER_IDS.includes(value);
}

/** PURE - filter UI → param `state` backend (`null` = tidak difilter). */
export function stateParamForFilter(filter: 'all' | PaymentState): PaymentState | null {
  return filter === 'all' ? null : filter;
}

/** PURE - filter UI → param `payment_type` backend (`null` = tidak difilter). */
export function typeParamForFilter(filter: 'all' | PaymentType): PaymentType | null {
  return filter === 'all' ? null : filter;
}

/** PURE — label arah bayar. */
export function paymentTypeLabel(type: PaymentType): string {
  return PAYMENT_TYPE_LABELS[type] ?? type;
}

/** PURE — label state payment (Indonesia). */
export function paymentStateLabel(state: PaymentState): string {
  return PAYMENT_STATE_LABELS[state] ?? state;
}

/** PURE — label cara bayar. */
export function paymentMethodLabel(method: PaymentMethod): string {
  return PAYMENT_METHOD_LABELS[method] ?? method;
}

/** PURE — tone badge per state (`blue`=aktif, `muted`=netral, `coral`=batal). */
export function paymentStateTone(state: PaymentState): 'blue' | 'muted' | 'coral' {
  if (state === 'CANCELLED') return 'coral';
  if (state === 'DRAFT') return 'muted';

  return 'blue';
}

/** PURE — tone badge per arah bayar (masuk = hijau? repo pakai blue/coral/muted). */
export function paymentTypeTone(type: PaymentType): 'blue' | 'muted' {
  return type === 'INBOUND' ? 'blue' : 'muted';
}

// ---------------------------------------------------------------------------
// Sisa dokumen (client-side, cermin guard backend)
// ---------------------------------------------------------------------------
/** PURE — Σ amount payment AKTIF (bukan CANCELLED) yang sudah ada untuk sumber. */
export function activePaymentsTotal(rows: PaymentRow[]): number {
  let total = 0;
  for (const row of rows) {
    if (row.state === 'CANCELLED') continue;

    total += parseFormNumber(row.amount) ?? 0;
  }

  return total;
}

/**
 * PURE — sisa dokumen = `amount_total` − Σ payment aktif (bisa ≤ 0).
 *
 * Dipakai untuk **menyarankan** jumlah bayar; backend tetap memvalidasi
 * (guard anti-overpay) sehingga UI tidak perlu memblokir ketat.
 */
export function remainingForSource(amountTotal: string | null, rows: PaymentRow[]): number {
  const total = parseFormNumber(amountTotal ?? '') ?? 0;

  return Math.max(0, Number((total - activePaymentsTotal(rows)).toFixed(2)));
}

/** PURE — saran jumlah bayar sebagai string form ('' bila tidak ada sisa). */
export function suggestedAmount(amountTotal: string | null, rows: PaymentRow[]): string {
  const remaining = remainingForSource(amountTotal, rows);

  return remaining > 0 ? remaining.toFixed(2) : '';
}

// ---------------------------------------------------------------------------
// Form: validasi + konversi
// ---------------------------------------------------------------------------
/** PURE — validasi form; objek KOSONG berarti boleh dikirim. */
export function validatePaymentForm(values: PaymentFormValues): PaymentFormErrors {
  const errors: PaymentFormErrors = {};

  if (values.payment_type === 'INBOUND') {
    if (values.customer_invoice_id.trim() === '') {
      errors.source = 'Pilih customer invoice (pembayaran masuk selalu terikat invoice).';
    }
  } else if (values.vendor_bill_id.trim() === '') {
    errors.source = 'Pilih vendor bill (pembayaran keluar selalu terikat bill).';
  }

  const amount = parseFormNumber(values.amount);
  if (values.amount.trim() === '') {
    errors.amount = 'Jumlah bayar wajib diisi.';
  } else if (amount === null) {
    errors.amount = 'Jumlah bayar harus angka.';
  } else if (amount <= 0) {
    errors.amount = 'Jumlah bayar harus > 0.';
  }

  if (values.payment_date.trim() === '') {
    errors.payment_date = 'Tanggal bayar wajib diisi.';
  }

  if (values.reference.trim().length > PAYMENT_REF_MAX_LENGTH) {
    errors.reference = `Referensi maksimal ${String(PAYMENT_REF_MAX_LENGTH)} karakter.`;
  }

  return errors;
}

/** PURE — true kalau tidak ada error (siap submit). */
export function isPaymentFormValid(errors: PaymentFormErrors): boolean {
  return Object.keys(errors).length === 0;
}

/** PURE — nilai form → body API (tepat satu sumber; teks di-trim). */
export function paymentInputFromForm(values: PaymentFormValues): PaymentInput {
  const invoiceId = values.customer_invoice_id.trim();
  const billId = values.vendor_bill_id.trim();
  const inbound = values.payment_type === 'INBOUND';

  return {
    payment_type: values.payment_type,
    customer_invoice_id: inbound && invoiceId !== '' ? Number(invoiceId) : null,
    vendor_bill_id: !inbound && billId !== '' ? Number(billId) : null,
    amount: parseFormNumber(values.amount) ?? 0,
    currency: values.currency.trim() === '' ? 'IDR' : values.currency.trim().toUpperCase(),
    payment_date: values.payment_date.trim(),
    payment_method: values.payment_method,
    reference: values.reference,
    memo: values.memo,
  };
}

/** PURE — detail backend → nilai form (dipakai halaman edit). */
export function paymentFormFromDetail(detail: PaymentDetail): PaymentFormValues {
  return {
    payment_type: detail.payment_type,
    customer_invoice_id:
      detail.customer_invoice_id === null ? '' : String(detail.customer_invoice_id),
    vendor_bill_id: detail.vendor_bill_id === null ? '' : String(detail.vendor_bill_id),
    amount: detail.amount,
    currency: detail.currency,
    payment_date: detail.payment_date === null ? '' : detail.payment_date.slice(0, 10),
    payment_method: detail.payment_method,
    reference: detail.reference,
    memo: detail.memo,
  };
}

/** PURE — ganti arah bayar: sumber lawan dikosongkan (tepat satu sumber). */
export function switchPaymentType(
  values: PaymentFormValues,
  next: PaymentType,
): PaymentFormValues {
  if (next === 'INBOUND') {
    return { ...values, payment_type: next, vendor_bill_id: '' };
  }

  return { ...values, payment_type: next, customer_invoice_id: '' };
}

/** PURE — label opsi dropdown invoice (`code — customer`). */
export function invoiceOptionLabel(row: { code: string; customer_name: string | null }): string {
  return `${row.code} — ${row.customer_name ?? '-'}`;
}

/** PURE — label opsi dropdown bill (`code — vendor`). */
export function billOptionLabel(row: { code: string; vendor_name: string | null }): string {
  return `${row.code} — ${row.vendor_name ?? '-'}`;
}

/** PURE — label tombol aksi per state target. */
export const PAYMENT_ACTION_LABELS: Record<string, string> = {
  CONFIRMED: 'Konfirmasi & Kirim',
  SENT: 'Tandai Terkirim',
  DONE: 'Tandai Selesai',
  CANCELLED: 'Batalkan',
};

/** PURE — map state target → nama aksi API (`confirm`/`done`/`cancel`). */
export const PAYMENT_STATE_TO_ACTION: Record<string, 'confirm' | 'done' | 'cancel'> = {
  CONFIRMED: 'confirm',
  SENT: 'done',
  DONE: 'done',
  CANCELLED: 'cancel',
};

/** Satu baris detail payment (label + nilai siap tampil). */
export interface PaymentDetailItem {
  label: string;
  value: string;
  mono?: boolean;
}

/** PURE - daftar field halaman detail payment (urutan tetap). */
export function paymentDetailItems(row: PaymentRow): PaymentDetailItem[] {
  return [
    { label: 'Kode', value: displayOrDash(row.code), mono: true },
    { label: 'Arah', value: paymentTypeLabel(row.payment_type) },
    { label: 'Dokumen sumber', value: displayOrDash(row.source_label), mono: true },
    { label: 'Partner', value: displayOrDash(row.partner_name) },
    { label: 'Jumlah', value: `${row.amount} ${row.currency}` },
    { label: 'Tanggal bayar', value: displayOrDash(row.payment_date) },
    { label: 'Cara bayar', value: paymentMethodLabel(row.payment_method) },
    { label: 'Referensi bank', value: displayOrDash(row.reference), mono: true },
    { label: 'State', value: paymentStateLabel(row.state) },
    { label: 'Odoo ID', value: row.odoo_id === null ? 'belum dikirim' : String(row.odoo_id) },
  ];
}


