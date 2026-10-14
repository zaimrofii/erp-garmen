/**
 * master-sequence.ts — logic PURE halaman Number Sequence (Sprint C).
 *
 * Dipisah dari halaman supaya bisa diuji TANPA DOM (jsdom tidak jalan di bun —
 * `.clinerules` §ENVIRONMENT): validasi form edit, konversi form ↔ payload, dan
 * helper tampilan. Backend tetap penjaga terakhir (400 diteruskan ke UI apa adanya).
 */
import type { MasterSequenceCreateInput, MasterSequenceInput } from '@/types/master-sequence';

/** Batas selaras service backend (`master/sequence_services.py`). */
export const MAX_SEQUENCE_NAME_LENGTH = 64;
export const MAX_SEQUENCE_PREFIX_LENGTH = 16;
export const MAX_SEQUENCE_CODE_LENGTH = 16;
export const MIN_SEQUENCE_CODE_LENGTH = 2;
export const DEFAULT_SEQUENCE_PADDING = 4;
export const MIN_SEQUENCE_PADDING = 1;
export const MAX_SEQUENCE_PADDING = 10;

/** Pola PERSIS `CODE_PATTERN` backend (create — H5.3). */
export const SEQUENCE_CODE_PATTERN = /^[A-Z0-9]{2,16}$/;

/** Pola PERSIS `PREFIX_PATTERN` backend (prefix boleh memakai dash). */
export const SEQUENCE_PREFIX_PATTERN = /^[A-Z0-9-]{1,16}$/;

/** Nilai form edit (input teks = string; aktif = flag). */
export interface SequenceFormValues {
  name: string;
  prefix: string;
  padding: string;
  active: boolean;
}

/** Pesan error per field (kosong = valid). */
export interface SequenceFormErrors {
  name?: string;
  prefix?: string;
  padding?: string;
}

/** Validasi form edit → error per field. */
export function validateSequenceForm(values: SequenceFormValues): SequenceFormErrors {
  const errors: SequenceFormErrors = {};

  const name = values.name.trim();
  if (!name) {
    errors.name = 'Nama wajib diisi.';
  } else if (name.length > MAX_SEQUENCE_NAME_LENGTH) {
    errors.name = `Nama maksimal ${MAX_SEQUENCE_NAME_LENGTH} karakter.`;
  }

  const prefix = values.prefix.trim();
  if (!prefix) {
    errors.prefix = 'Prefix wajib diisi (tidak boleh kosong).';
  } else if (prefix.length > MAX_SEQUENCE_PREFIX_LENGTH) {
    errors.prefix = `Prefix maksimal ${MAX_SEQUENCE_PREFIX_LENGTH} karakter.`;
  }

  const padding = Number(values.padding);
  if (values.padding.trim() === '' || !Number.isInteger(padding)) {
    errors.padding = 'Padding harus angka bulat.';
  } else if (padding < MIN_SEQUENCE_PADDING || padding > MAX_SEQUENCE_PADDING) {
    errors.padding = `Padding harus antara ${MIN_SEQUENCE_PADDING} dan ${MAX_SEQUENCE_PADDING}.`;
  }

  return errors;
}

/** PURE — form → body `PUT` (nama/prefix di-trim, padding jadi angka). */
export function sequenceInputFromForm(values: SequenceFormValues): MasterSequenceInput {
  return {
    name: values.name.trim(),
    prefix: values.prefix.trim(),
    padding: Number(values.padding),
    active: values.active,
  };
}

/** PURE — label status untuk tabel. */
export function sequenceStatusLabel(active: boolean): string {
  return active ? 'Aktif' : 'Nonaktif';
}

// ---------------------------------------------------------------------------
// H5.3 — form CREATE (POST /settings/sequences/)
// ---------------------------------------------------------------------------

/** Nilai form create (semua input teks = string). */
export interface CreateSequenceFormValues {
  code: string;
  name: string;
  prefix: string;
  padding: string;
}

/** Pesan error per field form create (kosong = valid). */
export interface CreateSequenceFormErrors {
  code?: string;
  name?: string;
  prefix?: string;
  padding?: string;
}

/** Nilai awal form create (padding = default backend). */
export const EMPTY_CREATE_SEQUENCE_FORM: CreateSequenceFormValues = {
  code: '',
  name: '',
  prefix: '',
  padding: String(DEFAULT_SEQUENCE_PADDING),
};

/**
 * Validasi form create → error per field.
 *
 * Cermin `validate_new_sequence_payload()` backend: kode `^[A-Z0-9]{2,16}$`,
 * nama wajib ≤64, prefix opsional `^[A-Z0-9-]{1,16}$`, padding 1..10.
 */
export function validateCreateSequenceForm(
  values: CreateSequenceFormValues,
): CreateSequenceFormErrors {
  const errors: CreateSequenceFormErrors = {};

  const code = values.code.trim().toUpperCase();
  if (!code) {
    errors.code = 'Kode wajib diisi.';
  } else if (!SEQUENCE_CODE_PATTERN.test(code)) {
    errors.code = `Kode hanya A-Z dan 0-9, ${MIN_SEQUENCE_CODE_LENGTH}-${MAX_SEQUENCE_CODE_LENGTH} karakter.`;
  }

  const name = values.name.trim();
  if (!name) {
    errors.name = 'Nama wajib diisi.';
  } else if (name.length > MAX_SEQUENCE_NAME_LENGTH) {
    errors.name = `Nama maksimal ${MAX_SEQUENCE_NAME_LENGTH} karakter.`;
  }

  const prefix = values.prefix.trim().toUpperCase();
  if (prefix !== '' && !SEQUENCE_PREFIX_PATTERN.test(prefix)) {
    errors.prefix = `Prefix hanya A-Z, 0-9, dan '-' (1-${MAX_SEQUENCE_PREFIX_LENGTH} karakter).`;
  }

  const padding = Number(values.padding);
  if (values.padding.trim() === '' || !Number.isInteger(padding)) {
    errors.padding = 'Padding harus angka bulat.';
  } else if (padding < MIN_SEQUENCE_PADDING || padding > MAX_SEQUENCE_PADDING) {
    errors.padding = `Padding harus antara ${MIN_SEQUENCE_PADDING} dan ${MAX_SEQUENCE_PADDING}.`;
  }

  return errors;
}

/** PURE — form create → body `POST` (prefix kosong = pakai kode di backend). */
export function createSequenceInputFromForm(
  values: CreateSequenceFormValues,
): MasterSequenceCreateInput {
  const prefix = values.prefix.trim().toUpperCase();
  const input: MasterSequenceCreateInput = {
    code: values.code.trim().toUpperCase(),
    name: values.name.trim(),
    padding: Number(values.padding),
  };
  if (prefix !== '') input.prefix = prefix;

  return input;
}
