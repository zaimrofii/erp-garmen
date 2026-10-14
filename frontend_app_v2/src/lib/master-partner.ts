/**
 * master-partner.ts — logic PURE halaman master Partner (H1.6).
 *
 * Dipisah dari halaman supaya bisa diuji TANPA DOM (jsdom tidak jalan di bun —
 * `.clinerules` §ENVIRONMENT): validasi form (name wajib, NPWP 15/16 digit, email
 * format, guard peran customer/vendor), konversi row ↔ form, filter tab, dan
 * penyusunan item detail semuanya fungsi murni di sini.
 *
 * Aturan yang ditegakkan klien (backend tetap penjaga terakhir → pesan 400-nya
 * diteruskan apa adanya ke Toast):
 *   * ``name`` wajib;
 *   * ``is_customer`` & ``is_vendor`` **tidak boleh keduanya false**;
 *   * ``npwp`` bila diisi: 15 atau 16 digit (titik/strip/spasi diabaikan);
 *   * ``email`` bila diisi harus berbentuk alamat email.
 */
import type {
  MasterPartnerDetail,
  MasterPartnerInput,
  MasterPartnerRow,
} from '@/types/master-partner';

/** Nilai form (input teks = string; peran & aktif = checkbox). */
export interface PartnerFormValues {
  code: string;
  name: string;
  email: string;
  phone: string;
  city: string;
  address: string;
  npwp: string;
  is_customer: boolean;
  is_vendor: boolean;
  is_company: boolean;
  active: boolean;
}

/** Pesan error per field (kosong = valid). */
export interface PartnerFormErrors {
  code?: string;
  name?: string;
  email?: string;
  phone?: string;
  city?: string;
  address?: string;
  npwp?: string;
  roles?: string;
}

/** Nilai awal form "Partner Baru" (default = default model backend). */
export const EMPTY_PARTNER_FORM: PartnerFormValues = {
  code: '',
  name: '',
  email: '',
  phone: '',
  city: '',
  address: '',
  npwp: '',
  is_customer: true,
  is_vendor: false,
  is_company: true,
  active: true,
};

/** Batas panjang teks (selaras kolom model — beda dari DB = 400, bukan 500). */
export const MAX_CODE_LENGTH = 64;
export const MAX_NAME_LENGTH = 255;
export const MAX_PHONE_LENGTH = 32;
export const MAX_CITY_LENGTH = 64;
export const MAX_ADDRESS_LENGTH = 2000;
export const MAX_NPWP_LENGTH = 32;

/** Panjang NPWP yang diterima (digit setelah normalisasi). */
export const NPWP_LENGTHS = [15, 16];

/** PURE — NPWP → digit saja (``01.234.567.8-901.000`` → ``012345678901000``). */
export function normalizeNpwp(value: string): string {
  return value.replace(/\D/g, '');
}

/** PURE — cek bentuk email sederhana (satu ``@`` + domain ber-titik). */
export function isEmailLike(value: string): boolean {
  const text = value.trim();

  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(text);
}

/** PURE — validasi form; objek KOSONG berarti boleh dikirim. */
export function validatePartnerForm(values: PartnerFormValues): PartnerFormErrors {
  const errors: PartnerFormErrors = {};

  const name = values.name.trim();
  if (name.length === 0) {
    errors.name = 'Nama partner wajib diisi.';
  } else if (name.length > MAX_NAME_LENGTH) {
    errors.name = `Nama maksimal ${String(MAX_NAME_LENGTH)} karakter.`;
  }

  const code = values.code.trim();
  if (code.length > MAX_CODE_LENGTH) {
    errors.code = `Kode maksimal ${String(MAX_CODE_LENGTH)} karakter (kosongkan agar dibuat otomatis).`;
  }

  if (!values.is_customer && !values.is_vendor) {
    errors.roles = 'Pilih minimal satu peran: pelanggan atau supplier.';
  }

  const email = values.email.trim();
  if (email.length > 0 && !isEmailLike(email)) {
    errors.email = 'Email tidak valid (contoh: nama@domain.com).';
  }

  const phone = values.phone.trim();
  if (phone.length > MAX_PHONE_LENGTH) {
    errors.phone = `Telepon maksimal ${String(MAX_PHONE_LENGTH)} karakter.`;
  }

  const city = values.city.trim();
  if (city.length > MAX_CITY_LENGTH) {
    errors.city = `Kota maksimal ${String(MAX_CITY_LENGTH)} karakter.`;
  }

  const address = values.address.trim();
  if (address.length > MAX_ADDRESS_LENGTH) {
    errors.address = `Alamat maksimal ${String(MAX_ADDRESS_LENGTH)} karakter.`;
  }

  const npwpRaw = values.npwp.trim();
  if (npwpRaw.length > MAX_NPWP_LENGTH) {
    errors.npwp = `NPWP maksimal ${String(MAX_NPWP_LENGTH)} karakter.`;
  } else {
    const digits = normalizeNpwp(npwpRaw);
    if (digits.length > 0 && !NPWP_LENGTHS.includes(digits.length)) {
      errors.npwp = `NPWP harus ${NPWP_LENGTHS.join(' atau ')} digit (terbaca ${String(digits.length)} digit).`;
    }
  }

  return errors;
}

