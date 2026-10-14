/**
 * master-bom.ts — logic PURE halaman master BOM (H1.5).
 *
 * Dipisah dari halaman supaya bisa diuji TANPA DOM (jsdom tidak jalan di bun —
 * `.clinerules` §ENVIRONMENT): validasi form (header + baris komponen), konversi
 * detail ↔ form, operasi baris (tambah/hapus/urutkan), dan opsi dropdown.
 *
 * Aturan yang ditegakkan klien (backend tetap penjaga terakhir):
 *   * produk BOM wajib dipilih; ``output_qty > 0``;
 *   * setiap baris: produk wajib, ``qty > 0``;
 *   * baris **tidak boleh** memakai produk BOM itu sendiri (self-reference → 400
 *     di backend; di sini hanya diingatkan agar operator tidak mengirim);
 *   * siklus antar-BOM hanya bisa diperiksa backend (butuh seluruh graf) — pesan
 *     400-nya diteruskan apa adanya ke Toast.
 */
import type {
  MasterBomDetail,
  MasterBomInput,
  MasterBomLineInput,
  MasterBomLineRow,
  MasterBomRow,
} from '@/types/master-bom';

/** Nilai satu baris komponen di form (`<select>`/`<input>` = string). */
export interface BomLineFormValues {
  /** pk baris MES (`null` = baris baru, belum pernah disimpan). */
  id: number | null;
  /** id Odoo baris (dipakai backend untuk mencocokkan hasil tarikan). */
  odoo_id: number | null;
  product_id: string;
  qty: string;
  uom_id: string;
  sequence: string;
  notes: string;
}

/** Nilai form BOM (header + baris). */
export interface BomFormValues {
  code: string;
  name: string;
  product_id: string;
  output_qty: string;
  uom_id: string;
  notes: string;
  active: boolean;
  lines: BomLineFormValues[];
}

/** Pesan error per field baris (index-based, dipakai saat submit). */
export interface BomLineFormErrors {
  product_id?: string;
  qty?: string;
  uom_id?: string;
}

/** Pesan error header + per baris. */
export interface BomFormErrors {
  code?: string;
  name?: string;
  product_id?: string;
  output_qty?: string;
  uom_id?: string;
  lines?: Record<number, BomLineFormErrors>;
}

/** Nilai awal form "BOM Baru" (default = default model backend). */
export const EMPTY_BOM_FORM: BomFormValues = {
  code: '',
  name: '',
  product_id: '',
  output_qty: '1',
  uom_id: '',
  notes: '',
  active: true,
  lines: [],
};

/** Batas panjang teks (selaras kolom model). */
export const MAX_CODE_LENGTH = 64;
export const MAX_NAME_LENGTH = 255;

/** Batas jumlah baris komponen (selaras `bom_services.MAX_LINES`). */
export const MAX_LINES = 200;

/** PURE - id dari `<select>`: `''`/bukan angka → `null`. */
export function toNullableId(value: string): number | null {
  const trimmed = value.trim();
  if (trimmed.length === 0) return null;

  const parsed = Number(trimmed);

  return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
}

/** PURE - angka desimal dari `<input>`: kosong/ngawur → `null`. */
export function toNullableQty(value: string): number | null {
  const trimmed = value.trim();
  if (trimmed.length === 0) return null;

  const parsed = Number(trimmed);

  return Number.isFinite(parsed) ? parsed : null;
}

/** PURE - baris komponen baru (produk kosong, qty 1, satuan diwarisi). */
export function emptyBomLine(sequence: number): BomLineFormValues {
  return {
    id: null,
    odoo_id: null,
    product_id: '',
    qty: '1',
    uom_id: '',
    sequence: String(sequence),
    notes: '',
  };
}

/** PURE — validasi form; objek KOSONG berarti boleh dikirim. */
export function validateBomForm(values: BomFormValues): BomFormErrors {
  const errors: BomFormErrors = {};

  const code = values.code.trim();
  if (code.length > MAX_CODE_LENGTH) {
    errors.code = `Kode maksimal ${String(MAX_CODE_LENGTH)} karakter (kosongkan agar dibuat otomatis).`;
  }

  if (values.name.trim().length > MAX_NAME_LENGTH) {
    errors.name = `Nama maksimal ${String(MAX_NAME_LENGTH)} karakter.`;
  }

  if (toNullableId(values.product_id) === null) {
    errors.product_id = 'Produk BOM wajib dipilih.';
  }

  const outputQty = toNullableQty(values.output_qty);
  if (outputQty === null || outputQty <= 0) {
    errors.output_qty = 'Jumlah output harus lebih besar dari 0.';
  }

  if (values.uom_id.trim().length > 0 && toNullableId(values.uom_id) === null) {
    errors.uom_id = 'Satuan tidak valid.';
  }

  const lineErrors: Record<number, BomLineFormErrors> = {};
  values.lines.forEach((line, index) => {
    const current: BomLineFormErrors = {};

    if (toNullableId(line.product_id) === null) {
      current.product_id = 'Produk komponen wajib dipilih.';
    } else if (line.product_id.trim() === values.product_id.trim()) {
      current.product_id = 'Komponen tidak boleh produk BOM sendiri.';
    }

    const qty = toNullableQty(line.qty);
    if (qty === null || qty <= 0) {
      current.qty = 'Qty komponen harus lebih besar dari 0.';
    }

    if (line.uom_id.trim().length > 0 && toNullableId(line.uom_id) === null) {
      current.uom_id = 'Satuan tidak valid.';
    }

    if (Object.keys(current).length > 0) {
      lineErrors[index] = current;
    }
  });

  if (Object.keys(lineErrors).length > 0) {
    errors.lines = lineErrors;
  }

  return errors;
}

