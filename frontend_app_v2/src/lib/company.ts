/**
 * company.ts — logic PURE halaman Company Profile (H5.1).
 *
 * Dipisah dari halaman supaya bisa diuji TANPA DOM (jsdom tidak jalan di bun —
 * `.clinerules` §ENVIRONMENT): validasi form, konversi form ↔ payload, dan helper
 * tampilan. Backend tetap penjaga terakhir (400 diteruskan ke UI apa adanya).
 *
 * **Reuse H1.6** (`@/lib/master-partner`): `isEmailLike`, `normalizeNpwp`,
 * `NPWP_LENGTHS`, `MAX_NPWP_LENGTH` — validasi NPWP/email TIDAK diduplikasi.
 */
import { isEmailLike, normalizeNpwp, NPWP_LENGTHS, MAX_NPWP_LENGTH } from '@/lib/master-partner';
import type { CompanyInput, CompanyRow } from '@/types/company';

/** Batas selaras service backend (`master/company_services.py`). */
export const MAX_COMPANY_NAME_LENGTH = 255;
export const MAX_COMPANY_LEGAL_NAME_LENGTH = 255;
export const MAX_COMPANY_CITY_LENGTH = 64;
export const MAX_COMPANY_PHONE_LENGTH = 32;
export const MAX_COMPANY_WEBSITE_LENGTH = 200;
export const MAX_COMPANY_LOGO_URL_LENGTH = 500;
export const MAX_COMPANY_TIMEZONE_LENGTH = 64;

/** Pola PERSIS `COUNTRY_PATTERN` backend: ISO 3166-1 alpha-2 (auto-upper). */
export const COMPANY_COUNTRY_PATTERN = /^[A-Z]{2}$/;
export const DEFAULT_COMPANY_TIMEZONE = 'Asia/Jakarta';

/** Nilai form (semua input teks = string; `currencyId` string agar bisa dikosongkan). */
export interface CompanyFormValues {
  name: string;
  legal_name: string;
  address: string;
  city: string;
  country: string;
  phone: string;
  email: string;
  npwp: string;
  website: string;
  logo_url: string;
  currencyId: string;
  timezone: string;
  active: boolean;
}

/** Pesan error per field (kosong = valid). */
export interface CompanyFormErrors {
  name?: string;
  legal_name?: string;
  city?: string;
  country?: string;
  phone?: string;
  email?: string;
  npwp?: string;
  website?: string;
  logo_url?: string;
  timezone?: string;
}

/** Nilai awal form (profil belum pernah diisi). */
export const EMPTY_COMPANY_FORM: CompanyFormValues = {
  name: '',
  legal_name: '',
  address: '',
  city: '',
  country: '',
  phone: '',
  email: '',
  npwp: '',
  website: '',
  logo_url: '',
  currencyId: '',
  timezone: DEFAULT_COMPANY_TIMEZONE,
  active: true,
};

/** PURE — baris company (atau `null`) → nilai form. */
export function companyFormFromRow(row: CompanyRow | null): CompanyFormValues {
  if (row === null) return { ...EMPTY_COMPANY_FORM };

  return {
    name: row.name,
    legal_name: row.legal_name,
    address: row.address,
    city: row.city,
    country: row.country,
    phone: row.phone,
    email: row.email,
    npwp: row.npwp,
    website: row.website,
    logo_url: row.logo_url,
    currencyId: row.currency_id === null ? '' : String(row.currency_id),
    timezone: row.timezone,
    active: row.is_active,
  };
}

/** PURE — URL http/https (dipakai `website` & `logo_url`). */
export function isHttpUrl(value: string): boolean {
  try {
    const url = new URL(value);

    return url.protocol === 'http:' || url.protocol === 'https:';
  } catch {
    return false;
  }
}

