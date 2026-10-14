import type { CsvColumn } from '@/hooks/use-csv-export';
import type { Role, User } from '@/types/settings';

/**
 * user-admin.ts — logika PURE halaman `/settings/users` (F6.3).
 *
 * Isi: kolom "Kode Operator" (siapa yang punya kode), filter role, seleksi baris +
 * aksi massal, dan definisi kolom CSV. Komponen halaman hanya merender + memanggil
 * fungsi di sini (pola repo: `lib/login-form.ts`, `lib/action-runner.ts`).
 *
 * Aturan yang dipegang:
 *  - kode operator HANYA untuk role OPERATOR/QC (invariant backend F6.1) → role lain
 *    menampilkan `—` dan tombol Regenerate tidak dirender;
 *  - aksi massal "Regenerate" hanya masuk akal kalau ada ≥1 user operator/QC terpilih;
 *    "Aktifkan"/"Nonaktifkan" dilewati untuk baris yang statusnya sudah sesuai.
 */

/** Role yang boleh punya `operator_code` (UPPERCASE di backend: OPERATOR/QC). */
export const OPERATOR_CODE_ROLES: readonly Role[] = ['operator', 'qc'];

/** Placeholder kolom kode untuk role yang tidak punya kode. */
export const EMPTY_CODE_LABEL = '—';

/** Dropdown filter role: `''` = semua role (nilai dikirim ke `?role=` karena sama). */
export const ROLE_FILTER_ALL = '';

export interface RoleFilterOption {
  value: string;
  label: string;
}

/** Opsi dropdown filter role (urutan tetap sesuai brief). */
export const ROLE_FILTER_OPTIONS: RoleFilterOption[] = [
  { value: ROLE_FILTER_ALL, label: 'All' },
  { value: 'operator', label: 'Operator' },
  { value: 'qc', label: 'QC' },
  { value: 'supervisor', label: 'Supervisor' },
  { value: 'admin', label: 'Admin' },
  { value: 'owner', label: 'Owner' },
];

export type BulkActionId = 'regenerate' | 'activate' | 'deactivate';

export interface BulkActionOption {
  value: string;
  label: string;
}

/** Dropdown aksi massal (`''` = belum memilih apa pun). */
export const BULK_ACTION_OPTIONS: BulkActionOption[] = [
  { value: '', label: 'Aksi massal…' },
  { value: 'regenerate', label: 'Regenerate Kode' },
  { value: 'activate', label: 'Aktifkan' },
  { value: 'deactivate', label: 'Nonaktifkan' },
];

/** PURE — sempitkan `string` dari <select> ke `BulkActionId` TANPA cast `as`. */
export function isBulkActionId(value: string): value is BulkActionId {
  return value === 'regenerate' || value === 'activate' || value === 'deactivate';
}

/** PURE — true kalau role ini boleh punya kode operator. */
export function hasOperatorCodeRole(role: Role): boolean {
  return OPERATOR_CODE_ROLES.some((candidate) => candidate === role);
}

/** PURE — teks kolom kode: kode (4/6 digit) atau `—` untuk role lain / kode kosong. */
export function operatorCodeLabel(role: Role, code: string | null | undefined): string {
  if (!hasOperatorCodeRole(role)) return EMPTY_CODE_LABEL;

  const value = (code ?? '').trim();

  return value.length > 0 ? value : EMPTY_CODE_LABEL;
}

/** PURE — filter baris per role (`''`/`all` = semua). */
export function filterUsersByRole(users: readonly User[], roleFilter: string): User[] {
  const wanted = roleFilter.trim().toLowerCase();
  if (wanted === '' || wanted === 'all') return [...users];

  return users.filter((user) => user.role === wanted);
}

/** PURE — ubah himpunan id terpilih (checkbox baris); `checked=false` = buang. */
export function toggleSelection(
  selected: ReadonlySet<number>,
  id: number,
  checked: boolean,
): Set<number> {
  const next = new Set(selected);

  if (checked) next.add(id);
  else next.delete(id);

  return next;
}

/** PURE — baris yang terpilih (urut seperti daftar sumber). */
export function selectedRows(users: readonly User[], selected: ReadonlySet<number>): User[] {
  return users.filter((user) => selected.has(user.id));
}

/** PURE — true kalau aksi massal "Regenerate Kode" bisa dijalankan untuk pilihan ini. */
export function canRegenerateSelection(users: readonly User[]): boolean {
  return users.some((user) => hasOperatorCodeRole(user.role));
}

/** PURE — baris yang BENAR-BENAR berubah untuk aksi aktif/nonaktif (sisanya dilewati). */
export function rowsForBulkAction(users: readonly User[], action: BulkActionId): User[] {
  if (action === 'activate') return users.filter((user) => !user.active);
  if (action === 'deactivate') return users.filter((user) => user.active);

  return users.filter((user) => hasOperatorCodeRole(user.role));
}

/** PURE — label status untuk CSV (badge UI memakai teks yang sama). */
export function csvStatusLabel(active: boolean): string {
  return active ? 'Aktif' : 'Nonaktif';
}

/** Kolom CSV export daftar user (header manusiawi, bukan nama field). */
export function userCsvColumns(): CsvColumn<Record<string, string>>[] {
  return [
    { key: 'username', label: 'Username' },
    { key: 'full_name', label: 'Nama Lengkap' },
    { key: 'email', label: 'Email' },
    { key: 'role', label: 'Role' },
    { key: 'operator_code', label: 'Kode Operator' },
    { key: 'active', label: 'Status' },
  ];
}

/**
 * PURE — nilai kolom CSV per baris (`userCsvColumns()` memakai key mentah, jadi kolom
 * yang butuh teks manusiawi — kode & status — disiapkan di sini).
 */
export function userCsvRow(user: User): Record<string, string> {
  return {
    username: user.username,
    full_name: user.full_name,
    email: (user.email ?? '').trim(),
    role: user.role,
    operator_code: operatorCodeLabel(user.role, user.operator_code),
    active: csvStatusLabel(user.active),
  };
}

/** Baris siap-CSV (kolom sudah dirapikan untuk Excel). */
export function usersCsvRows(users: readonly User[]): Record<string, string>[] {
  return users.map(userCsvRow);
}