/** PURE — true kalau tidak ada error (siap submit). */
export function isBomFormValid(errors: BomFormErrors): boolean {
  return Object.keys(errors).length === 0;
}

// ---------------------------------------------------------------------------
// Operasi baris (PURE — dipakai tombol "Tambah/Hapus baris" di form)
// ---------------------------------------------------------------------------
/** PURE — tambah satu baris kosong dengan ``sequence`` berikutnya (kelipatan 10). */
export function addBomLine(values: BomFormValues): BomFormValues {
  const nextSequence = (values.lines.length + 1) * 10;

  return { ...values, lines: [...values.lines, emptyBomLine(nextSequence)] };
}

/** PURE — hapus baris ke-``index`` (indeks negatif/di luar rentang = tidak berubah). */
export function removeBomLine(values: BomFormValues, index: number): BomFormValues {
  if (index < 0 || index >= values.lines.length) return values;

  return { ...values, lines: values.lines.filter((_, position) => position !== index) };
}

/** PURE — ubah sebagian field baris ke-``index`` (indeks invalid = tidak berubah). */
export function updateBomLine(
  values: BomFormValues,
  index: number,
  patch: Partial<BomLineFormValues>,
): BomFormValues {
  if (index < 0 || index >= values.lines.length) return values;

  return {
    ...values,
    lines: values.lines.map((line, position) =>
      position === index ? { ...line, ...patch } : line,
    ),
  };
}

/** PURE — satu baris backend → nilai form (``id``/``odoo_id`` dibawa agar cocok saat PUT). */
export function bomLineFormFromRow(line: MasterBomLineRow): BomLineFormValues {
  return {
    id: line.id,
    odoo_id: line.odoo_id,
    product_id: line.product_id === null ? '' : String(line.product_id),
    qty: String(line.qty),
    uom_id: line.uom_id === null ? '' : String(line.uom_id),
    sequence: String(line.sequence),
    notes: line.notes,
  };
}

/** PURE — detail backend → nilai form (dipakai halaman edit). */
export function bomFormFromDetail(detail: MasterBomDetail): BomFormValues {
  return {
    code: detail.code,
    name: detail.name,
    product_id: detail.product_id === null ? '' : String(detail.product_id),
    output_qty: String(detail.output_qty),
    uom_id: detail.uom_id === null ? '' : String(detail.uom_id),
    notes: detail.notes,
    active: detail.active,
    lines: detail.lines.map(bomLineFormFromRow),
  };
}

/** PURE — nilai form → body API (baris tanpa produk dibuang, qty default 1). */
export function bomInputFromForm(values: BomFormValues): MasterBomInput {
  const lines: MasterBomLineInput[] = [];

  for (const line of values.lines) {
    const productId = toNullableId(line.product_id);
    if (productId === null) continue;

    lines.push({
      id: line.id,
      odoo_id: line.odoo_id,
      product_id: productId,
      qty: toNullableQty(line.qty) ?? 0,
      uom_id: toNullableId(line.uom_id),
      sequence: toNullableQty(line.sequence) ?? 10,
      notes: line.notes,
    });
  }

  return {
    code: values.code.trim(),
    name: values.name.trim(),
    product_id: toNullableId(values.product_id),
    output_qty: toNullableQty(values.output_qty) ?? 0,
    uom_id: toNullableId(values.uom_id),
    notes: values.notes.trim(),
    active: values.active,
    lines,
  };
}

/** PURE — label opsi produk (`KODE - nama`; fallback kalau salah satu kosong). */
export function productOptionLabel(row: { code: string; name: string }): string {
  const code = row.code.trim();
  const name = row.name.trim();

  if (code.length === 0) return name;
  if (name.length === 0) return code;

  return `${code} - ${name}`;
}

/** PURE — label opsi UoM (`KODE - nama`). */
export function uomOptionLabel(row: { code: string; name: string }): string {
  return productOptionLabel(row);
}

/** PURE — teks aman untuk nilai nullable (`null`/'' → '-'). */
export function displayOrDash(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return '-';
  const text = String(value).trim();

  return text.length === 0 ? '-' : text;
}

/** PURE — total qty komponen (info ringkas di halaman detail/form). */
export function totalLineQty(lines: readonly { qty: number }[]): number {
  return lines.reduce((total, line) => total + (Number.isFinite(line.qty) ? line.qty : 0), 0);
}

/** Satu baris detail BOM (label + nilai siap tampil). */
export interface MasterBomDetailItem {
  label: string;
  value: string;
  mono?: boolean;
}

/** PURE - daftar field halaman detail BOM (urutan tetap). */
export function bomDetailItems(row: MasterBomRow): MasterBomDetailItem[] {
  const output = `${String(row.output_qty)} ${row.uom_code ?? ''}`.trim();

  return [
    { label: 'Kode', value: displayOrDash(row.code), mono: true },
    { label: 'Nama', value: displayOrDash(row.name) },
    {
      label: 'Produk',
      value:
        row.product_code === null && row.product_name === null
          ? '-'
          : productOptionLabel({
              code: row.product_code ?? '',
              name: row.product_name ?? '',
            }),
    },
    { label: 'Output', value: displayOrDash(output) },
    { label: 'Jumlah Komponen', value: String(row.lines_count) },
    { label: 'Catatan', value: displayOrDash(row.notes) },
    { label: 'Odoo ID', value: row.odoo_id === null ? 'belum dikirim' : String(row.odoo_id) },
  ];
}
