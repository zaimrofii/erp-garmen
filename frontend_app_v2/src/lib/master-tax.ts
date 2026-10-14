/**
 * master-tax.ts — logic PURE halaman master Tax (H3.6).
 *
 * Dipisah dari halaman supaya bisa diuji TANPA DOM (jsdom tidak jalan di bun —
 * `.clinerules` §ENVIRONMENT): validasi form, konversi row ↔ form, label tarif,
 * dan opsi `type_tax_use`/`amount_type` semuanya fungsi murni di sini.
 *
 * Angka dibiarkan sebagai **string** selama di form (pola H1.2 `master-uom.ts`);
 * konversi ke `number` hanya saat submit (`taxInputFromForm`).
 */
import { displayOrDash, parseFormNumber } from '@/lib/master-uom';
import type { MasterTaxInput, MasterTaxRow, TaxAmountType, TaxUse } from '@/types/master-tax';

/** Nilai form (semua input = string; checkbox = boolean). */
export interface TaxFormValues {
  code: string;
  name: string;
  amount: string;
  amount_type: TaxAmountType;
  type_tax_use: TaxUse;
  price_include: boolean;
  is_default: boolean;
  active: boolean;
}

/** Pesan error per field (kosong = valid). */
export interface TaxFormErrors {
  code?: string;
  name?: string;
  amount?: string;
}

/** Nilai awal form "Pajak Baru" (default = default model backend). */
export const EMPTY_TAX_FORM: TaxFormValues = {
  code: '',
  name: '',
  amount: '11',
  amount_type: 'percent',
  type_tax_use: 'sale',
  price_include: false,
  is_default: false,
  active: true,
};

/** Opsi dropdown jenis pajak (label Indonesia; `value` HARUS sama dengan Odoo). */
export const TAX_USE_OPTIONS: { value: TaxUse; label: string }[] = [
  { value: 'sale', label: 'Penjualan (sale)' },
  { value: 'purchase', label: 'Pembelian (purchase)' },
  { value: 'none', label: 'Tanpa jenis (none)' },
];

/** Opsi dropdown tipe nilai (label Indonesia; `value` HARUS sama dengan Odoo). */
export const AMOUNT_TYPE_OPTIONS: { value: TaxAmountType; label: string }[] = [
  { value: 'percent', label: 'Persen (%)' },
  { value: 'fixed', label: 'Nominal tetap' },
];

/** Filter jenis pajak di halaman daftar (`all` = tidak difilter). */
export const TAX_USE_FILTERS: { id: string; label: string }[] = [
  { id: 'all', label: 'Semua' },
  { id: 'sale', label: 'Penjualan' },
  { id: 'purchase', label: 'Pembelian' },
];

/** Kode/name/amount mengikuti kolom & validasi backend (`tax_services.py`). */
export const MAX_TAX_CODE_LENGTH = 64;
export const MAX_TAX_NAME_LENGTH = 255;
export const MAX_TAX_AMOUNT = 999.99;

/** PURE - menyempitkan `string` dari `<select>` ke `TaxUse` TANPA cast `as`. */
export function isTaxUse(value: string): value is TaxUse {
  return TAX_USE_OPTIONS.some((option) => option.value === value);
}

/** PURE - menyempitkan `string` dari `<select>` ke `TaxAmountType` TANPA cast `as`. */
export function isTaxAmountType(value: string): value is TaxAmountType {
  return AMOUNT_TYPE_OPTIONS.some((option) => option.value === value);
}

/** PURE - label jenis pajak (`sale` → 'Penjualan (sale)'). */
export function taxUseLabel(value: TaxUse): string {
  return TAX_USE_OPTIONS.find((option) => option.value === value)?.label ?? value;
}

/** PURE - label tipe nilai (`percent` → 'Persen (%)'). */
export function taxAmountTypeLabel(value: TaxAmountType): string {
  return AMOUNT_TYPE_OPTIONS.find((option) => option.value === value)?.label ?? value;
}