/** PURE — true kalau tidak ada error (siap submit). */
export function isPartnerFormValid(errors: PartnerFormErrors): boolean {
  return Object.keys(errors).length === 0;
}

/** PURE — baris backend → nilai form (dipakai halaman edit). */
export function partnerFormFromRow(row: MasterPartnerRow): PartnerFormValues {
  return {
    code: row.code,
    name: row.name,
    email: row.email,
    phone: row.phone,
    city: row.city,
    address: row.address,
    npwp: row.npwp,
    is_customer: row.is_customer,
    is_vendor: row.is_vendor,
    is_company: row.is_company,
    active: row.active,
  };
}

/** PURE — nilai form → body API (trim teks; NPWP dikirim apa adanya, backend normalisasi). */
export function partnerInputFromForm(values: PartnerFormValues): MasterPartnerInput {
  return {
    code: values.code.trim(),
    name: values.name.trim(),
    email: values.email.trim(),
    phone: values.phone.trim(),
    city: values.city.trim(),
    address: values.address.trim(),
    npwp: values.npwp.trim(),
    is_customer: values.is_customer,
    is_vendor: values.is_vendor,
    is_company: values.is_company,
    active: values.active,
  };
}

/** PURE — daftar peran partner untuk badge (`Pelanggan`, `Supplier`, keduanya). */
export function partnerRoleLabels(row: Pick<MasterPartnerRow, 'is_customer' | 'is_vendor'>): string[] {
  const labels: string[] = [];
  if (row.is_customer) labels.push('Pelanggan');
  if (row.is_vendor) labels.push('Supplier');

  return labels;
}

/** PURE — teks aman untuk nilai kosong (`''`/`null` → '-'). */
export function displayOrDash(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return '-';
  const text = String(value).trim();

  return text.length === 0 ? '-' : text;
}

/** PURE — NPWP siap tampil: 15/16 digit dikelompokkan, selain itu apa adanya. */
export function formatNpwp(value: string): string {
  const digits = normalizeNpwp(value);
  if (digits.length === 15) {
    return `${digits.slice(0, 2)}.${digits.slice(2, 5)}.${digits.slice(5, 8)}.${digits.slice(8, 9)}-${digits.slice(9, 12)}.${digits.slice(12, 15)}`;
  }
  if (digits.length === 16) {
    return `${digits.slice(0, 4)} ${digits.slice(4, 8)} ${digits.slice(8, 12)} ${digits.slice(12, 16)}`;
  }

  return displayOrDash(value);
}

/** Satu baris detail partner (label + nilai siap tampil). */
export interface MasterPartnerDetailItem {
  label: string;
  value: string;
  mono?: boolean;
}

/** PURE - daftar field halaman detail partner (urutan tetap). */
export function partnerDetailItems(row: MasterPartnerRow): MasterPartnerDetailItem[] {
  return [
    { label: 'Kode', value: displayOrDash(row.code), mono: true },
    { label: 'Nama', value: displayOrDash(row.name) },
    { label: 'Peran', value: partnerRoleLabels(row).join(' + ') || '-' },
    { label: 'Jenis', value: row.is_company ? 'Perusahaan' : 'Perorangan' },
    { label: 'Email', value: displayOrDash(row.email) },
    { label: 'Telepon', value: displayOrDash(row.phone) },
    { label: 'Kota', value: displayOrDash(row.city) },
    { label: 'NPWP', value: formatNpwp(row.npwp), mono: true },
    { label: 'Rank Pelanggan', value: String(row.customer_rank) },
    { label: 'Rank Supplier', value: String(row.supplier_rank) },
    { label: 'Odoo ID', value: row.odoo_id === null ? 'belum dikirim' : String(row.odoo_id) },
  ];
}

/** PURE - jumlah order yang memakai partner (dari detail) siap tampil. */
export function ordersCountLabel(detail: MasterPartnerDetail): string {
  return `${String(detail.orders_count)} order`;
}
