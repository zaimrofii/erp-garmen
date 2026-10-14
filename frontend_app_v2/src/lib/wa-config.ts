/**
 * wa-config.ts — logic PURE halaman WA Gateway Config (H5.8).
 *
 * Dipisah dari halaman supaya bisa diuji TANPA DOM (jsdom tidak jalan di bun —
 * `.clinerules` §ENVIRONMENT): validasi form (3 field), konversi form ↔ payload PUT,
 * dan helper tampilan untuk bagian **Status** (effective/diverges).
 *
 * Cermin `master/wa_config_services.py`: guard backend ``real``/``api`` ⇒ ``wa_api_url``
 * + ``wa_api_key`` wajib; ``wa_api_key='***'`` = jangan ubah (rahasia selalu di-mask
 * backend); URL menerima hostname internal **tanpa TLD** (``http://wa-gateway:8080``) —
 * `URLValidator` Django menolaknya, jadi aturan di sini sama dengan ``_is_http_url``
 * backend (pola H5.6).
 */
import type { SelectOption } from '@/components/atoms/Select';
import type { WAConfigInput, WAConfigRow, WAConfigValues } from '@/types/wa-config';
import { SENSITIVE_MASK } from '@/types/wa-config';

/** Mask rahasia (sama dengan backend); nilai ini **tidak** mengubah API key. */
export const WA_MASK = SENSITIVE_MASK;

/** Batas & opsi (selaras service backend). */
export const BACKEND_VALUES = ['mock', 'real', 'api'];
export const REAL_BACKENDS = ['real', 'api'];
export const MAX_URL_LENGTH = 200;
export const MAX_API_KEY_LENGTH = 255;

/** Opsi dropdown backend gateway WA. */
export const BACKEND_OPTIONS: SelectOption[] = [
  { value: 'mock', label: 'Mock (tanpa jaringan)' },
  { value: 'real', label: 'Real (vendor WA)' },
  { value: 'api', label: 'API (HTTP)' },
];

/** Label ramah per field (dipakai form + bagian Status/diverges). */
export const CONFIG_FIELD_LABELS: Record<string, string> = {
  wa_backend: 'Backend WA',
  wa_api_url: 'URL API WA',
  wa_api_key: 'API key WA',
};

/** Nilai form (semua input teks = string; `active` = flag). */
export interface WAConfigFormValues {
  wa_backend: string;
  wa_api_url: string;
  wa_api_key: string;
  active: boolean;
}

/** Pesan error per field (kosong = valid). */
export type WAConfigFormErrors = Partial<Record<keyof WAConfigFormValues, string>>;

/** Nilai awal form (profil belum pernah diisi). */
export const EMPTY_WA_FORM: WAConfigFormValues = {
  wa_backend: 'mock',
  wa_api_url: '',
  wa_api_key: '',
  active: true,
};

/** PURE — baris profil (atau `null`) → nilai form. */
export function waConfigFormFromRow(row: WAConfigRow | null): WAConfigFormValues {
  if (row === null) return { ...EMPTY_WA_FORM };

  return {
    wa_backend: row.wa_backend === '' ? 'mock' : row.wa_backend,
    wa_api_url: row.wa_api_url,
    wa_api_key: row.wa_api_key,
    active: row.is_active,
  };
}

/** PURE — URL http/https **dengan host** (menerima hostname internal tanpa TLD). */
export function isHttpUrl(value: string): boolean {
  try {
    const url = new URL(value);

    return (url.protocol === 'http:' || url.protocol === 'https:') && url.host !== '';
  } catch {
    return false;
  }
}

/** PURE — True kalau nilai API key adalah mask backend (artinya: jangan diubah). */
export function isMaskedApiKey(value: string): boolean {
  return value.trim() === WA_MASK;
}

/** PURE — nilai config untuk tampilan (`null`/kosong → "—"). */
export function formatConfigValue(value: string | number | null): string {
  if (value === null || value === '') return '—';

  return String(value);
}

/** PURE — effective values → baris `{field, label, value}` untuk bagian Status. */
export function effectiveStatusRows(
  effective: WAConfigValues,
): { field: string; label: string; value: string }[] {
  return Object.entries(CONFIG_FIELD_LABELS).map(([field, label]) => ({
    field,
    label,
    value: formatConfigValue(effective[field as keyof WAConfigValues]),
  }));
}

/** PURE — form → body `PUT` (teks di-trim; `***` diteruskan apa adanya). */
export function waConfigInputFromForm(values: WAConfigFormValues): WAConfigInput {
  const apiKey = values.wa_api_key.trim();

  return {
    wa_backend: values.wa_backend.trim().toLowerCase(),
    wa_api_url: values.wa_api_url.trim(),
    // `***` = jangan ubah (backend mengabaikannya); nilai lain (termasuk "") ganti/hapus.
    wa_api_key: apiKey === WA_MASK ? WA_MASK : values.wa_api_key,
    active: values.active,
  };
}

/** Validasi form → error per field (cermin `validate_config_payload` backend). */
export function validateWAConfigForm(values: WAConfigFormValues): WAConfigFormErrors {
  const errors: WAConfigFormErrors = {};

  const backend = values.wa_backend.trim().toLowerCase();
  if (!BACKEND_VALUES.includes(backend)) {
    errors.wa_backend = `Backend harus salah satu dari ${BACKEND_VALUES.join(', ')}.`;
  }

  const url = values.wa_api_url.trim();
  if (url !== '' && !isHttpUrl(url)) {
    errors.wa_api_url = 'URL API harus http/https dengan host (mis. http://wa-gateway:8080).';
  } else if (url.length > MAX_URL_LENGTH) {
    errors.wa_api_url = `URL API maksimal ${MAX_URL_LENGTH} karakter.`;
  }

  if (values.wa_api_key.trim().length > MAX_API_KEY_LENGTH) {
    errors.wa_api_key = `API key maksimal ${MAX_API_KEY_LENGTH} karakter.`;
  }

  // guard: backend real/api wajib punya URL + API key (pola backend; `***` dihitung ada)
  if (REAL_BACKENDS.includes(backend)) {
    if (url === '') {
      errors.wa_api_url = 'Backend real/api membutuhkan URL API.';
    }
    if (values.wa_api_key.trim() === '') {
      errors.wa_api_key = 'Backend real/api membutuhkan API key.';
    }
  }

  return errors;
}

/** PURE — form valid (tak ada error). */
export function isWAConfigFormValid(errors: WAConfigFormErrors): boolean {
  return Object.keys(errors).length === 0;
}
