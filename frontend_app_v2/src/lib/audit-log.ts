/**
 * audit-log.ts — logic PURE halaman Audit Log Viewer (H5.5).
 *
 * Dipisah dari halaman supaya bisa diuji TANPA DOM (jsdom tidak jalan di bun —
 * `.clinerules` §ENVIRONMENT): validasi filter, label baris, entries untuk modal
 * detail, dan pemetaan warna badge.
 *
 * Cermin `core/audit/services.py` (backend): `result` hanya ``OK|FAILED|CONFLICT|
 * DENIED``; `date_from`/`date_to` = ``YYYY-MM-DD``; `search` maksimal 100 karakter.
 */
import type { SelectOption } from '@/components/atoms/Select';
import type { BadgeTone } from '@/components/atoms/Badge';
import type { AuditLogDetail, AuditLogFilters, AuditLogRow } from '@/types/audit-log';
import { AUDIT_RESULTS } from '@/types/audit-log';

/** Batas panjang `?search` (sama dengan backend `MAX_SEARCH_LENGTH`). */
export const AUDIT_SEARCH_MAX = 100;

/** Opsi dropdown `result` (+ opsi kosong = semua). */
export const RESULT_OPTIONS: SelectOption[] = [
  { value: '', label: 'Semua hasil' },
  ...AUDIT_RESULTS.map((result) => ({ value: result, label: result })),
];

/** PURE — warna badge per `result` (OK = blue, gagal/konflik = coral, ditolak = muted). */
export function auditResultTone(result: string): BadgeTone {
  switch (result.trim().toUpperCase()) {
    case 'OK':
      return 'blue';
    case 'FAILED':
    case 'CONFLICT':
      return 'coral';
    case 'DENIED':
      return 'muted';
    default:
      return 'default';
  }
}

/** PURE — „—" untuk nilai kosong (null/undefined/string kosong). */
export function dash(value: string | null | undefined): string {
  if (value === null || value === undefined || value.trim() === '') return '—';

  return value;
}

/** PURE — ISO-8601 → `YYYY-MM-DD HH:MM` („—" kalau kosong/tak bisa diparse). */
export function formatAuditTimestamp(value: string | null): string {
  if (value === null || value.trim() === '') return '—';

  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return '—';

  const pad = (input: number): string => String(input).padStart(2, '0');

  return (
    `${String(parsed.getFullYear())}-${pad(parsed.getMonth() + 1)}-${pad(parsed.getDate())}` +
    ` ${pad(parsed.getHours())}:${pad(parsed.getMinutes())}`
  );
}

/** PURE — label pelaku: nama lengkap → username → „sistem" (user NULL). */
export function actorLabel(row: AuditLogRow): string {
  if (row.full_name.trim() !== '') return row.full_name;
  if (row.username !== null && row.username.trim() !== '') return row.username;

  return 'sistem';
}

/** PURE — ringkasan metadata kolom daftar („—" kalau kosong). */
export function metadataSummary(row: AuditLogRow): string {
  return dash(row.metadata_preview);
}

/** PURE — True kalau ada filter aktif (dipakai tombol „Bersihkan"). */
export function hasActiveFilters(filters: AuditLogFilters): boolean {
  return Object.values(filters).some((value) => value.trim() !== '');
}

/** PURE — `YYYY-MM-DD` yang benar-benar ada di kalender. */
export function isIsoDate(value: string): boolean {
  const text = value.trim();
  if (!/^\d{4}-\d{2}-\d{2}$/.test(text)) return false;

  const [year, month, day] = text.split('-').map((part) => Number(part));
  const parsed = new Date(year, month - 1, day);

  return (
    parsed.getFullYear() === year &&
    parsed.getMonth() === month - 1 &&
    parsed.getDate() === day
  );
}

/** Pesan error per field filter (kosong = valid). */
export type AuditFilterErrors = Partial<Record<keyof AuditLogFilters, string>>;

/** Validasi filter → error per field (cermin `filter_audit_logs` backend). */
export function validateAuditFilters(filters: AuditLogFilters): AuditFilterErrors {
  const errors: AuditFilterErrors = {};

  const userId = filters.user_id.trim();
  if (userId !== '') {
    const parsed = Number(userId);

    if (!Number.isInteger(parsed) || parsed < 1) {
      errors.user_id = 'User ID harus angka bulat ≥ 1 (atau dikosongkan).';
    }
  }

  const result = filters.result.trim();
  if (
    result !== '' &&
    !(AUDIT_RESULTS as readonly string[]).includes(result.toUpperCase())
  ) {
    errors.result = `Hasil harus salah satu dari ${AUDIT_RESULTS.join(', ')}.`;
  }

  if (filters.date_from.trim() !== '' && !isIsoDate(filters.date_from)) {
    errors.date_from = 'Tanggal "dari" harus format YYYY-MM-DD.';
  }
  if (filters.date_to.trim() !== '' && !isIsoDate(filters.date_to)) {
    errors.date_to = 'Tanggal "sampai" harus format YYYY-MM-DD.';
  }
  if (filters.search.trim().length > AUDIT_SEARCH_MAX) {
    errors.search = `Kata kunci maksimal ${String(AUDIT_SEARCH_MAX)} karakter.`;
  }

  return errors;
}

/** PURE — filter valid (tak ada error). */
export function isAuditFiltersValid(errors: AuditFilterErrors): boolean {
  return Object.keys(errors).length === 0;
}

/** Satu baris `{label, value}` di modal detail (urutan tetap, siap dirender). */
export interface AuditDetailEntry {
  label: string;
  value: string;
  mono: boolean;
}

/** PURE — objek JSON → teks rapi (indent 2) untuk modal detail (kosong = „—"). */
export function formatJsonBlock(value: Record<string, unknown>): string {
  if (Object.keys(value).length === 0) return '—';

  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return '—';
  }
}

/** PURE — detail audit → daftar entry modal (payload/metadata = blok JSON). */
export function auditDetailEntries(detail: AuditLogDetail): AuditDetailEntry[] {
  return [
    { label: 'Waktu', value: formatAuditTimestamp(detail.timestamp), mono: true },
    { label: 'Pelaku', value: actorLabel(detail), mono: false },
    { label: 'Aksi', value: dash(detail.action), mono: true },
    { label: 'Resource', value: dash(detail.resource), mono: true },
    { label: 'Resource ID', value: dash(detail.resource_id), mono: true },
    { label: 'Hasil', value: dash(detail.result), mono: false },
    { label: 'Request ID', value: dash(detail.request_id), mono: true },
    { label: 'IP', value: dash(detail.ip_address), mono: true },
    { label: 'User agent', value: dash(detail.user_agent), mono: true },
    { label: 'Payload', value: formatJsonBlock(detail.payload), mono: true },
    { label: 'Metadata', value: formatJsonBlock(detail.metadata), mono: true },
  ];
}