/** Validasi form → error per field (cermin `validate_company_payload` backend). */
export function validateCompanyForm(values: CompanyFormValues): CompanyFormErrors {
  const errors: CompanyFormErrors = {};

  const name = values.name.trim();
  if (!name) {
    errors.name = 'Nama perusahaan wajib diisi.';
  } else if (name.length > MAX_COMPANY_NAME_LENGTH) {
    errors.name = `Nama maksimal ${MAX_COMPANY_NAME_LENGTH} karakter.`;
  }

  if (values.legal_name.trim().length > MAX_COMPANY_LEGAL_NAME_LENGTH) {
    errors.legal_name = `Nama legal maksimal ${MAX_COMPANY_LEGAL_NAME_LENGTH} karakter.`;
  }

  if (values.city.trim().length > MAX_COMPANY_CITY_LENGTH) {
    errors.city = `Kota maksimal ${MAX_COMPANY_CITY_LENGTH} karakter.`;
  }

  if (values.phone.trim().length > MAX_COMPANY_PHONE_LENGTH) {
    errors.phone = `Telepon maksimal ${MAX_COMPANY_PHONE_LENGTH} karakter.`;
  }

  const country = values.country.trim().toUpperCase();
  if (country !== '' && !COMPANY_COUNTRY_PATTERN.test(country)) {
    errors.country = 'Negara harus 2 huruf kode ISO (mis. ID).';
  }

  const email = values.email.trim();
  if (email !== '' && !isEmailLike(email)) {
    errors.email = 'Email tidak valid.';
  }

  const npwpRaw = values.npwp.trim();
  if (npwpRaw.length > MAX_NPWP_LENGTH) {
    errors.npwp = `NPWP maksimal ${String(MAX_NPWP_LENGTH)} karakter.`;
  } else {
    const digits = normalizeNpwp(npwpRaw);
    if (digits.length > 0 && !NPWP_LENGTHS.includes(digits.length)) {
      errors.npwp = `NPWP harus ${NPWP_LENGTHS.join(' atau ')} digit (${String(
        digits.length,
      )} digit terdeteksi).`;
    }
  }

  const website = values.website.trim();
  if (website.length > MAX_COMPANY_WEBSITE_LENGTH) {
    errors.website = `Website maksimal ${MAX_COMPANY_WEBSITE_LENGTH} karakter.`;
  } else if (website !== '' && !isHttpUrl(website)) {
    errors.website = 'Website harus URL http/https.';
  }

  const logoUrl = values.logo_url.trim();
  if (logoUrl.length > MAX_COMPANY_LOGO_URL_LENGTH) {
    errors.logo_url = `Logo maksimal ${MAX_COMPANY_LOGO_URL_LENGTH} karakter.`;
  } else if (logoUrl !== '' && !isHttpUrl(logoUrl)) {
    errors.logo_url = 'Logo harus URL http/https.';
  }

  if (values.timezone.trim().length > MAX_COMPANY_TIMEZONE_LENGTH) {
    errors.timezone = `Zona waktu maksimal ${MAX_COMPANY_TIMEZONE_LENGTH} karakter.`;
  }

  return errors;
}

/** PURE — form valid (tak ada error). */
export function isCompanyFormValid(errors: CompanyFormErrors): boolean {
  return Object.keys(errors).length === 0;
}

/** PURE — form → body `PUT` (semua field dikirim; `currencyId` kosong → `null`). */
export function companyInputFromForm(values: CompanyFormValues): CompanyInput {
  const timezone = values.timezone.trim();
  const currencyId = values.currencyId.trim();

  return {
    name: values.name.trim(),
    legal_name: values.legal_name.trim(),
    address: values.address.trim(),
    city: values.city.trim(),
    country: values.country.trim().toUpperCase(),
    phone: values.phone.trim(),
    email: values.email.trim(),
    npwp: normalizeNpwp(values.npwp),
    website: values.website.trim(),
    logo_url: values.logo_url.trim(),
    currency_id: currencyId === '' ? null : Number(currencyId),
    timezone: timezone === '' ? DEFAULT_COMPANY_TIMEZONE : timezone,
    active: values.active,
  };
}
