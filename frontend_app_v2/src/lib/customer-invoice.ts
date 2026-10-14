/**
 * customer-invoice.ts — logic PURE halaman Customer Invoice (H3.1).
 *
 * Dipisah dari halaman supaya bisa diuji TANPA DOM (jsdom tidak jalan di bun —
 * `.clinerules` §ENVIRONMENT): validasi form, konversi row/detail ↔ form, subtotal
 * baris, total invoice, label state, dan opsi filter semuanya fungsi murni di sini.
 *
 * Angka dibiarkan **string** selama di form (pola H2.1/H3.6); konversi ke `number`
 * hanya saat submit (`invoiceInputFromForm`).
 */
import { displayOrDash, parseFormNumber } from '@/lib/master-uom';
import {
  CUSTOMER_INVOICE_STATE_LABELS,
  type CustomerInvoiceDetail,
  type CustomerInvoiceInput,
  type CustomerInvoiceLineRow,
  type CustomerInvoiceRow,
  type CustomerInvoiceState,
} from '@/types/customer-invoice';

/** Satu baris invoice di layar form. */
export interface InvoiceLineFormValues {
  id: number | null;
  order_line_id: number | null;
  product_id: string;
  qty: string;
  price_unit: string;
  /** Pajak baris (id `master.Tax`), boleh kosong. */
  tax_ids: number[];
}

/** Nilai form invoice (header + baris). */
export interface InvoiceFormValues {
  order_id: string;
  customer_id: string;
  invoice_date: string;
  due_date: string;
  notes: string;
  lines: InvoiceLineFormValues[];
}

export interface InvoiceLineFormErrors {
  product_id?: string;
  qty?: string;
  price_unit?: string;
}

export interface InvoiceFormErrors {
  order_id?: string;
  invoice_date?: string;
  lines?: Record<number, InvoiceLineFormErrors>;
}

/** PURE — baris kosong baru. */
export function emptyInvoiceLine(): InvoiceLineFormValues {
  return { id: null, order_line_id: null, product_id: '', qty: '1', price_unit: '', tax_ids: [] };
}

/** Form kosong (satu baris siap isi — pola form BOM H1.5/H2.1). */
export const EMPTY_INVOICE_FORM: InvoiceFormValues = {
  order_id: '',
  customer_id: '',
  invoice_date: '',
  due_date: '',
  notes: '',
  lines: [emptyInvoiceLine()],
};

/** Opsi "kosong" untuk `<select>` (mengirim `null` ke backend). */
export const NO_ORDER_OPTION = { value: '', label: '— Pilih order —' };
export const NO_CUSTOMER_OPTION = { value: '', label: '— Ikuti customer order —' };
export const NO_TAX_OPTION = { value: '', label: '— Tanpa pajak —' };

/** Filter state di halaman daftar (`all` = tidak difilter). */
export const INVOICE_STATE_FILTERS: { id: string; label: string }[] = [
  { id: 'all', label: 'Semua' },
  { id: 'DRAFT', label: 'Draft' },
  { id: 'CONFIRMED', label: 'Terkonfirmasi' },
  { id: 'SENT', label: 'Terkirim' },
  { id: 'DONE', label: 'Selesai' },
  { id: 'CANCELLED', label: 'Dibatalkan' },
];

const FILTER_IDS: readonly string[] = INVOICE_STATE_FILTERS.map((filter) => filter.id);

/** PURE - menyempitkan `string` dari Tabs ke filter state TANPA cast `as`. */
export function isInvoiceStateFilter(value: string): value is 'all' | CustomerInvoiceState {
  return FILTER_IDS.includes(value);
}

/** PURE - filter UI → param `state` backend (`null` = tidak difilter). */
export function stateParamForFilter(
  filter: 'all' | CustomerInvoiceState,
): CustomerInvoiceState | null {
  return filter === 'all' ? null : filter;
}

/** PURE — tambah satu baris kosong. */
export function addInvoiceLine(values: InvoiceFormValues): InvoiceFormValues {
  return { ...values, lines: [...values.lines, emptyInvoiceLine()] };
}

