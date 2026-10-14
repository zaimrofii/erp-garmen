/**
 * sales-order.ts — helper PURE halaman Sales Order (H2.1).
 *
 * Semua fungsi di sini bebas DOM/network supaya bisa diuji langsung (`tests/unit/pages/
 * sales-orders.test.ts`) dan dipakai halaman `src/pages/sales/*`:
 *   * bentuk nilai form (`OrderFormValues`) ↔ body backend (`SalesOrderInput`);
 *   * validasi (customer wajib, tiap baris: produk wajib, qty > 0, harga ≥ 0);
 *   * operasi baris (tambah/hapus/ubah) + subtotal/total;
 *   * label state + aksi yang boleh (mirror `order_services.ALLOWED_TRANSITIONS`).
 */
import type {
  SalesOrderDetail,
  SalesOrderInput,
  SalesOrderLineInput,
  SalesOrderLineRow,
  SalesOrderRow,
  SalesOrderState,
} from '@/types/sales-order';

/** Satu baris di layar form (semua angka sebagai string, khas `<input>`). */
export interface OrderLineFormValues {
  id: number | null;
  product_id: string;
  qty: string;
  price_unit: string;
  tag: string;
  /** Pajak baris (id `master.Tax`) yang dipilih, boleh kosong. */
  tax_ids: number[];
}

/** Nilai form order (header + baris). */
export interface OrderFormValues {
  customer_id: string;
  order_type: string;
  priority: string;
  deadline: string;
  lines: OrderLineFormValues[];
}

/** Pesan error per field (kosong = tidak ada error). */
export interface OrderLineFormErrors {
  product_id?: string;
  qty?: string;
  price_unit?: string;
}

export interface OrderFormErrors {
  customer_id?: string;
  priority?: string;
  deadline?: string;
  lines?: Record<number, OrderLineFormErrors>;
}

/** Form kosong (satu baris siap isi — pola form BOM H1.5). */
export const EMPTY_ORDER_FORM: OrderFormValues = {
  customer_id: '',
  order_type: 'EXPORT',
  priority: '0',
  deadline: '',
  lines: [{ id: null, product_id: '', qty: '1', price_unit: '', tag: '', tax_ids: [] }],
};

/** Tipe order yang dikenali backend (`order_services.ORDER_TYPES`). */
export const ORDER_TYPE_OPTIONS = ['EXPORT', 'CUSTOM', 'BRAND'] as const;

/** Label bahasa Indonesia untuk state MES (§14). */
export const ORDER_STATE_LABELS: Record<string, string> = {
  DRAFT: 'Draft',
  CONFIRMED: 'Terkonfirmasi',
  DONE: 'Selesai',
  CANCELLED: 'Dibatalkan',
};

/**
 * Aksi yang boleh dari sebuah state (mirror `ALLOWED_TRANSITIONS` backend).
 *
 * `DRAFT → CONFIRMED|CANCELLED`, `CONFIRMED → DONE|CANCELLED`, `DONE`/`CANCELLED`
 * = terminal.
 */
export function allowedOrderActions(state: string): string[] {
  if (state === 'DRAFT') return ['CONFIRMED', 'CANCELLED'];
  if (state === 'CONFIRMED') return ['DONE', 'CANCELLED'];

  return [];
}

/** PURE — label state siap tampil (`DRAFT` → `Draft`; tak dikenal = apa adanya). */
export function orderStateLabel(state: string): string {
  return ORDER_STATE_LABELS[state] ?? state;
}

