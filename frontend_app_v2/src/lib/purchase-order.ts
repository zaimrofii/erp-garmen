/**
 * purchase-order.ts — helper PURE halaman **Purchase Order MES** (H2.2).
 *
 * Bebas DOM/network supaya bisa diuji langsung (`tests/unit/pages/purchase-orders-crud.test.ts`)
 * dan dipakai `src/pages/purchase/PurchaseOrder{Form,Detail}Page.tsx`:
 *   * bentuk nilai form (`PoFormValues`) ↔ body backend (`PurchaseOrderMesInput`);
 *   * validasi (vendor wajib, tiap baris: produk wajib, qty > 0, harga ≥ 0);
 *   * operasi baris (tambah/hapus/ubah) + subtotal/total (Decimal → number utk UI);
 *   * label state + aksi yang boleh (mirror `purchase_order_services.ALLOWED_TRANSITIONS`).
 */
import type {
  PurchaseOrderMesDetail,
  PurchaseOrderMesInput,
  PurchaseOrderMesLineInput,
  PurchaseOrderMesLineRow,
  PurchaseOrderMesRow,
  PurchaseOrderState,
} from '@/types/purchase-order';

/** Satu baris di layar form (semua angka sebagai string, khas `<input>`). */
export interface PoLineFormValues {
  id: number | null;
  product_id: string;
  qty: string;
  price_unit: string;
  date_planned: string;
  /** Pajak baris (id `master.Tax`) yang dipilih, boleh kosong. */
  tax_ids: number[];
}

/** Nilai form PO (header + baris). */
export interface PoFormValues {
  vendor_id: string;
  expected_date: string;
  notes: string;
  lines: PoLineFormValues[];
}

/** Pesan error per field (kosong = tidak ada error). */
export interface PoLineFormErrors {
  product_id?: string;
  qty?: string;
  price_unit?: string;
  date_planned?: string;
}

export interface PoFormErrors {
  vendor_id?: string;
  expected_date?: string;
  lines?: Record<number, PoLineFormErrors>;
}

/** Form kosong (satu baris siap isi — pola form H1.5/H2.1). */
export const EMPTY_PO_FORM: PoFormValues = {
  vendor_id: '',
  expected_date: '',
  notes: '',
  lines: [{ id: null, product_id: '', qty: '1', price_unit: '', date_planned: '', tax_ids: [] }],
};

/** Label bahasa Indonesia untuk state PO MES (§14). */
export const PO_STATE_LABELS: Record<string, string> = {
  DRAFT: 'Draft',
  CONFIRMED: 'Terkonfirmasi',
  DONE: 'Selesai',
  CANCELLED: 'Dibatalkan',
};

/**
 * Aksi yang boleh dari sebuah state (mirror `ALLOWED_TRANSITIONS` backend).
 *
 * `DRAFT → CONFIRMED|CANCELLED`, `CONFIRMED → DONE|CANCELLED`,
 * `DONE`/`CANCELLED` = terminal.
 */
export function allowedPoActions(state: string): string[] {
  if (state === 'DRAFT') return ['CONFIRMED', 'CANCELLED'];
  if (state === 'CONFIRMED') return ['DONE', 'CANCELLED'];

  return [];
}

/** PURE — label state siap tampil (`DRAFT` → `Draft`; tak dikenal = apa adanya). */
export function poStateLabel(state: string): string {
  return PO_STATE_LABELS[state] ?? state;
}

/** PURE — `true` kalau PO masih boleh diubah/dihapus (DRAFT-only, backend). */
export function isPoEditable(state: string): boolean {
  return state === 'DRAFT';
}

/** PURE — string angka/desimal → number; `null` kalau kosong/tidak valid. */
export function toNullableNumber(value: string): number | null {
  const trimmed = value.trim();
  if (trimmed.length === 0) return null;

  const parsed = Number(trimmed);
  return Number.isFinite(parsed) ? parsed : null;
}

/** PURE — id dari `<select>` (`''` → `null`). */
export function toNullableId(value: string): number | null {
  const parsed = toNullableNumber(value);
  if (parsed === null || !Number.isInteger(parsed) || parsed <= 0) return null;

  return parsed;
}

/** PURE — subtotal satu baris (`qty × price_unit`; `0` kalau salah satu kosong). */
export function poLineSubtotal(qty: string, priceUnit: string): number {
  const quantity = toNullableNumber(qty) ?? 0;
  const price = toNullableNumber(priceUnit) ?? 0;

  return quantity * price;
}

