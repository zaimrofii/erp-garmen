/**
 * vendor-bill.ts — logic PURE halaman Vendor Bill (H3.2).
 *
 * Dipisah dari halaman supaya bisa diuji TANPA DOM (jsdom tidak jalan di bun —
 * `.clinerules` §ENVIRONMENT): validasi form, konversi row/detail ↔ form, subtotal
 * baris, total bill, label state, dan opsi filter semuanya fungsi murni di sini.
 *
 * Angka dibiarkan **string** selama di form (pola H3.1/H2.1/H3.6); konversi ke
 * `number` hanya saat submit (`billInputFromForm`).
 *
 * Beda dari customer invoice (H3.1): `purchase_order_id` **opsional** (bill tanpa PO,
 * mis. biaya jasa) dan `ref` (nomor bill dari vendor) hanya *best-effort* — boleh
 * kosong, hanya dibatasi 64 karakter (probe STEP 0: Odoo tidak mewajibkannya).
 */
import { displayOrDash, parseFormNumber } from '@/lib/master-uom';
import {
  VENDOR_BILL_STATE_LABELS,
  type VendorBillDetail,
  type VendorBillInput,
  type VendorBillLineRow,
  type VendorBillRow,
  type VendorBillState,
} from '@/types/vendor-bill';

/** Satu baris bill di layar form. */
export interface BillLineFormValues {
  id: number | null;
  po_line_id: number | null;
  product_id: string;
  qty: string;
  price_unit: string;
  /** Pajak baris (id `master.Tax`), boleh kosong. */
  tax_ids: number[];
}

/** Nilai form bill (header + baris). */
export interface BillFormValues {
  purchase_order_id: string;
  vendor_id: string;
  ref: string;
  invoice_date: string;
  due_date: string;
  notes: string;
  lines: BillLineFormValues[];
}

export interface BillLineFormErrors {
  product_id?: string;
  qty?: string;
  price_unit?: string;
}

export interface BillFormErrors {
  vendor_id?: string;
  invoice_date?: string;
  ref?: string;
  lines?: Record<number, BillLineFormErrors>;
}

/** Batas `ref` backend (`vendor_bill_services.MAX_REF_LENGTH`). */
export const BILL_REF_MAX_LENGTH = 64;

/** PURE — baris kosong baru. */
export function emptyBillLine(): BillLineFormValues {
  return { id: null, po_line_id: null, product_id: '', qty: '1', price_unit: '', tax_ids: [] };
}

/** Form kosong (satu baris siap isi — pola form BOM H1.5/H3.1). */
export const EMPTY_BILL_FORM: BillFormValues = {
  purchase_order_id: '',
  vendor_id: '',
  ref: '',
  invoice_date: '',
  due_date: '',
  notes: '',
  lines: [emptyBillLine()],
};

/** Opsi "kosong" untuk `<select>` (mengirim `null`/tanpa field ke backend). */
export const NO_PO_OPTION = { value: '', label: '— Tanpa PO (biaya jasa) —' };
export const NO_VENDOR_OPTION = { value: '', label: '— Pilih vendor —' };
export const NO_TAX_OPTION = { value: '', label: '— Tanpa pajak —' };

/** Filter state di halaman daftar (`all` = tidak difilter). */
export const BILL_STATE_FILTERS: { id: string; label: string }[] = [
  { id: 'all', label: 'Semua' },
  { id: 'DRAFT', label: 'Draft' },
  { id: 'CONFIRMED', label: 'Terkonfirmasi' },
  { id: 'SENT', label: 'Terkirim' },
  { id: 'DONE', label: 'Selesai' },
  { id: 'CANCELLED', label: 'Dibatalkan' },
];

const FILTER_IDS: readonly string[] = BILL_STATE_FILTERS.map((filter) => filter.id);

/** PURE - menyempitkan `string` dari Tabs ke filter state TANPA cast `as`. */
export function isBillStateFilter(value: string): value is 'all' | VendorBillState {
  return FILTER_IDS.includes(value);
}

/** PURE - filter UI → param `state` backend (`null` = tidak difilter). */
export function stateParamForFilter(filter: 'all' | VendorBillState): VendorBillState | null {
  return filter === 'all' ? null : filter;
}