/** PURE — hapus baris ke-`index` (indeks invalid = tidak berubah). */
export function removeInvoiceLine(values: InvoiceFormValues, index: number): InvoiceFormValues {
  if (index < 0 || index >= values.lines.length) return values;

  return { ...values, lines: values.lines.filter((_, position) => position !== index) };
}

/** PURE — ubah sebagian field baris ke-`index` (indeks invalid = tidak berubah). */
export function updateInvoiceLine(
  values: InvoiceFormValues,
  index: number,
  patch: Partial<InvoiceLineFormValues>,
): InvoiceFormValues {
  if (index < 0 || index >= values.lines.length) return values;

  return {
    ...values,
    lines: values.lines.map((line, position) =>
      position === index ? { ...line, ...patch } : line,
    ),
  };
}

/** PURE — satu baris backend (nested) → nilai form. */
export function invoiceLineFormFromRow(line: CustomerInvoiceLineRow): InvoiceLineFormValues {
  return {
    id: line.id,
    order_line_id: line.order_line_id,
    product_id: String(line.product_id),
    qty: line.qty,
    price_unit: line.price_unit,
    tax_ids: [...line.tax_ids],
  };
}

/** PURE — detail Sales Order (H2.1) → nilai form invoice (auto-fill baris + customer). */
export function invoiceFormFromOrderDetail(detail: {
  customer_id: number | null;
  lines: { id: number; product_id: number | null; qty: number; price_unit: string; tax_ids: number[] }[];
}): InvoiceFormValues {
  return {
    order_id: '',
    customer_id: detail.customer_id === null ? '' : String(detail.customer_id),
    invoice_date: '',
    due_date: '',
    notes: '',
    lines:
      detail.lines.length === 0
        ? [emptyInvoiceLine()]
        : detail.lines.map((line) => ({
            id: null,
            order_line_id: line.id,
            product_id: line.product_id === null ? '' : String(line.product_id),
            qty: String(line.qty),
            price_unit: line.price_unit,
            tax_ids: [...line.tax_ids],
          })),
  };
}

/** PURE — detail backend → nilai form (dipakai halaman edit). */
export function invoiceFormFromDetail(detail: CustomerInvoiceDetail): InvoiceFormValues {
  return {
    order_id: String(detail.order_id),
    customer_id: String(detail.customer_id),
    invoice_date: detail.invoice_date === null ? '' : detail.invoice_date.slice(0, 10),
    due_date: detail.due_date === null ? '' : detail.due_date.slice(0, 10),
    notes: detail.notes,
    lines:
      detail.lines.length === 0 ? [emptyInvoiceLine()] : detail.lines.map(invoiceLineFormFromRow),
  };
}

/** PURE — nilai form → body API (baris tanpa produk dibuang; `lines` selalu dikirim). */
export function invoiceInputFromForm(values: InvoiceFormValues): CustomerInvoiceInput {
  return {
    order_id: Number(values.order_id),
    invoice_date: values.invoice_date.trim(),
    due_date: values.due_date.trim() === '' ? null : values.due_date.trim(),
    notes: values.notes,
    lines: values.lines
      .filter((line) => line.product_id.trim().length > 0)
      .map((line) => ({
        product_id: Number(line.product_id),
        qty: parseFormNumber(line.qty) ?? 0,
        price_unit: parseFormNumber(line.price_unit) ?? 0,
        tax_ids: [...line.tax_ids],
        order_line_id: line.order_line_id,
      })),
  };
}