/** PURE — total PO dari baris form. */
export function poFormTotal(values: PoFormValues): number {
  return values.lines.reduce(
    (total, line) => total + poLineSubtotal(line.qty, line.price_unit),
    0,
  );
}

/** PURE — total PO dari baris backend (`subtotal` sudah dihitung backend). */
export function poLinesTotal(lines: readonly { subtotal: string }[]): number {
  return lines.reduce((total, line) => total + (toNullableNumber(line.subtotal) ?? 0), 0);
}

// ---------------------------------------------------------------------------
// Validasi (PURE — dipakai form sebelum submit)
// ---------------------------------------------------------------------------
/** PURE — true kalau tanggal kosong atau ISO `YYYY-MM-DD` yang sah. */
function isIsoDateOrEmpty(value: string): boolean {
  const trimmed = value.trim();
  if (trimmed.length === 0) return true;

  return /^\d{4}-\d{2}-\d{2}$/.test(trimmed) && !Number.isNaN(Date.parse(trimmed));
}

/** PURE — validasi header + seluruh baris; pesan dalam bahasa Indonesia. */
export function validatePoForm(values: PoFormValues): PoFormErrors {
  const errors: PoFormErrors = {};

  if (toNullableId(values.vendor_id) === null) {
    errors.vendor_id = 'Vendor wajib dipilih.';
  }

  if (!isIsoDateOrEmpty(values.expected_date)) {
    errors.expected_date = 'Tanggal diharapkan harus format ISO (mis. 2026-11-30).';
  }

  const lineErrors: Record<number, PoLineFormErrors> = {};
  values.lines.forEach((line, index) => {
    const current: PoLineFormErrors = {};

    if (toNullableId(line.product_id) === null) {
      current.product_id = 'Produk wajib dipilih.';
    }

    const qty = toNullableNumber(line.qty);
    if (qty === null || qty <= 0) {
      current.qty = 'Qty harus angka lebih besar dari 0.';
    }

    const price = toNullableNumber(line.price_unit);
    if (price === null || price < 0) {
      current.price_unit = 'Harga satuan wajib diisi dan tidak boleh negatif.';
    }

    if (!isIsoDateOrEmpty(line.date_planned)) {
      current.date_planned = 'Tanggal rencana harus format ISO (mis. 2026-11-25).';
    }

    if (Object.keys(current).length > 0) {
      lineErrors[index] = current;
    }
  });

  if (values.lines.length === 0) {
    lineErrors[0] = { product_id: 'PO minimal punya satu baris produk.' };
  }

  if (Object.keys(lineErrors).length > 0) {
    errors.lines = lineErrors;
  }

  return errors;
}

/** PURE — true kalau tidak ada error (siap submit). */
export function isPoFormValid(errors: PoFormErrors): boolean {
  return Object.keys(errors).length === 0;
}

// ---------------------------------------------------------------------------
// Operasi baris (PURE — tombol Tambah/Hapus di form)
// ---------------------------------------------------------------------------
/** PURE — baris kosong baru. */
export function emptyPoLine(): PoLineFormValues {
  return { id: null, product_id: '', qty: '1', price_unit: '', date_planned: '', tax_ids: [] };
}

/** PURE — tambah satu baris kosong. */
export function addPoLine(values: PoFormValues): PoFormValues {
  return { ...values, lines: [...values.lines, emptyPoLine()] };
}

/** PURE — hapus baris ke-`index` (indeks invalid = tidak berubah). */
export function removePoLine(values: PoFormValues, index: number): PoFormValues {
  if (index < 0 || index >= values.lines.length) return values;

  return { ...values, lines: values.lines.filter((_, position) => position !== index) };
}

/** PURE — ubah sebagian field baris ke-`index` (indeks invalid = tidak berubah). */
export function updatePoLine(
  values: PoFormValues,
  index: number,
  patch: Partial<PoLineFormValues>,
): PoFormValues {
  if (index < 0 || index >= values.lines.length) return values;

  return {
    ...values,
    lines: values.lines.map((line, position) =>
      position === index ? { ...line, ...patch } : line,
    ),
  };
}

/** PURE — satu baris backend → nilai form. */
export function poLineFormFromRow(line: PurchaseOrderMesLineRow): PoLineFormValues {
  return {
    id: line.id,
    product_id: line.product_id === null ? '' : String(line.product_id),
    qty: line.qty,
    price_unit: line.price_unit,
    date_planned: line.date_planned === null ? '' : line.date_planned.slice(0, 10),
    tax_ids: [...line.tax_ids],
  };
}