/** PURE — tambah satu baris kosong. */
export function addBillLine(values: BillFormValues): BillFormValues {
  return { ...values, lines: [...values.lines, emptyBillLine()] };
}

/** PURE — hapus baris ke-`index` (indeks invalid = tidak berubah). */
export function removeBillLine(values: BillFormValues, index: number): BillFormValues {
  if (index < 0 || index >= values.lines.length) return values;

  return { ...values, lines: values.lines.filter((_, position) => position !== index) };
}

/** PURE — ubah sebagian field baris ke-`index` (indeks invalid = tidak berubah). */
export function updateBillLine(
  values: BillFormValues,
  index: number,
  patch: Partial<BillLineFormValues>,
): BillFormValues {
  if (index < 0 || index >= values.lines.length) return values;

  return {
    ...values,
    lines: values.lines.map((line, position) =>
      position === index ? { ...line, ...patch } : line,
    ),
  };
}

/** PURE — satu baris backend (nested) → nilai form. */
export function billLineFormFromRow(line: VendorBillLineRow): BillLineFormValues {
  return {
    id: line.id,
    po_line_id: line.po_line_id,
    product_id: String(line.product_id),
    qty: line.qty,
    price_unit: line.price_unit,
    tax_ids: [...line.tax_ids],
  };
}

/** PURE — detail Purchase Order (H2.2) → nilai form bill (auto-fill baris + vendor). */
export function billFormFromPurchaseOrderDetail(detail: {
  vendor_id: number | null;
  lines: { id: number; product_id: number | null; qty: string; price_unit: string; tax_ids: number[] }[];
}): BillFormValues {
  return {
    purchase_order_id: '',
    vendor_id: detail.vendor_id === null ? '' : String(detail.vendor_id),
    ref: '',
    invoice_date: '',
    due_date: '',
    notes: '',
    lines:
      detail.lines.length === 0
        ? [emptyBillLine()]
        : detail.lines.map((line) => ({
            id: null,
            po_line_id: line.id,
            product_id: line.product_id === null ? '' : String(line.product_id),
            qty: line.qty,
            price_unit: line.price_unit,
            tax_ids: [...line.tax_ids],
          })),
  };
}

/** PURE — detail backend → nilai form (dipakai halaman edit). */
export function billFormFromDetail(detail: VendorBillDetail): BillFormValues {
  return {
    purchase_order_id:
      detail.purchase_order_id === null ? '' : String(detail.purchase_order_id),
    vendor_id: String(detail.vendor_id),
    ref: detail.ref,
    invoice_date: detail.invoice_date === null ? '' : detail.invoice_date.slice(0, 10),
    due_date: detail.due_date === null ? '' : detail.due_date.slice(0, 10),
    notes: detail.notes,
    lines:
      detail.lines.length === 0 ? [emptyBillLine()] : detail.lines.map(billLineFormFromRow),
  };
}

/**
 * PURE — nilai form → body API.
 *
 * `lines` selalu dikirim (baris tanpa produk dibuang) supaya backend memakai baris
 * apa adanya, bukan auto-fill dari PO (pola H3.1).
 */
export function billInputFromForm(values: BillFormValues): VendorBillInput {
  const poId = values.purchase_order_id.trim();

  return {
    vendor_id: Number(values.vendor_id),
    purchase_order_id: poId === '' ? null : Number(poId),
    ref: values.ref,
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
        po_line_id: line.po_line_id,
      })),
  };
}

