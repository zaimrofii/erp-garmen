import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { KeyRound, Pencil, Plus } from 'lucide-react';
import { Badge, type BadgeTone } from '@/components/atoms/Badge';
import { Button } from '@/components/atoms/Button';
import { Checkbox } from '@/components/atoms/Checkbox';
import { Input } from '@/components/atoms/Input';
import { Modal } from '@/components/atoms/Modal';
import { Select, type SelectOption } from '@/components/atoms/Select';
import { Toast, type ToastTone } from '@/components/atoms/Toast';
import { DenseTable, type DenseTableColumn } from '@/components/molecules/DenseTable';
import { FormField } from '@/components/molecules/FormField';
import { PageHeader } from '@/components/molecules/PageHeader';
import { PaginationBar } from '@/components/molecules/PaginationBar';
import { TableToolbar } from '@/components/molecules/TableToolbar';
import { fetchRoles } from '@/api/roles';
import {
  createUser,
  deleteUser,
  fetchUsers,
  regenerateOperatorCode,
  updateUser,
  userInputFromRow,
} from '@/api/settings';
import { useFeedback } from '@/app/app-runtime';
import { useApiClient } from '@/hooks/useApiClient';
import { useCsvExport } from '@/hooks/use-csv-export';
import { usePagination } from '@/hooks/use-pagination';
import { cn } from '@/lib/cn';
import {
  BULK_ACTION_OPTIONS,
  canRegenerateSelection,
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
  type BulkActionId,
} from '@/lib/user-admin';
import { CARD, PILL_PRIMARY } from '@/lib/tokens';
import type { Role, User } from '@/types/settings';
import type { SettingsUserInput } from '@/api/settings';

/**
 * UserManagementPage - route `/settings/users` (khusus admin).
 *
 * REAL sejak F5.4.CLOSE (backend B26, admin/owner):
 *   * list  → `GET /settings/users/` (`fetchUsers`);
 *   * tambah→ `POST /settings/users/` (`createUser`, butuh password ≥ 8 karakter);
 *   * edit  → `PUT /settings/users/<id>/` (`updateUser`, password kosong = tidak diubah);
 *   * nonaktif → `DELETE /settings/users/<id>/` (`deleteUser` = **soft delete**,
 *     jadi user nonaktif tetap terlihat di tabel dengan badge "Nonaktif").
 *
 * Backend memakai kode role UPPERCASE; adapter `api/settings.ts` yang menerjemahkan
 * ke union `Role` lowercase (lihat `real/settingsUsers.ts`).
 *
 * F6.3 (operator badge):
 *   * kolom **Kode Operator** (4/6 digit) + tombol **Regenerate** per baris
 *     (dengan konfirmasi) — kode `—` untuk role selain OPERATOR/QC;
 *   * **filter role** (All/Operator/QC/Supervisor/Admin/Owner) — filter klien-side
 *     lewat `lib/user-admin.ts` (daftar user admin jumlahnya kecil, satu query cukup);
 *   * **aksi massal**: checkbox per baris + dropdown Regenerate Kode / Aktifkan /
 *     Nonaktifkan (satu request per baris, ringkasan hasil di Toast);
 *   * **Export CSV** (baris terpilih, atau seluruh hasil filter bila tidak ada pilihan).
 *
 * Regenerate memakai endpoint yang SUDAH ADA (Opsi B): `PUT /settings/users/<id>/`
 * dengan `operator_code: ""` → backend mengundi kode unik baru (`User.save()` F6.1).
 * **Cetak Badge DITUNDA** (F6.3-CLOSE, Opsi C): butuh endpoint `/print/badge/` +
 * `PrintJob.Resource.BADGE` (1 migration) → ditandai `TODO F7` di dalam JSX dan
 * didokumentasikan di `django_app/docs/known-limitations.md` (§2 Frontend, F7).
 */

const EMPTY_USERS: User[] = [];

const ROLE_TONE: Record<Role, BadgeTone> = {
  operator: 'muted',
  supervisor: 'blue',
  qc: 'blue',
  admin: 'coral',
  inventory: 'blue',
  purchasing: 'blue',
  owner: 'coral',
};

