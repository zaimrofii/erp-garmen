import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { buildCsv } from '@/hooks/use-csv-export';
import {
  BULK_ACTION_OPTIONS,
  canRegenerateSelection,
  csvStatusLabel,
  EMPTY_CODE_LABEL,
  filterUsersByRole,
  hasOperatorCodeRole,
  isBulkActionId,
  operatorCodeLabel,
  ROLE_FILTER_ALL,
  ROLE_FILTER_OPTIONS,
  rowsForBulkAction,
  selectedRows,
  toggleSelection,
  userCsvColumns,
  usersCsvRows,
} from '@/lib/user-admin';
import type { Role, User } from '@/types/settings';

/**
 * F6.3 — halaman `/settings/users`: kolom Kode Operator, filter role, aksi massal, CSV.
 *
 * Bagian logika diuji langsung (PURE, `lib/user-admin.ts`); bagian halaman yang ber-hook
 * (query/mutation/modal) diverifikasi lewat pemeriksaan sumber — pola yang sama dipakai
 * `tests/unit/pages/devices-page.test.ts` (tanpa DOM/jsdom).
 */

const ROOT = path.resolve(import.meta.dirname, '../../..');
const PAGE = readFileSync(
  path.join(ROOT, 'src/pages/settings/UserManagementPage.tsx'),
  'utf8',
);

function user(overrides: Partial<User> & { id: number }): User {
  const role: Role = overrides.role ?? 'operator';

  return {
    username: `user-${overrides.id}`,
    full_name: `User ${overrides.id}`,
    role,
    active: true,
    email: `user${overrides.id}@klien.com`,
    operator_code: hasOperatorCodeRole(role) ? '4821' : null,
    ...overrides,
  };
}

const ROWS: User[] = [
  user({ id: 1, role: 'operator', active: true, operator_code: '4821' }),
  user({ id: 2, role: 'qc', active: false, operator_code: '7390' }),
  user({ id: 3, role: 'admin', active: true, operator_code: null }),
  user({ id: 4, role: 'supervisor', active: false, operator_code: null }),
];

describe('F6.3 — kolom Kode Operator (pure)', () => {
  it('hasOperatorCodeRole: hanya operator & qc', () => {
    expect(hasOperatorCodeRole('operator')).toBe(true);
    expect(hasOperatorCodeRole('qc')).toBe(true);
    expect(hasOperatorCodeRole('supervisor')).toBe(false);
    expect(hasOperatorCodeRole('admin')).toBe(false);
    expect(hasOperatorCodeRole('owner')).toBe(false);
  });

  it('operatorCodeLabel: kode untuk operator/qc, "—" untuk role lain atau kode kosong', () => {
    expect(operatorCodeLabel('operator', '4821')).toBe('4821');
    expect(operatorCodeLabel('qc', ' 7390 ')).toBe('7390');
    expect(operatorCodeLabel('operator', null)).toBe(EMPTY_CODE_LABEL);
    expect(operatorCodeLabel('operator', '')).toBe(EMPTY_CODE_LABEL);
    // invariant backend: role lain tidak punya kode — walau datanya ada, UI menampilkan "—"
    expect(operatorCodeLabel('admin', '1234')).toBe(EMPTY_CODE_LABEL);
  });
});

describe('F6.3 — filter role (pure)', () => {
  it('opsi filter sesuai brief (All + 5 role)', () => {
    expect(ROLE_FILTER_OPTIONS.map((option) => option.label)).toEqual([
      'All',
      'Operator',
      'QC',
      'Supervisor',
      'Admin',
      'Owner',
    ]);
    expect(ROLE_FILTER_OPTIONS[0].value).toBe(ROLE_FILTER_ALL);
  });

  it('filterUsersByRole: "" / "all" → semua; selain itu hanya role tsb', () => {
    expect(filterUsersByRole(ROWS, '')).toHaveLength(4);
    expect(filterUsersByRole(ROWS, 'all').map((row) => row.id)).toEqual([1, 2, 3, 4]);
    expect(filterUsersByRole(ROWS, 'operator').map((row) => row.id)).toEqual([1]);
    expect(filterUsersByRole(ROWS, 'qc').map((row) => row.id)).toEqual([2]);
    expect(filterUsersByRole(ROWS, 'owner')).toEqual([]);
    // tidak memutasi daftar sumber
    expect(ROWS).toHaveLength(4);
  });
});