/** PURE — validasi form; objek KOSONG berarti boleh dikirim. */
export function validateInvoiceForm(values: InvoiceFormValues): InvoiceFormErrors {
  const errors: InvoiceFormErrors = {};

  if (values.order_id.trim() === '') {
    errors.order_id = 'Order wajib dipilih (invoice selalu terikat order).';
  }

  if (values.invoice_date.trim() === '') {
    errors.invoice_date = 'Tanggal invoice wajib diisi.';
  }

  const lineErrors: Record<number, InvoiceLineFormErrors> = {};
  values.lines.forEach((line, index) => {
    const row: InvoiceLineFormErrors = {};

    if (line.product_id.trim() === '') {
      row.product_id = 'Produk wajib dipilih.';
    }

    const qty = parseFormNumber(line.qty);
    if (qty === null || qty <= 0) {
      row.qty = 'Qty harus angka > 0.';
    }

    const price = parseFormNumber(line.price_unit);
    if (price === null) {
      row.price_unit = 'Harga wajib angka (0 diizinkan sebelum CONFIRMED).';
    } else if (price < 0) {
      row.price_unit = 'Harga tidak boleh negatif.';
    }

    if (Object.keys(row).length > 0) lineErrors[index] = row;
  });

  if (Object.keys(lineErrors).length > 0) errors.lines = lineErrors;

  return errors;
}

/** PURE — true kalau tidak ada error (siap submit). */
export function isInvoiceFormValid(errors: InvoiceFormErrors): boolean {
  return Object.keys(errors).length === 0;
}

/** PURE — subtotal satu baris (qty × harga, sebelum pajak) → '0.00' bila tidak valid. */
export function lineSubtotal(qty: string, priceUnit: string): string {
  const qtyNumber = parseFormNumber(qty) ?? 0;
  const priceNumber = parseFormNumber(priceUnit) ?? 0;

  return (qtyNumber * priceNumber).toFixed(2);
}

/** PURE — total invoice dari baris form (sebelum pajak). */
export function invoiceFormTotal(values: InvoiceFormValues): number {
  let total = 0;
  for (const line of values.lines) {
    total += (parseFormNumber(line.qty) ?? 0) * (parseFormNumber(line.price_unit) ?? 0);
  }

  return total;
}

/** PURE — label state invoice (Indonesia). */
export function invoiceStateLabel(state: CustomerInvoiceState): string {
  return CUSTOMER_INVOICE_STATE_LABELS[state] ?? state;
}

/** PURE — tone badge per state (`blue`=aktif, `muted`=netral, `coral`=batal). */
export function invoiceStateTone(state: CustomerInvoiceState): 'blue' | 'muted' | 'coral' {
  if (state === 'CANCELLED') return 'coral';
  if (state === 'DRAFT') return 'muted';

  return 'blue';
}

/** PURE — label tombol aksi per state target. */
export const INVOICE_ACTION_LABELS: Record<string, string> = {
  CONFIRMED: 'Konfirmasi & Kirim',
  SENT: 'Tandai Terkirim',
  DONE: 'Tandai Selesai',
  CANCELLED: 'Batalkan',
};

/** PURE — map state target → nama aksi API (`confirm`/`done`/`cancel`). */
export const INVOICE_STATE_TO_ACTION: Record<string, 'confirm' | 'done' | 'cancel'> = {
  CONFIRMED: 'confirm',
  SENT: 'done',
  DONE: 'done',
  CANCELLED: 'cancel',
};

/** Satu baris detail invoice (label + nilai siap tampil). */
export interface CustomerInvoiceDetailItem {
  label: string;
  value: string;
  mono?: boolean;
}

/** PURE - daftar field halaman detail invoice (urutan tetap). */
export function invoiceDetailItems(row: CustomerInvoiceRow): CustomerInvoiceDetailItem[] {
  return [
    { label: 'Kode', value: displayOrDash(row.code), mono: true },
    { label: 'Order', value: displayOrDash(row.order_no), mono: true },
    { label: 'Customer', value: displayOrDash(row.customer_name) },
    { label: 'Tanggal invoice', value: displayOrDash(row.invoice_date) },
    { label: 'Jatuh tempo', value: displayOrDash(row.due_date) },
    { label: 'State', value: invoiceStateLabel(row.state) },
    { label: 'Jumlah baris', value: String(row.lines_count) },
    { label: 'Total (sebelum pajak)', value: row.amount_total },
    { label: 'Odoo ID', value: row.odoo_id === null ? 'belum dikirim' : String(row.odoo_id) },
  ];
}