/** PURE — `true` kalau order masih boleh diubah/dihapus (DRAFT-only, backend). */
export function isOrderEditable(state: string): boolean {
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

/** PURE — subtotal satu baris (`qty × price_unit`; `0` kalau harga kosong). */
export function lineSubtotal(qty: string, priceUnit: string): number {
  const quantity = toNullableNumber(qty) ?? 0;
  const price = toNullableNumber(priceUnit) ?? 0;

  return quantity * price;
}

/** PURE — total order dari baris form. */
export function orderFormTotal(values: OrderFormValues): number {
  return values.lines.reduce(
    (total, line) => total + lineSubtotal(line.qty, line.price_unit),
    0,
  );
}

/** PURE — total order dari baris backend (`subtotal` sudah dihitung backend). */
export function orderLinesTotal(lines: readonly { subtotal: string }[]): number {
  return lines.reduce((total, line) => total + (toNullableNumber(line.subtotal) ?? 0), 0);
}

// ---------------------------------------------------------------------------
// Validasi (PURE — dipakai form sebelum submit)
// ---------------------------------------------------------------------------
/** PURE — validasi header + seluruh baris; pesan dalam bahasa Indonesia. */
export function validateOrderForm(values: OrderFormValues): OrderFormErrors {
  const errors: OrderFormErrors = {};

  if (toNullableId(values.customer_id) === null) {
    errors.customer_id = 'Customer wajib dipilih.';
  }

  const priority = toNullableNumber(values.priority);
  if (priority === null || !Number.isInteger(priority)) {
    errors.priority = 'Prioritas harus bilangan bulat (boleh 0).';
  }

  if (values.deadline.trim().length > 0 && Number.isNaN(Date.parse(values.deadline))) {
    errors.deadline = 'Deadline harus format tanggal ISO (mis. 2026-11-30).';
  }

  const lineErrors: Record<number, OrderLineFormErrors> = {};
  values.lines.forEach((line, index) => {
    const current: OrderLineFormErrors = {};

    if (toNullableId(line.product_id) === null) {
      current.product_id = 'Produk wajib dipilih.';
    }

    const qty = toNullableNumber(line.qty);
    if (qty === null || !Number.isInteger(qty) || qty <= 0) {
      current.qty = 'Qty harus bilangan bulat lebih besar dari 0.';
    }

    const price = toNullableNumber(line.price_unit);
    if (price === null || price < 0) {
      current.price_unit = 'Harga satuan wajib diisi dan tidak boleh negatif.';
    }

    if (Object.keys(current).length > 0) {
      lineErrors[index] = current;
    }
  });

  if (values.lines.length === 0) {
    lineErrors[0] = { product_id: 'Order minimal punya satu baris produk.' };
  }

  if (Object.keys(lineErrors).length > 0) {
    errors.lines = lineErrors;
  }

  return errors;
}

/** PURE — true kalau tidak ada error (siap submit). */
export function isOrderFormValid(errors: OrderFormErrors): boolean {
  return Object.keys(errors).length === 0;
}

// ---------------------------------------------------------------------------
// Operasi baris (PURE — tombol Tambah/Hapus di form)
// ---------------------------------------------------------------------------
/** PURE — baris kosong baru. */
export function emptyOrderLine(): OrderLineFormValues {
  return { id: null, product_id: '', qty: '1', price_unit: '', tag: '', tax_ids: [] };
}

/** PURE — tambah satu baris kosong. */
export function addOrderLine(values: OrderFormValues): OrderFormValues {
  return { ...values, lines: [...values.lines, emptyOrderLine()] };
}

/** PURE — hapus baris ke-`index` (indeks invalid = tidak berubah). */
export function removeOrderLine(values: OrderFormValues, index: number): OrderFormValues {
  if (index < 0 || index >= values.lines.length) return values;

  return { ...values, lines: values.lines.filter((_, position) => position !== index) };
}

/** PURE — ubah sebagian field baris ke-`index` (indeks invalid = tidak berubah). */
export function updateOrderLine(
  values: OrderFormValues,
  index: number,
  patch: Partial<OrderLineFormValues>,
): OrderFormValues {
  if (index < 0 || index >= values.lines.length) return values;

  return {
    ...values,
    lines: values.lines.map((line, position) =>
      position === index ? { ...line, ...patch } : line,
    ),
  };
}

/** PURE — satu baris backend → nilai form. */
export function orderLineFormFromRow(line: SalesOrderLineRow): OrderLineFormValues {
  return {
    id: line.id,
    product_id: line.product_id === null ? '' : String(line.product_id),
    qty: String(line.qty),
    price_unit: line.price_unit,
    tag: line.tag,
    tax_ids: [...line.tax_ids],
  };
}

/** PURE — detail backend → nilai form (dipakai halaman edit, bukan state). */
export function orderFormFromDetail(detail: SalesOrderDetail): OrderFormValues {
  return {
    customer_id: detail.customer_id === null ? '' : String(detail.customer_id),
    order_type: detail.order_type,
    priority: String(detail.priority),
    deadline: detail.deadline === null ? '' : detail.deadline.slice(0, 10),
    lines: detail.lines.length === 0 ? [emptyOrderLine()] : detail.lines.map(orderLineFormFromRow),
  };
}

/** PURE — nilai form → body API (baris tanpa produk dibuang, harga default 0). */
export function orderInputFromForm(values: OrderFormValues): SalesOrderInput {
  const lines: SalesOrderLineInput[] = [];

  for (const line of values.lines) {
    const productId = toNullableId(line.product_id);
    if (productId === null) continue;

    lines.push({
      product_id: productId,
      qty: toNullableNumber(line.qty) ?? 0,
      price_unit: (toNullableNumber(line.price_unit) ?? 0).toFixed(2),
      tag: line.tag.trim(),
      tax_ids: [...line.tax_ids],
    });
  }

  const deadline = values.deadline.trim();

  return {
    customer_id: toNullableId(values.customer_id),
    order_type: values.order_type,
    priority: toNullableNumber(values.priority) ?? 0,
    deadline: deadline.length === 0 ? null : deadline,
    lines,
  };
}

// ---------------------------------------------------------------------------
// Label & item detail (PURE)
// ---------------------------------------------------------------------------
/** PURE — label opsi (`KODE - nama`; fallback kalau salah satu kosong). */
export function orderOptionLabel(row: { code: string; name: string }): string {
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

/** Satu baris detail order (label + nilai siap tampil). */
export interface OrderDetailItem {
  label: string;
  value: string;
  mono?: boolean;
}

/** PURE — daftar field halaman detail order (urutan tetap). */
export function orderDetailItems(row: SalesOrderRow): OrderDetailItem[] {
  return [
    { label: 'Kode', value: displayOrDash(row.code), mono: true },
    { label: 'Ref Pelanggan', value: displayOrDash(row.client_order_ref) },
    { label: 'Customer', value: displayOrDash(row.customer_name) },
    { label: 'Tipe Order', value: displayOrDash(row.order_type) },
    { label: 'State', value: orderStateLabel(row.state), mono: true },
    { label: 'Prioritas', value: String(row.priority) },
    { label: 'Deadline', value: displayDate(row.deadline) },
    { label: 'Jumlah Baris', value: String(row.lines_count) },
    { label: 'Total', value: displayOrDash(row.amount_total), mono: true },
    { label: 'Odoo ID', value: row.odoo_id === null ? 'belum dikirim' : String(row.odoo_id) },
  ];
}

/** PURE — daftar state untuk filter daftar (`all` + 4 state MES). */
export const ORDER_STATE_FILTERS: { id: string; label: string }[] = [
  { id: 'all', label: 'Semua' },
  { id: 'DRAFT', label: 'Draft' },
  { id: 'CONFIRMED', label: 'Terkonfirmasi' },
  { id: 'DONE', label: 'Selesai' },
  { id: 'CANCELLED', label: 'Dibatalkan' },
];

/** PURE — state filter UI → param `state` backend (`null` = tidak difilter). */
export function stateParamForFilter(state: string): string | null {
  return state === 'all' ? null : state;
}

/** Semua state MES (untuk validasi filter tabs). */
export const ORDER_STATES: readonly SalesOrderState[] = [
  'DRAFT',
  'CONFIRMED',
  'DONE',
  'CANCELLED',
];