/** PURE — detail backend → nilai form (dipakai halaman edit, bukan state). */
export function poFormFromDetail(detail: PurchaseOrderMesDetail): PoFormValues {
  return {
    vendor_id: detail.vendor_id === null ? '' : String(detail.vendor_id),
    expected_date: detail.expected_date === null ? '' : detail.expected_date.slice(0, 10),
    notes: detail.notes,
    lines: detail.lines.length === 0 ? [emptyPoLine()] : detail.lines.map(poLineFormFromRow),
  };
}

/** PURE — nilai form → body API (baris tanpa produk dibuang, angka dinormalisasi). */
export function poInputFromForm(values: PoFormValues): PurchaseOrderMesInput {
  const lines: PurchaseOrderMesLineInput[] = [];

  for (const line of values.lines) {
    const productId = toNullableId(line.product_id);
    if (productId === null) continue;

    const planned = line.date_planned.trim();
    lines.push({
      product_id: productId,
      qty: (toNullableNumber(line.qty) ?? 0).toFixed(2),
      price_unit: (toNullableNumber(line.price_unit) ?? 0).toFixed(2),
      tax_ids: [...line.tax_ids],
      date_planned: planned.length === 0 ? null : planned,
    });
  }

  const expected = values.expected_date.trim();
  const notes = values.notes.trim();

  return {
    vendor_id: toNullableId(values.vendor_id),
    expected_date: expected.length === 0 ? null : expected,
    notes,
    lines,
  };
}

// ---------------------------------------------------------------------------
// Label & item detail (PURE)
// ---------------------------------------------------------------------------
/** PURE — label opsi (`KODE - nama`; fallback kalau salah satu kosong). */
export function poOptionLabel(row: { code: string; name: string }): string {
  const code = row.code.trim();
  const name = row.name.trim();

  if (code.length === 0) return name;
  if (name.length === 0) return code;

  return `${code} - ${name}`;
}

/** PURE — teks aman untuk nilai nullable (`null`/'' → '-'). */
export function displayOrDash(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return '-';
  const text = String(value).trim();

  return text.length === 0 ? '-' : text;
}

/** PURE — tanggal ISO → `YYYY-MM-DD` (`null`/kosong → '-'). */
export function displayDate(value: string | null): string {
  if (value === null || value.trim().length === 0) return '-';

  return value.slice(0, 10);
}

/** Satu baris detail PO (label + nilai siap tampil). */
export interface PoDetailItem {
  label: string;
  value: string;
  mono?: boolean;
}

/** PURE — daftar field halaman detail PO (urutan tetap). */
export function poDetailItems(row: PurchaseOrderMesRow): PoDetailItem[] {
  return [
    { label: 'Kode', value: displayOrDash(row.code), mono: true },
    { label: 'Ref Vendor', value: displayOrDash(row.partner_ref) },
    { label: 'Vendor', value: displayOrDash(row.vendor_name) },
    { label: 'State', value: poStateLabel(row.state), mono: true },
    { label: 'Tanggal Diharapkan', value: displayDate(row.expected_date) },
    { label: 'Jumlah Baris', value: String(row.lines_count) },
    { label: 'Total', value: displayOrDash(row.amount_total), mono: true },
    { label: 'Catatan', value: displayOrDash(row.notes) },
    { label: 'Odoo ID', value: row.odoo_id === null ? 'belum dikirim' : String(row.odoo_id) },
  ];
}

/** PURE — daftar state untuk filter daftar (`all` + 4 state MES). */
export const PO_STATE_FILTERS: { id: string; label: string }[] = [
  { id: 'all', label: 'Semua' },
  { id: 'DRAFT', label: 'Draft' },
  { id: 'CONFIRMED', label: 'Terkonfirmasi' },
  { id: 'DONE', label: 'Selesai' },
  { id: 'CANCELLED', label: 'Dibatalkan' },
];

/** PURE — state filter UI → param `state` backend (`null` = tidak difilter). */
export function poStateParamForFilter(state: string): string | null {
  return state === 'all' ? null : state;
}

/** Semua state PO MES (untuk validasi filter tabs). */
export const PO_STATES: readonly PurchaseOrderState[] = [
  'DRAFT',
  'CONFIRMED',
  'DONE',
  'CANCELLED',
];