/** PURE — validasi form; objek KOSONG berarti boleh dikirim. */
export function validateBillForm(values: BillFormValues): BillFormErrors {
  const errors: BillFormErrors = {};

  if (values.vendor_id.trim() === '') {
    errors.vendor_id = 'Vendor wajib dipilih.';
  }

  if (values.invoice_date.trim() === '') {
    errors.invoice_date = 'Tanggal bill wajib diisi.';
  }

  if (values.ref.trim().length > BILL_REF_MAX_LENGTH) {
    errors.ref = `Nomor bill vendor maksimal ${String(BILL_REF_MAX_LENGTH)} karakter.`;
  }

  const lineErrors: Record<number, BillLineFormErrors> = {};
  values.lines.forEach((line, index) => {
    const row: BillLineFormErrors = {};

    if (line.product_id.trim() === '') {
      row.product_id = 'Produk wajib dipilih.';
    }

    const qty = parseFormNumber(line.qty);
    if (qty === null || qty <= 0) {
      row.qty = 'Qty harus angka > 0.';
    }

    const price = parseFormNumber(line.price_unit);
    if (price === null) {
      row.price_unit = 'Harga wajib angka (0 diizinkan, mis. tagihan menyusul).';
    } else if (price < 0) {
      row.price_unit = 'Harga tidak boleh negatif.';
    }

    if (Object.keys(row).length > 0) lineErrors[index] = row;
  });

  if (Object.keys(lineErrors).length > 0) errors.lines = lineErrors;

  return errors;
}

/** PURE — true kalau tidak ada error (siap submit). */
export function isBillFormValid(errors: BillFormErrors): boolean {
  return Object.keys(errors).length === 0;
}

/** PURE — subtotal satu baris (qty × harga, sebelum pajak) → '0.00' bila tidak valid. */
export function lineSubtotal(qty: string, priceUnit: string): string {
  const qtyNumber = parseFormNumber(qty) ?? 0;
  const priceNumber = parseFormNumber(priceUnit) ?? 0;

  return (qtyNumber * priceNumber).toFixed(2);
}

/** PURE — total bill dari baris form (sebelum pajak). */
export function billFormTotal(values: BillFormValues): number {
  let total = 0;
  for (const line of values.lines) {
    total += (parseFormNumber(line.qty) ?? 0) * (parseFormNumber(line.price_unit) ?? 0);
  }

  return total;
}

/** PURE — label state bill (Indonesia). */
export function billStateLabel(state: VendorBillState): string {
  return VENDOR_BILL_STATE_LABELS[state] ?? state;
}

/** PURE — tone badge per state (`blue`=aktif, `muted`=netral, `coral`=batal). */
export function billStateTone(state: VendorBillState): 'blue' | 'muted' | 'coral' {
  if (state === 'CANCELLED') return 'coral';
  if (state === 'DRAFT') return 'muted';

  return 'blue';
}

/** PURE — label tombol aksi per state target. */
export const BILL_ACTION_LABELS: Record<string, string> = {
  CONFIRMED: 'Konfirmasi & Kirim',
  SENT: 'Tandai Terkirim',
  DONE: 'Tandai Selesai',
  CANCELLED: 'Batalkan',
};

/** PURE — map state target → nama aksi API (`confirm`/`done`/`cancel`). */
export const BILL_STATE_TO_ACTION: Record<string, 'confirm' | 'done' | 'cancel'> = {
  CONFIRMED: 'confirm',
  SENT: 'done',
  DONE: 'done',
  CANCELLED: 'cancel',
};

/** Satu baris detail bill (label + nilai siap tampil). */
export interface VendorBillDetailItem {
  label: string;
  value: string;
  mono?: boolean;
}

/** PURE - daftar field halaman detail bill (urutan tetap). */
export function billDetailItems(row: VendorBillRow): VendorBillDetailItem[] {
  return [
    { label: 'Kode', value: displayOrDash(row.code), mono: true },
    { label: 'Purchase Order', value: displayOrDash(row.purchase_order_no), mono: true },
    { label: 'Vendor', value: displayOrDash(row.vendor_name) },
    { label: 'No. bill vendor (ref)', value: displayOrDash(row.ref), mono: true },
    { label: 'Tanggal bill', value: displayOrDash(row.invoice_date) },
    { label: 'Jatuh tempo', value: displayOrDash(row.due_date) },
    { label: 'State', value: billStateLabel(row.state) },
    { label: 'Jumlah baris', value: String(row.lines_count) },
    { label: 'Total (sebelum pajak)', value: row.amount_total },
    { label: 'Odoo ID', value: row.odoo_id === null ? 'belum dikirim' : String(row.odoo_id) },
  ];
}


