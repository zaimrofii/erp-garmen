/**
 * master-warehouse.ts — logic PURE halaman master gudang (H1.3).
 *
 * Dipisah dari halaman supaya bisa diuji TANPA DOM (jsdom tidak jalan di bun —
 * `.clinerules` §ENVIRONMENT): validasi form, konversi row ↔ form, dan opsi
 * `reception_steps`/`delivery_steps` semuanya fungsi murni di sini.
 *
 * Catatan panjang kode: MES membolehkan **64** karakter, sedangkan ``short_name``
 * Odoo hanya 5 karakter (probe ``fields_get``). Guard 5 karakter ada di **task**
 * (``MasterPushError``) supaya data MES tidak perlu dipotong di sini — form hanya
 * memberi hint.
 */
import type {
  DeliverySteps,
  MasterWarehouseInput,
  MasterWarehouseRow,
  ReceptionSteps,
} from '@/types/master-warehouse';

/** Nilai form (input teks = string; `active` = checkbox). */
export interface WarehouseFormValues {
  code: string;
  name: string;
  reception_steps: ReceptionSteps;
  delivery_steps: DeliverySteps;
  active: boolean;
}

/** Pesan error per field (kosong = valid). */
export interface WarehouseFormErrors {
  code?: string;
  name?: string;
}

/** Nilai awal form "Gudang Baru" (default = default model backend). */
export const EMPTY_WAREHOUSE_FORM: WarehouseFormValues = {
  code: '',
  name: '',
  reception_steps: 'one_step',
  delivery_steps: 'ship_only',
  active: true,
};

/** Opsi dropdown penerimaan (label Indonesia; `value` HARUS sama dengan Odoo). */
export const RECEPTION_STEP_OPTIONS: { value: ReceptionSteps; label: string }[] = [
  { value: 'one_step', label: 'Terima langsung ke stok (1 langkah)' },
  { value: 'two_steps', label: 'Terima ke input lalu stok (2 langkah)' },
  { value: 'three_steps', label: 'Terima ke input, QC, lalu stok (3 langkah)' },
];

/** Opsi dropdown pengiriman (label Indonesia; `value` HARUS sama dengan Odoo). */
export const DELIVERY_STEP_OPTIONS: { value: DeliverySteps; label: string }[] = [
  { value: 'ship_only', label: 'Kirim langsung (1 langkah)' },
  { value: 'pick_ship', label: 'Ambil lalu kirim (2 langkah)' },
  { value: 'pick_pack_ship', label: 'Ambil, kemas, lalu kirim (3 langkah)' },
];

/** Kode gudang maksimal 64 karakter (kolom `master.Warehouse.code`). */
export const MAX_CODE_LENGTH = 64;

/** ``short_name`` Odoo (`stock.warehouse.code`) — info untuk pengguna (guard di task). */
export const ODOO_CODE_MAX_LENGTH = 5;

/** PURE - menyempitkan `string` dari `<select>` ke `ReceptionSteps` TANPA cast `as`. */
export function isReceptionSteps(value: string): value is ReceptionSteps {
  return RECEPTION_STEP_OPTIONS.some((option) => option.value === value);
}

/** PURE - menyempitkan `string` dari `<select>` ke `DeliverySteps` TANPA cast `as`. */
export function isDeliverySteps(value: string): value is DeliverySteps {
  return DELIVERY_STEP_OPTIONS.some((option) => option.value === value);
}

/** PURE — validasi form; objek KOSONG berarti boleh dikirim. */
export function validateWarehouseForm(values: WarehouseFormValues): WarehouseFormErrors {
  const errors: WarehouseFormErrors = {};

  const code = values.code.trim();
  if (code.length === 0) {
    errors.code = 'Kode gudang wajib diisi.';
  } else if (code.length > MAX_CODE_LENGTH) {
    errors.code = `Kode maksimal ${String(MAX_CODE_LENGTH)} karakter.`;
  }

  if (values.name.trim().length === 0) {
    errors.name = 'Nama gudang wajib diisi.';
  }

  return errors;
}

/** PURE — true kalau tidak ada error (siap submit). */
export function isWarehouseFormValid(errors: WarehouseFormErrors): boolean {
  return Object.keys(errors).length === 0;
}

/** PURE — baris backend → nilai form (dipakai halaman edit). */
export function warehouseFormFromRow(row: MasterWarehouseRow): WarehouseFormValues {
  return {
    code: row.code,
    name: row.name,
    reception_steps: row.reception_steps,
    delivery_steps: row.delivery_steps,
    active: row.active,
  };
}

/** PURE — nilai form → body API. */
export function warehouseInputFromForm(values: WarehouseFormValues): MasterWarehouseInput {
  return {
    code: values.code.trim(),
    name: values.name.trim(),
    reception_steps: values.reception_steps,
    delivery_steps: values.delivery_steps,
    active: values.active,
  };
}

/** PURE — label dropdown untuk satu baris gudang (`KODE - nama`). */
export function warehouseOptionLabel(row: MasterWarehouseRow): string {
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

/** Satu baris detail gudang (label + nilai siap tampil). */
export interface MasterWarehouseDetailItem {
  label: string;
  value: string;
  mono?: boolean;
}

/** PURE - daftar field halaman detail gudang (urutan tetap). */
export function warehouseDetailItems(row: MasterWarehouseRow): MasterWarehouseDetailItem[] {
  return [
    { label: 'Kode', value: displayOrDash(row.code), mono: true },
    { label: 'Nama', value: displayOrDash(row.name) },
    {
      label: 'Penerimaan',
      value:
        RECEPTION_STEP_OPTIONS.find((option) => option.value === row.reception_steps)?.label ??
        row.reception_steps,
    },
    {
      label: 'Pengiriman',
      value:
        DELIVERY_STEP_OPTIONS.find((option) => option.value === row.delivery_steps)?.label ??
        row.delivery_steps,
    },
    { label: 'Odoo ID', value: row.odoo_id === null ? 'belum dikirim' : String(row.odoo_id) },
    { label: 'Catatan Odoo', value: `short_name Odoo maks ${String(ODOO_CODE_MAX_LENGTH)} karakter` },
  ];
}