const ROLE_LABEL: Record<Role, string> = {
  operator: 'Operator',
  supervisor: 'Supervisor',
  qc: 'QC',
  admin: 'Admin',
  inventory: 'Inventory',
  purchasing: 'Purchasing',
  owner: 'Owner',
};

const DEFAULT_ROLE: Role = 'operator';

/** Panjang password minimum backend B26 (`MIN_PASSWORD_LENGTH` di `settings/views.py`). */
const MIN_PASSWORD_LENGTH = 8;

const ROLE_VALUES: Role[] = [
  'operator',
  'supervisor',
  'qc',
  'admin',
  'inventory',
  'purchasing',
  'owner',
];

const ROLE_SET: ReadonlySet<string> = new Set<string>(ROLE_VALUES);

/** PURE - menyempitkan `string` dari <select> ke `Role` TANPA cast `as`. */
function isRole(value: string): value is Role {
  return ROLE_SET.has(value);
}

interface ToastState {
  title: string;
  description: string;
  tone: ToastTone;
}

export function UserManagementPage() {
  const queryClient = useQueryClient();
  const feedback = useFeedback();

  const [search, setSearch] = useState('');
  const [formOpen, setFormOpen] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [fullName, setFullName] = useState('');
  const [roleText, setRoleText] = useState<string>(DEFAULT_ROLE);
  const [active, setActive] = useState(true);
  const [errorText, setErrorText] = useState<string | null>(null);
  const [toast, setToast] = useState<ToastState | null>(null);

  // F6.3 — filter role, seleksi baris (checkbox), aksi massal, & konfirmasi regenerate.
  const [roleFilter, setRoleFilter] = useState<string>(ROLE_FILTER_ALL);
  const [selected, setSelected] = useState<ReadonlySet<number>>(() => new Set<number>());
  const [bulkActionText, setBulkActionText] = useState('');
  const [confirmRegenerate, setConfirmRegenerate] = useState<User[] | null>(null);

  const client = useApiClient();
  const { exportCsv } = useCsvExport();

  const users = useQuery({
    queryKey: ['settings-users'],
    queryFn: () => fetchUsers(client),
    staleTime: 30_000,
  });

  const roles = useQuery({
    queryKey: ['roles'],
    queryFn: () => fetchRoles(client),
    staleTime: 60_000,
  });

  const rows = users.data ?? EMPTY_USERS;

  const roleOptions: SelectOption[] = useMemo(
    () => (roles.data ?? []).map((item) => ({ value: item, label: ROLE_LABEL[item] })),
    [roles.data],
  );

  const filtered = useMemo(() => {
    const byRole = filterUsersByRole(rows, roleFilter);
    const needle = search.trim().toLowerCase();
    if (needle.length === 0) return byRole;

    return byRole.filter(
      (row) =>
        row.username.toLowerCase().includes(needle) ||
        row.full_name.toLowerCase().includes(needle) ||
        row.role.toLowerCase().includes(needle),
    );
  }, [rows, roleFilter, search]);

  /** Baris yang dicentang (lintas halaman) — dipakai aksi massal & Export CSV. */
  const picked = useMemo(() => selectedRows(rows, selected), [rows, selected]);

  const pagination = usePagination(filtered, { pageSize: 20 });

  /** Buat (POST) atau ubah (PUT) user — satu mutation, dibedakan `vars.id`. */
  const save = useMutation({
    mutationFn: (vars: { id: number | null; input: SettingsUserInput }) =>
      vars.id === null ? createUser(client, vars.input) : updateUser(client, vars.id, vars.input),
    onSuccess: (saved, variables) => {
      feedback.trigger('success');
      setToast({
        title: variables.id === null ? 'User ditambahkan' : 'User diperbarui',
        description: `${saved.username} disimpan sebagai ${ROLE_LABEL[saved.role]}.`,
        tone: 'success',
      });
      setFormOpen(false);
      void queryClient.invalidateQueries({ queryKey: ['settings-users'] });
    },
    onError: (error: Error) => {
      feedback.trigger('error');
      setToast({
        title: 'Gagal menyimpan user',
        description: error.message,
        tone: 'error',
      });
    },
  });

  /** Nonaktifkan user (DELETE = soft delete; user tetap ada dengan `is_active=false`). */
  const deactivate = useMutation({
    mutationFn: (id: number) => deleteUser(client, id),
    onSuccess: () => {
      feedback.trigger('success');
      setToast({
        title: 'User dinonaktifkan',
        description: 'DELETE /settings/users/<id>/ (soft delete - baris tetap tersimpan).',
        tone: 'success',
      });
      void queryClient.invalidateQueries({ queryKey: ['settings-users'] });
    },
    onError: (error: Error) => {
      feedback.trigger('error');
      setToast({
        title: 'Gagal menonaktifkan user',
        description: error.message,
        tone: 'error',
      });
    },
  });

  /**
   * Aksi massal (F6.3): satu request PER baris (endpoint B26 tidak punya bulk),
   * kegagalan dicatat lalu diringkas di Toast supaya user tahu baris mana yang gagal.
   *   * `regenerate` → `PUT /settings/users/<id>/` dengan `operator_code: ""`;
   *   * `activate`   → `PUT` dengan `is_active: true` (butuh email terisi);
   *   * `deactivate` → `DELETE` (soft delete).
   */
  const bulk = useMutation({
    mutationFn: async (vars: { action: BulkActionId; users: User[] }) => {
      let done = 0;
      const errors: string[] = [];

      for (const user of vars.users) {
        const mail = (user.email ?? '').trim();

        try {
          if (vars.action === 'deactivate') {
            await deleteUser(client, user.id);
          } else if (vars.action === 'regenerate') {
            await regenerateOperatorCode(client, user.id, userInputFromRow(user));
          } else if (mail.length === 0) {
            errors.push(`${user.username}: email belum diisi`);
            continue;
          } else {
            await updateUser(client, user.id, { ...userInputFromRow(user), active: true });
          }

          done += 1;
        } catch (caught) {
          errors.push(`${user.username}: ${caught instanceof Error ? caught.message : 'gagal'}`);
        }
      }

      return { done, errors };
    },
    onSuccess: ({ done, errors }) => {
      if (done > 0) feedback.trigger('success');
      if (errors.length > 0) feedback.trigger('error');

      setToast({
        title: errors.length === 0 ? 'Aksi massal selesai' : 'Aksi massal selesai dengan catatan',
        description:
          errors.length === 0
            ? `${done} user diproses.`
            : `${done} user diproses, ${errors.length} gagal → ${errors.slice(0, 3).join('; ')}`,
        tone: errors.length === 0 ? 'success' : 'error',
      });
      setConfirmRegenerate(null);
      setSelected(new Set<number>());
      void queryClient.invalidateQueries({ queryKey: ['settings-users'] });
    },
    onError: (error: Error) => {
      feedback.trigger('error');
      setToast({ title: 'Aksi massal gagal', description: error.message, tone: 'error' });
    },
  });

  const busy = save.isPending || deactivate.isPending || bulk.isPending;

  function openAdd(): void {
    setEditingId(null);
    setUsername('');
    setEmail('');
    setPassword('');
    setFullName('');
    setRoleText(DEFAULT_ROLE);
    setActive(true);
    setErrorText(null);
    setFormOpen(true);
  }

  function openEdit(user: User): void {
    setEditingId(user.id);
    setUsername(user.username);
    setEmail(user.email ?? '');
    setPassword('');
    setFullName(user.full_name);
    setRoleText(user.role);
    setActive(user.active);
    setErrorText(null);
    setFormOpen(true);
  }

  function handleSubmit(): void {
    const name = username.trim();
    const mail = email.trim();
    const displayName = fullName.trim();
    const isCreate = editingId === null;

    if (name.length === 0) {
      setErrorText('Username wajib diisi.');
      feedback.trigger('error');
      return;
    }

    if (mail.length === 0) {
      setErrorText('Email wajib diisi.');
      feedback.trigger('error');
      return;
    }

    if (displayName.length === 0) {
      setErrorText('Nama lengkap wajib diisi.');
      feedback.trigger('error');
      return;
    }

    if (isCreate && password.length < MIN_PASSWORD_LENGTH) {
      setErrorText(`Password minimal ${MIN_PASSWORD_LENGTH} karakter.`);
      feedback.trigger('error');
      return;
    }

    setErrorText(null);
    save.mutate({
      id: editingId,
      input: {
        username: name,
        email: mail,
        password,
        full_name: displayName,
        role: isRole(roleText) ? roleText : DEFAULT_ROLE,
        active,
      },
    });
  }

  /** Aktif → nonaktif lewat DELETE (soft delete); nonaktif → aktif lewat PUT `is_active`. */
  function handleToggleActive(user: User): void {
    if (user.active) {
      deactivate.mutate(user.id);
      return;
    }

    const mail = (user.email ?? '').trim();
    if (mail.length === 0) {
      feedback.trigger('error');
      setToast({
        title: 'Email belum ada',
        description: 'Lengkapi email lewat tombol Edit sebelum mengaktifkan user ini.',
        tone: 'error',
      });
      return;
    }

    save.mutate({
      id: user.id,
      input: {
        username: user.username,
        email: mail,
        full_name: user.full_name,
        role: user.role,
        active: true,
      },
    });
  }

  function handleSearch(value: string): void {
    setSearch(value);
    pagination.reset();
  }

  /** F6.3 — filter role (klien-side) + reset halaman. */
  function handleRoleFilter(value: string): void {
    setRoleFilter(value);
    pagination.reset();
  }

  /** F6.3 — pilih aksi massal; "Regenerate Kode" minta konfirmasi dulu (kode lama hangus). */
  function handleBulkAction(value: string): void {
    setBulkActionText('');

    if (!isBulkActionId(value)) return;

    const targets = rowsForBulkAction(picked, value);

    if (targets.length === 0) {
      feedback.trigger('error');
      setToast({
        title: 'Tidak ada baris yang perlu diubah',
        description:
          value === 'regenerate'
            ? 'Pilih minimal satu user ber-role Operator/QC.'
            : value === 'activate'
              ? 'Semua baris terpilih sudah aktif.'
              : 'Semua baris terpilih sudah nonaktif.',
        tone: 'error',
      });
      return;
    }

    if (value === 'regenerate') {
      setConfirmRegenerate(targets);
      return;
    }

    bulk.mutate({ action: value, users: targets });
  }

  /** Export CSV: baris terpilih, atau seluruh hasil filter bila tidak ada pilihan. */
  function handleExport(): void {
    const source = picked.length > 0 ? picked : filtered;
    exportCsv(usersCsvRows(source), 'users.csv', userCsvColumns());
  }

  /** Konfirmasi regenerate: hanya baris operator/QC yang dikirim (guard ekstra). */
  function runRegenerate(): void {
    const users = confirmRegenerate ?? [];

    if (!canRegenerateSelection(users)) {
      feedback.trigger('error');
      setToast({
        title: 'Tidak ada kode yang bisa dibuat ulang',
        description: 'Hanya user ber-role Operator/QC yang punya kode operator.',
        tone: 'error',
      });
      setConfirmRegenerate(null);
      return;
    }

    bulk.mutate({ action: 'regenerate', users: rowsForBulkAction(users, 'regenerate') });
  }

  // TODO F7: cetak badge ESC/POS (`POST /print/badge/` + `PrintJob.Resource.BADGE`) —
  // ditunda oleh keputusan F6.3-CLOSE (Opsi C): butuh 1 migration + 2 endpoint baru,
  // sedangkan kolom Kode Operator + Regenerate sudah cukup untuk pilot. Tombol SENGAJA
  // tidak dirender (jangan ada tombol mati); penanda lokasi pemasangannya ada di JSX
  // bagian toolbar. Badge pilot dicetak manual di luar sistem.
  const columns: DenseTableColumn<User>[] = [
    {
      key: 'select',
      label: 'Pilih',
      render: (row) => (
        <Checkbox
          aria-label={`Pilih ${row.username}`}
          checked={selected.has(row.id)}
          onCheckedChange={(checked) =>
            setSelected((current) => toggleSelection(current, row.id, checked))
          }
        />
      ),
    },
    {
      key: 'username',
      label: 'Username',
      render: (row) => <span className="font-mono tabular-nums">{row.username}</span>,
    },
    {
      key: 'email',
      label: 'Email',
      render: (row) => <span className="text-xs text-muted-foreground">{row.email ?? '-'}</span>,
    },
    { key: 'full_name', label: 'Nama Lengkap' },
    {
      key: 'role',
      label: 'Role',
      render: (row) => <Badge tone={ROLE_TONE[row.role]}>{ROLE_LABEL[row.role]}</Badge>,
    },
    {
      // F6.3 — kode operator (4/6 digit) + Regenerate; role lain hanya "—".
      key: 'operator_code',
      label: 'Kode Operator',
      render: (row) => (
        <span className="flex items-center gap-2">
          <span className="font-mono text-sm tabular-nums">
            {operatorCodeLabel(row.role, row.operator_code)}
          </span>
          {hasOperatorCodeRole(row.role) ? (
            <Button
              variant="ghost"
              size="sm"
              icon={KeyRound}
              disabled={busy}
              onClick={() => setConfirmRegenerate([row])}
            >
              Regenerate
            </Button>
          ) : null}
        </span>
      ),
    },
    {
      key: 'active',
      label: 'Status',
      render: (row) => (
        <Badge tone={row.active ? 'blue' : 'muted'}>{row.active ? 'Aktif' : 'Nonaktif'}</Badge>
      ),
    },
    {
      key: 'actions',
      label: 'Aksi',
      align: 'right',
      render: (row) => (
        <span className="flex justify-end gap-2">
          <Button
            variant="secondary"
            size="sm"
            icon={Pencil}
            disabled={busy}
            onClick={() => openEdit(row)}
          >
            Edit
          </Button>
          <Button
            variant="ghost"
            size="sm"
            disabled={busy}
            onClick={() => handleToggleActive(row)}
          >
            {row.active ? 'Nonaktifkan' : 'Aktifkan'}
          </Button>
        </span>
      ),
    },
  ];

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <PageHeader
        title="Users"
        subtitle="Manajemen pengguna beserta role dan status aktifnya"
        breadcrumb={[{ label: 'Settings' }, { label: 'Users' }]}
        actions={
          <button
            type="button"
            className={cn(PILL_PRIMARY, 'gap-1.5 px-3 py-2 text-xs')}
            onClick={openAdd}
          >
            <Plus className="h-3.5 w-3.5" aria-hidden="true" />
            Tambah User
          </button>
        }
      />

      <TableToolbar
        search={search}
        onSearchChange={handleSearch}
        searchLabel="Cari user"
        searchPlaceholder="Cari username / nama / role"
        onExport={handleExport}
        exportDisabled={rows.length === 0}
        refreshing={users.isFetching}
        onRefresh={() => {
          void users.refetch();
        }}
      />

      {/* F6.3 — filter role + aksi massal (checkbox per baris di tabel). */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div className="w-full sm:w-56">
          <Select
            label="Filter role"
            value={roleFilter}
            options={ROLE_FILTER_OPTIONS}
            onChange={(event) => handleRoleFilter(event.target.value)}
          />
        </div>

        <div className="flex flex-wrap items-end gap-3">
          <div className="w-full sm:w-56">
            <Select
              label="Aksi massal"
              value={bulkActionText}
              options={BULK_ACTION_OPTIONS}
              disabled={busy}
              onChange={(event) => handleBulkAction(event.target.value)}
            />
          </div>
          <p
            className="pb-2 text-xs font-medium text-muted-foreground"
            data-selected-count={picked.length}
          >
            {picked.length} baris dipilih
          </p>
          {/* TODO F7: cetak badge ESC/POS (`POST /print/badge/` + nilai
              `PrintJob.Resource.BADGE`). Ditunda oleh keputusan F6.3-CLOSE (Opsi C):
              butuh 1 migration + 2 endpoint baru; kolom Kode Operator + Regenerate
              sudah cukup untuk pilot. Tombol sengaja TIDAK dirender supaya tidak ada
              tombol mati — badge pilot dicetak manual di luar sistem. */}
        </div>
      </div>

      <section className={cn(CARD, 'p-0')}>
        <DenseTable
          columns={columns}
          rows={pagination.pageRows}
          loading={users.isLoading}
          error={users.error === null ? null : 'Gagal memuat daftar user.'}
          onRetry={() => {
            void users.refetch();
          }}
          emptyMessage="Tidak ada user yang cocok."
        />
      </section>

      <PaginationBar
        page={pagination.page}
        totalPages={pagination.totalPages}
        rangeStart={pagination.rangeStart}
        rangeEnd={pagination.rangeEnd}
        total={pagination.total}
        canPrev={pagination.canPrev}
        canNext={pagination.canNext}
        onPrev={pagination.goPrev}
        onNext={pagination.goNext}
      />

      <Modal
        open={formOpen}
        onOpenChange={setFormOpen}
        title={editingId === null ? 'Tambah User' : 'Edit User'}
        description="Role menentukan menu dan halaman yang bisa diakses."
        footer={
          <>
            <Button variant="secondary" onClick={() => setFormOpen(false)}>
              Batal
            </Button>
            <Button variant="primary" loading={busy} onClick={handleSubmit}>
              {editingId === null ? 'Tambah' : 'Simpan'}
            </Button>
          </>
        }
      >
        <div className="flex flex-col gap-4">
          <FormField label="Username" htmlFor="user-name" required>
            <Input
              id="user-name"
              value={username}
              placeholder="mis. spv.lineb"
              onChange={(event) => setUsername(event.target.value)}
            />
          </FormField>

          <FormField label="Email" htmlFor="user-email" required>
            <Input
              id="user-email"
              type="email"
              value={email}
              placeholder="mis. spv.lineb@garment.local"
              onChange={(event) => setEmail(event.target.value)}
            />
          </FormField>

          <FormField
            label={editingId === null ? 'Password' : 'Password (kosongkan bila tidak diubah)'}
            htmlFor="user-pass"
            required={editingId === null}
          >
            <Input
              id="user-pass"
              type="password"
              value={password}
              placeholder={editingId === null ? 'min. 8 karakter' : 'min. 8 karakter bila diubah'}
              onChange={(event) => setPassword(event.target.value)}
            />
          </FormField>

          <FormField label="Nama Lengkap" htmlFor="user-full" required>
            <Input
              id="user-full"
              value={fullName}
              placeholder="mis. Budi Santoso"
              onChange={(event) => setFullName(event.target.value)}
            />
          </FormField>

          <Select
            label="Role"
            value={roleText}
            options={roleOptions}
            onChange={(event) => setRoleText(event.target.value)}
          />

          <Checkbox
            label="User aktif"
            checked={active}
            onCheckedChange={(checked) => setActive(checked)}
          />

          {errorText === null ? null : (
            <p role="alert" className="text-xs font-medium text-accent-coral">
              {errorText}
            </p>
          )}
        </div>
      </Modal>

      {/* F6.3 — konfirmasi regenerate: kode lama hangus (badge lama tidak berlaku lagi). */}
      <Modal
        open={confirmRegenerate !== null}
        onOpenChange={(open) => {
          if (!open) setConfirmRegenerate(null);
        }}
        title="Regenerate Kode Operator?"
        description="Kode lama tidak bisa dikembalikan dan badge yang sudah dicetak tidak berlaku lagi."
        footer={
          <>
            <Button variant="secondary" onClick={() => setConfirmRegenerate(null)}>
              Batal
            </Button>
            <Button icon={KeyRound} loading={bulk.isPending} onClick={runRegenerate}>
              Regenerate
            </Button>
          </>
        }
      >
        <p
          className="text-sm text-foreground"
          data-regenerate-count={(confirmRegenerate ?? []).length}
        >
          {(confirmRegenerate ?? []).length === 1
            ? `Kode operator ${confirmRegenerate?.[0]?.username ?? ''} akan diganti kode baru (4 digit).`
            : `Kode operator ${(confirmRegenerate ?? []).length} user akan diganti kode baru (4 digit).`}
        </p>
      </Modal>

      <Toast
        open={toast !== null}
        onOpenChange={(open) => {
          if (!open) setToast(null);
        }}
        title={toast?.title ?? ''}
        description={toast?.description}
        tone={toast?.tone ?? 'default'}
      />
    </div>
  );
}
