/**
 * master-currency.ts — logic PURE halaman Currency (H5.2).
 *
 * Dipisah dari halaman supaya bisa diuji TANPA DOM (jsdom tidak jalan di bun —
 * `.clinerules` §ENVIRONMENT): validasi form (create/edit), konversi form ↔ payload,
 * dan helper tampilan. Backend tetap penjaga terakhir (400 diteruskan ke UI apa adanya).
 */
import type {
  MasterCurrencyCreateInput,
  MasterCurrencyInput,
  MasterCurrencyRow,
} from '@/types/master-currency';

/** Batas selaras service backend (`master/currency_services.py`). */
export const CURRENCY_CODE_LENGTH = 3;
/** Pola PERSIS `CODE_PATTERN` backend (baris baru): 3 huruf A-Z, auto-upper. */
export const CURRENCY_CODE_PATTERN = /^[A-Z]{3}$/;
export const MAX_CURRENCY_NAME_LENGTH = 255;
export const MAX_CURRENCY_SYMBOL_LENGTH = 8;

/** Nilai form (input teks = string; `rate` kosong = tidak diisi). */
export interface CurrencyFormValues {
  code: string;
  name: string;
  symbol: string;
  rate: string;
}

/** Pesan error per field (kosong = valid). */
export interface CurrencyFormErrors {
  code?: string;
  name?: string;
  symbol?: string;
  rate?: string;
}

/** Nilai awal form create. */
export const EMPTY_CURRENCY_FORM: CurrencyFormValues = {
  code: '',
  name: '',
  symbol: '',
  rate: '',
};

/** PURE — baris mata uang → nilai form (`rate` `null` → string kosong). */
export function currencyFormFromRow(row: MasterCurrencyRow): CurrencyFormValues {
  return {
    code: row.code,
    name: row.name,
    symbol: row.symbol,
    rate: row.rate === null ? '' : String(row.rate),
  };
}

/** Validasi field yang sama di create & edit (name/symbol/rate). */
function validateShared(values: CurrencyFormValues): CurrencyFormErrors {
  const errors: CurrencyFormErrors = {};

  const name = values.name.trim();
  if (!name) {
    errors.name = 'Nama wajib diisi.';
  } else if (name.length > MAX_CURRENCY_NAME_LENGTH) {
    errors.name = `Nama maksimal ${MAX_CURRENCY_NAME_LENGTH} karakter.`;
  }

  const symbol = values.symbol.trim();
  if (symbol.length > MAX_CURRENCY_SYMBOL_LENGTH) {
    errors.symbol = `Simbol maksimal ${MAX_CURRENCY_SYMBOL_LENGTH} karakter.`;
  }

  const rate = values.rate.trim();
  if (rate !== '') {
    const parsed = Number(rate);
    if (!Number.isFinite(parsed)) {
      errors.rate = 'Kurs harus angka.';
    } else if (parsed < 0) {
      errors.rate = 'Kurs tidak boleh negatif.';
    }
  }

  return errors;
}

/** Validasi form **create** → error per field (kode wajib ISO 3 huruf). */
export function validateCurrencyCreateForm(values: CurrencyFormValues): CurrencyFormErrors {
  const errors = validateShared(values);
  const code = values.code.trim().toUpperCase();

  if (!code) {
    errors.code = 'Kode wajib diisi (kode ISO 3 huruf, mis. IDR).';
  } else if (!CURRENCY_CODE_PATTERN.test(code)) {
    errors.code = `Kode harus ${CURRENCY_CODE_LENGTH} huruf A-Z (mis. IDR/USD).`;
  }

  return errors;
}

/**
 * Validasi form **edit** → error per field.
 *
 * `code` hanya divalidasi kalau **berubah** dari `originalCode`: baris hasil pull I1
 * ber-kode `ODOO-<id>` tetap bisa diedit (name/symbol/rate) tanpa error palsu —
 * perilaku yang sama dengan backend H5.2 (echo `code` tidak divalidasi ulang).
 */
export function validateCurrencyEditForm(
  values: CurrencyFormValues,
  originalCode: string,
): CurrencyFormErrors {
  const errors = validateShared(values);
  const code = values.code.trim().toUpperCase();
  const unchanged = code === '' || code === originalCode.trim().toUpperCase();

  if (!unchanged && !CURRENCY_CODE_PATTERN.test(code)) {
    errors.code = `Kode harus ${CURRENCY_CODE_LENGTH} huruf A-Z (mis. IDR/USD).`;
  }

  return errors;
}

/** PURE — form → body `POST` (`rate` kosong tidak dikirim). */
export function currencyCreateInputFromForm(
  values: CurrencyFormValues,
): MasterCurrencyCreateInput {
  const input: MasterCurrencyCreateInput = {
    code: values.code.trim().toUpperCase(),
    name: values.name.trim(),
    symbol: values.symbol.trim(),
  };
  if (values.rate.trim() !== '') input.rate = Number(values.rate);

  return input;
}

/** PURE — form → body `PUT` (`code` hanya dikirim kalau **berubah**). */
export function currencyUpdateInputFromForm(
  values: CurrencyFormValues,
  originalCode: string,
  active: boolean,
): MasterCurrencyInput {
  const input: MasterCurrencyInput = {
    name: values.name.trim(),
    symbol: values.symbol.trim(),
    rate: values.rate.trim() === '' ? null : Number(values.rate),
    active,
  };
  const code = values.code.trim().toUpperCase();
  if (code !== '' && code !== originalCode.trim().toUpperCase()) {
    input.code = code;
  }

  return input;
}

/** PURE — label sumber baris: `Odoo` (hasil pull I1) atau `MES` (dibuat di MES). */
export function currencySourceLabel(row: MasterCurrencyRow): string {
  return row.odoo_id === null ? 'MES' : 'Odoo';
}

/** PURE — kurs untuk tabel (`—` kalau belum diisi). */
export function currencyRateLabel(row: MasterCurrencyRow): string {
  return row.rate === null ? '—' : String(row.rate);
}
