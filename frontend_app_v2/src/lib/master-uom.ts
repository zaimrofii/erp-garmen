/**
 * master-uom.ts — logic PURE halaman master UoM (H1.2).
 *
 * Dipisah dari halaman supaya bisa diuji TANPA DOM (jsdom tidak jalan di bun —
 * `.clinerules` §ENVIRONMENT): validasi form, konversi row ↔ form, dan opsi
 * `uom_type` semuanya fungsi murni di sini.
 */
import type { MasterUomInput, MasterUomRow, UomType } from '@/types/master-uom';

/** Nilai form (semua input = string; `active` = checkbox). */
export interface UomFormValues {
  code: string;
  name: string;
  category: string;
  uom_type: UomType;
  factor: string;
  rounding: string;
  active: boolean;
}

/** Pesan error per field (kosong = valid). */
export interface UomFormErrors {
  code?: string;
  name?: string;
  category?: string;
  factor?: string;
  rounding?: string;
}

/** Nilai awal form "UoM Baru" (default = default model backend). */
export const EMPTY_UOM_FORM: UomFormValues = {
  code: '',
  name: '',
  category: '',
  uom_type: 'reference',
  factor: '1',
  rounding: '0.01',
  active: true,
};

/** Opsi dropdown tipe (label Indonesia; `value` HARUS sama dengan Odoo). */
export const UOM_TYPE_OPTIONS: { value: UomType; label: string }[] = [
  { value: 'reference', label: 'Referensi (unit dasar kategori)' },
  { value: 'bigger', label: 'Lebih besar dari referensi' },
  { value: 'smaller', label: 'Lebih kecil dari referensi' },
];

/** PURE - menyempitkan `string` dari `<select>` ke `UomType` TANPA cast `as`. */
export function isUomType(value: string): value is UomType {
  return UOM_TYPE_OPTIONS.some((option) => option.value === value);
}

/** Kode UoM maksimal 64 karakter (kolom `master.UoM.code`). */
export const MAX_CODE_LENGTH = 64;

/** PURE — nilai angka form → number, atau `null` kalau bukan angka. */
export function parseFormNumber(value: string): number | null {
  const trimmed = value.trim();
  if (trimmed.length === 0) return null;

  const parsed = Number(trimmed);

  return Number.isFinite(parsed) ? parsed : null;
}

/** PURE — validasi form; objek KOSONG berarti boleh dikirim. */
export function validateUomForm(values: UomFormValues): UomFormErrors {
  const errors: UomFormErrors = {};

  const code = values.code.trim();
  if (code.length === 0) {
    errors.code = 'Kode UoM wajib diisi.';
  } else if (code.length > MAX_CODE_LENGTH) {
    errors.code = `Kode maksimal ${String(MAX_CODE_LENGTH)} karakter.`;
  }

  if (values.name.trim().length === 0) {
    errors.name = 'Nama UoM wajib diisi.';
  }

  if (values.category.trim().length === 0) {
    errors.category = 'Kategori wajib diisi (Odoo: uom.category).';
  }

  for (const field of ['factor', 'rounding'] as const) {
    const parsed = parseFormNumber(values[field]);

    if (parsed === null) {
      errors[field] = 'Isi angka (mis. 1 untuk rasio, 0.01 untuk presisi).';
    } else if (parsed <= 0) {
      errors[field] = 'Nilai harus lebih besar dari 0 (Odoo menolak 0).';
    }
  }

  return errors;
}

/** PURE — true kalau tidak ada error (siap submit). */
export function isUomFormValid(errors: UomFormErrors): boolean {
  return Object.keys(errors).length === 0;
}

/** PURE — baris backend → nilai form (dipakai halaman edit). */
export function uomFormFromRow(row: MasterUomRow): UomFormValues {
  return {
    code: row.code,
    name: row.name,
    category: row.category,
    uom_type: row.uom_type,
    factor: String(row.factor),
    rounding: String(row.rounding),
    active: row.active,
  };
}

/** PURE — nilai form → body API (angka di-parse; fallback default kalau kosong). */
export function uomInputFromForm(values: UomFormValues): MasterUomInput {
  return {
    code: values.code.trim(),
    name: values.name.trim(),
    category: values.category.trim(),
    uom_type: values.uom_type,
    factor: parseFormNumber(values.factor) ?? 1,
    rounding: parseFormNumber(values.rounding) ?? 0.01,
    active: values.active,
  };
}

/** PURE — label dropdown untuk satu baris UoM (`KODE - nama`). */
export function uomOptionLabel(row: MasterUomRow): string {
  const code = row.code.trim();
  const name = row.name.trim();

  if (code.length === 0) return name;
  if (name.length === 0) return code;

  return `${code} - ${name}`;
}

/** Satu baris detail UoM (label + nilai siap tampil). */
export interface MasterUomDetailItem {
  label: string;
  value: string;
  mono?: boolean;
}

/** PURE — teks sel yang aman untuk nilai nullable (`null`/'' → '-'). */
export function displayOrDash(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return '-';
  const text = String(value).trim();

  return text.length === 0 ? '-' : text;
}

/** PURE - daftar field halaman detail UoM (urutan tetap; `null` → label khusus). */
export function uomDetailItems(row: MasterUomRow): MasterUomDetailItem[] {
  return [
    { label: 'Kode', value: displayOrDash(row.code), mono: true },
    { label: 'Nama', value: displayOrDash(row.name) },
    { label: 'Kategori', value: displayOrDash(row.category) },
    {
      label: 'Tipe',
      value: UOM_TYPE_OPTIONS.find((option) => option.value === row.uom_type)?.label ?? row.uom_type,
    },
    { label: 'Rasio (factor)', value: String(row.factor) },
    { label: 'Presisi pembulatan', value: String(row.rounding) },
    { label: 'Odoo ID', value: row.odoo_id === null ? 'belum dikirim' : String(row.odoo_id) },
  ];
}