describe('F6.3 — seleksi baris & aksi massal (pure)', () => {
  it('toggleSelection menambah/membuang id tanpa memutasi himpunan lama', () => {
    const first = toggleSelection(new Set<number>(), 1, true);
    const second = toggleSelection(first, 2, true);
    const third = toggleSelection(second, 1, false);

    expect([...first]).toEqual([1]);
    expect([...second]).toEqual([1, 2]);
    expect([...third]).toEqual([2]);
    expect([...second]).toEqual([1, 2]);
  });

  it('selectedRows mengikuti urutan daftar sumber', () => {
    expect(selectedRows(ROWS, new Set([3, 1])).map((row) => row.id)).toEqual([1, 3]);
    expect(selectedRows(ROWS, new Set())).toEqual([]);
  });

  it('rowsForBulkAction: aktif/nonaktif hanya baris yang berubah, regenerate hanya operator/qc', () => {
    expect(rowsForBulkAction(ROWS, 'activate').map((row) => row.id)).toEqual([2, 4]);
    expect(rowsForBulkAction(ROWS, 'deactivate').map((row) => row.id)).toEqual([1, 3]);
    expect(rowsForBulkAction(ROWS, 'regenerate').map((row) => row.id)).toEqual([1, 2]);
  });

  it('canRegenerateSelection: false kalau tidak ada baris operator/qc', () => {
    expect(canRegenerateSelection(ROWS)).toBe(true);
    expect(canRegenerateSelection([ROWS[2]!, ROWS[3]!])).toBe(false);
    expect(canRegenerateSelection([])).toBe(false);
  });

  it('isBulkActionId menyempitkan string dari <select>', () => {
    expect(isBulkActionId('regenerate')).toBe(true);
    expect(isBulkActionId('activate')).toBe(true);
    expect(isBulkActionId('deactivate')).toBe(true);
    expect(isBulkActionId('')).toBe(false);
    expect(isBulkActionId('hapus-semua')).toBe(false);
  });

  it('BULK_ACTION_OPTIONS memuat 3 aksi massal + placeholder', () => {
    expect(BULK_ACTION_OPTIONS.map((option) => option.value)).toEqual([
      '',
      'regenerate',
      'activate',
      'deactivate',
    ]);
  });
});

describe('F6.3 — Export CSV (pure)', () => {
  it('csvStatusLabel + kolom CSV manusiawi', () => {
    expect(csvStatusLabel(true)).toBe('Aktif');
    expect(csvStatusLabel(false)).toBe('Nonaktif');
    expect(userCsvColumns().map((column) => column.label)).toEqual([
      'Username',
      'Nama Lengkap',
      'Email',
      'Role',
      'Kode Operator',
      'Status',
    ]);
  });

  it('usersCsvRows: kode "—" untuk role lain + status teks, siap `buildCsv`', () => {
    const rows = usersCsvRows(ROWS);
    const csv = buildCsv(rows, userCsvColumns());
    const lines = csv.split('\n');

    expect(rows[0]).toMatchObject({ operator_code: '4821', active: 'Aktif', role: 'operator' });
    expect(rows[2]).toMatchObject({ operator_code: EMPTY_CODE_LABEL, role: 'admin' });
    expect(lines).toHaveLength(ROWS.length + 1);
    expect(lines[0]).toContain('Kode Operator');
    expect(lines[1]).toContain('4821');
    expect(lines[3]).toContain(EMPTY_CODE_LABEL);
  });
});

describe('F6.3 — wiring halaman UserManagementPage', () => {
  it('kolom & tombol memakai helper pure (bukan logika inline)', () => {
    expect(PAGE).toContain("label: 'Kode Operator'");
    expect(PAGE).toContain('operatorCodeLabel(row.role, row.operator_code)');
    expect(PAGE).toContain('hasOperatorCodeRole(row.role)');
    expect(PAGE).toContain('setConfirmRegenerate([row])');
  });

  it('regenerate lewat PUT yang sudah ada (tanpa endpoint generate-code)', () => {
    expect(PAGE).toContain('regenerateOperatorCode(client, user.id, userInputFromRow(user))');
    expect(PAGE).not.toContain('/generate-code');
    expect(PAGE).toContain(
      "bulk.mutate({ action: 'regenerate', users: rowsForBulkAction(users, 'regenerate') })",
    );
  });

  it('konfirmasi regenerate: modal + guard canRegenerateSelection', () => {
    expect(PAGE).toContain('title="Regenerate Kode Operator?"');
    expect(PAGE).toContain('canRegenerateSelection(users)');
    expect(PAGE).toContain('data-regenerate-count');
    expect(PAGE).toContain('runRegenerate');
  });

  it('filter role + aksi massal terpasang di toolbar', () => {
    expect(PAGE).toContain('options={ROLE_FILTER_OPTIONS}');
    expect(PAGE).toContain('handleRoleFilter(event.target.value)');
    expect(PAGE).toContain('options={BULK_ACTION_OPTIONS}');
    expect(PAGE).toContain('handleBulkAction(event.target.value)');
    expect(PAGE).toContain('data-selected-count={picked.length}');
  });

  it('checkbox per baris + Export CSV terpasang', () => {
    expect(PAGE).toContain('checked={selected.has(row.id)}');
    expect(PAGE).toContain('toggleSelection(current, row.id, checked)');
    expect(PAGE).toContain('onExport={handleExport}');
    expect(PAGE).toContain("exportCsv(usersCsvRows(source), 'users.csv', userCsvColumns())");
  });

  it('Cetak Badge ditunda ke F7: TANPA tombol mati, ada TODO eksplisit', () => {
    // tidak ada adapter/fungsi cetak badge yang dipanggil (endpoint belum ada)
    expect(PAGE).not.toContain('printBadge');
    expect(PAGE).toContain('// TODO F7: cetak badge ESC/POS');
    expect(PAGE).toContain('PrintJob.Resource.BADGE');
    // alasan penundaan tercatat di sumber (keputusan Opsi C)
    expect(PAGE).toContain('F6.3-CLOSE');
  });
});

