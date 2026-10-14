/**
 * master-location.ts — logic PURE halaman master lokasi (H1.4).
 *
 * Dipisah dari halaman supaya bisa diuji TANPA DOM (jsdom tidak jalan di bun —
 * `.clinerules` §ENVIRONMENT): validasi form, konversi row ↔ form, opsi dropdown
 * `usage` (7 nilai Odoo), dan penyusunan opsi induk/gudang semuanya fungsi murni.
 *
 * Catatan hierarki: form hanya menyembunyikan pilihan **diri sendiri**; backend tetap
 * penjaga terakhir (400 untuk induk = diri sendiri / turunan sendiri) — pesannya
 * diteruskan apa adanya ke Toast, jadi tidak ada aturan domain yang diduplikasi.
 */
import type { LocationUsage, MasterLocationInput, MasterLocationRow } from '@/types/master-location';

/** Nilai form (`<select>` hanya memberi string; `''` = tanpa induk/gudang). */
export interface LocationFormValues {
  code: string;
  name: string;
  usage: LocationUsage;
  parent_id: string;
  warehouse_id: string;
  active: boolean;
}

/** Pesan error per field (kosong = valid). */
export interface LocationFormErrors {
  code?: string;
  name?: string;
  usage?: string;
  parent_id?: string;
  warehouse_id?: string;
}

/** Nilai awal form "Lokasi Baru" (default = default model backend). */
export const EMPTY_LOCATION_FORM: LocationFormValues = {
  code: '',
  name: '',
  usage: 'internal',
  parent_id: '',
  warehouse_id: '',
  active: true,
};

/** Opsi dropdown jenis lokasi (label Indonesia; `value` HARUS sama dengan Odoo). */
export const LOCATION_USAGE_OPTIONS: { value: LocationUsage; label: string }[] = [
  { value: 'view', label: 'View (hanya wadah hierarki)' },
  { value: 'internal', label: 'Internal (stok nyata)' },
  { value: 'supplier', label: 'Vendor (sumber barang masuk)' },
  { value: 'customer', label: 'Pelanggan (tujuan kirim)' },
  { value: 'inventory', label: 'Kehilangan persediaan (adjustment)' },
  { value: 'production', label: 'Produksi' },
  { value: 'transit', label: 'Transit (perjalanan antar lokasi)' },
];

/** Kode lokasi maksimal 64 karakter (kolom `master.Location.code`). */
export const MAX_CODE_LENGTH = 64;

/** Nama lokasi maksimal 255 karakter (kolom `master.Location.name`). */
export const MAX_NAME_LENGTH = 255;

/** PURE - menyempitkan `string` dari `<select>` ke `LocationUsage` TANPA cast `as`. */
export function isLocationUsage(value: string): value is LocationUsage {
  return LOCATION_USAGE_OPTIONS.some((option) => option.value === value);
}

/** PURE - label manusiawi untuk satu nilai `usage`. */
export function usageLabel(value: LocationUsage): string {
  return LOCATION_USAGE_OPTIONS.find((option) => option.value === value)?.label ?? value;
}

/** PURE - id dari `<select>`: `''`/bukan angka → `null` (tanpa induk/gudang). */
export function toNullableId(value: string): number | null {
  const trimmed = value.trim();
  if (trimmed.length === 0) return null;

  const parsed = Number(trimmed);

  return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
}

/** PURE — validasi form; objek KOSONG berarti boleh dikirim. */
export function validateLocationForm(values: LocationFormValues): LocationFormErrors {
  const errors: LocationFormErrors = {};

  const code = values.code.trim();
  if (code.length === 0) {
    errors.code = 'Kode lokasi wajib diisi.';
  } else if (code.length > MAX_CODE_LENGTH) {
    errors.code = `Kode maksimal ${String(MAX_CODE_LENGTH)} karakter.`;
  }

  const name = values.name.trim();
  if (name.length === 0) {
    errors.name = 'Nama lokasi wajib diisi.';
  } else if (name.length > MAX_NAME_LENGTH) {
    errors.name = `Nama maksimal ${String(MAX_NAME_LENGTH)} karakter.`;
  }

  if (!isLocationUsage(values.usage)) {
    errors.usage = 'Jenis lokasi tidak dikenal.';
  }

  if (values.parent_id.trim().length > 0 && toNullableId(values.parent_id) === null) {
    errors.parent_id = 'Induk tidak valid.';
  }

  if (values.warehouse_id.trim().length > 0 && toNullableId(values.warehouse_id) === null) {
    errors.warehouse_id = 'Gudang tidak valid.';
  }

  return errors;
}

/** PURE — true kalau tidak ada error (siap submit). */
export function isLocationFormValid(errors: LocationFormErrors): boolean {
  return Object.keys(errors).length === 0;
}

/** PURE — baris backend → nilai form (dipakai halaman edit). */
export function locationFormFromRow(row: MasterLocationRow): LocationFormValues {
  return {
    code: row.code,
    name: row.name,
    usage: row.usage,
    parent_id: row.parent_id === null ? '' : String(row.parent_id),
    warehouse_id: row.warehouse_id === null ? '' : String(row.warehouse_id),
    active: row.active,
  };
}

/** PURE — nilai form → body API (`''` → `null`, artinya akar/tanpa gudang). */
export function locationInputFromForm(values: LocationFormValues): MasterLocationInput {
  return {
    code: values.code.trim(),
    name: values.name.trim(),
    usage: values.usage,
    parent_id: toNullableId(values.parent_id),
    warehouse_id: toNullableId(values.warehouse_id),
    active: values.active,
  };
}

/** PURE — label opsi untuk satu baris lokasi (`KODE - nama`). */
export function locationOptionLabel(row: MasterLocationRow): string {
  const code = row.code.trim();
  const name = row.name.trim();

  if (code.length === 0) return name;
  if (name.length === 0) return code;

  return `${code} - ${name}`;
}

/**
 * PURE — kandidat induk: buang baris yang sedang diedit + lokasi nonaktif.
 * Siklus (induk = turunan sendiri) dijaga backend (400) — lihat catatan modul.
 */
export function selectableParentOptions(
  rows: readonly MasterLocationRow[],
  currentId: number | null,
): MasterLocationRow[] {
  return rows.filter((row) => row.id !== currentId && row.active);
}

/** PURE — teks aman untuk nilai nullable (`null`/'' → '-'). */
export function displayOrDash(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return '-';
  const text = String(value).trim();

  return text.length === 0 ? '-' : text;
}

/** Satu baris detail lokasi (label + nilai siap tampil). */
export interface MasterLocationDetailItem {
  label: string;
  value: string;
  mono?: boolean;
}

/** PURE - daftar field halaman detail lokasi (urutan tetap). */
export function locationDetailItems(row: MasterLocationRow): MasterLocationDetailItem[] {
  return [
    { label: 'Kode', value: displayOrDash(row.code), mono: true },
    { label: 'Nama', value: displayOrDash(row.name) },
    { label: 'Jenis', value: usageLabel(row.usage) },
    { label: 'Nama Lengkap', value: displayOrDash(row.complete_name) },
    { label: 'Induk', value: displayOrDash(row.parent_name) },
    { label: 'Gudang', value: displayOrDash(row.warehouse_name) },
    { label: 'Anak Langsung', value: String(row.children_count) },
    { label: 'Odoo ID', value: row.odoo_id === null ? 'belum dikirim' : String(row.odoo_id) },
  ];
}