/** PURE - tarif siap tampil (`12` + percent → '12%'; `5000` fixed → 'Rp 5000'). */
export function taxAmountLabel(row: Pick<MasterTaxRow, 'amount' | 'amount_type'>): string {
  const amount = Number.isFinite(row.amount) ? row.amount : 0;

  return row.amount_type === 'fixed' ? `Rp ${String(amount)}` : `${String(amount)}%`;
}


/** PURE — validasi form; objek KOSONG berarti boleh dikirim. */
export function validateTaxForm(values: TaxFormValues): TaxFormErrors {
  const errors: TaxFormErrors = {};

  const code = values.code.trim();
  if (code.length > MAX_TAX_CODE_LENGTH) {
    errors.code = `Kode maksimal ${String(MAX_TAX_CODE_LENGTH)} karakter.`;
  }

  if (values.name.trim().length === 0) {
    errors.name = 'Nama pajak wajib diisi.';
  } else if (values.name.trim().length > MAX_TAX_NAME_LENGTH) {
    errors.name = `Nama maksimal ${String(MAX_TAX_NAME_LENGTH)} karakter.`;
  }

  const amount = parseFormNumber(values.amount);
  if (amount === null) {
    errors.amount = 'Isi angka tarif (mis. 11 untuk PPN 11%).';
  } else if (amount < 0) {
    errors.amount = 'Tarif tidak boleh negatif (0 diizinkan untuk PPN 0%).';
  } else if (amount > MAX_TAX_AMOUNT) {
    errors.amount = `Tarif maksimal ${String(MAX_TAX_AMOUNT)}.`;
  }

  return errors;
}

/** PURE — true kalau tidak ada error (siap submit). */
export function isTaxFormValid(errors: TaxFormErrors): boolean {
  return Object.keys(errors).length === 0;
}

/** PURE — baris backend → nilai form (dipakai halaman edit). */
export function taxFormFromRow(row: MasterTaxRow): TaxFormValues {
  return {
    code: row.code,
    name: row.name,
    amount: String(row.amount),
    amount_type: row.amount_type,
    type_tax_use: row.type_tax_use,
    price_include: row.price_include,
    is_default: row.is_default,
    active: row.active,
  };
}

/** PURE — nilai form → body API (angka di-parse; fallback 0 kalau kosong). */
export function taxInputFromForm(values: TaxFormValues): MasterTaxInput {
  return {
    code: values.code.trim(),
    name: values.name.trim(),
    amount: parseFormNumber(values.amount) ?? 0,
    amount_type: values.amount_type,
    type_tax_use: values.type_tax_use,
    price_include: values.price_include,
    is_default: values.is_default,
    active: values.active,
  };
}

/** PURE — label dropdown untuk satu baris pajak (`KODE - nama`). */
export function taxOptionLabel(row: MasterTaxRow): string {
  const code = row.code.trim();
  const name = row.name.trim();

  if (code.length === 0) return name;
  if (name.length === 0) return code;

  return `${code} - ${name}`;
}

/** Satu baris detail pajak (label + nilai siap tampil). */
export interface MasterTaxDetailItem {
  label: string;
  value: string;
  mono?: boolean;
}

/** PURE - daftar field halaman detail pajak (urutan tetap). */
export function taxDetailItems(row: MasterTaxRow): MasterTaxDetailItem[] {
  return [
    { label: 'Kode', value: displayOrDash(row.code), mono: true },
    { label: 'Nama', value: displayOrDash(row.name) },
    { label: 'Tarif', value: taxAmountLabel(row) },
    { label: 'Tipe nilai', value: taxAmountTypeLabel(row.amount_type) },
    { label: 'Jenis pajak', value: taxUseLabel(row.type_tax_use) },
    { label: 'Harga termasuk pajak', value: row.price_include ? 'Ya' : 'Tidak' },
    { label: 'Pajak default MES', value: row.is_default ? 'Ya' : 'Tidak' },
    { label: 'Odoo ID', value: row.odoo_id === null ? 'belum dikirim' : String(row.odoo_id) },
  ];
}
