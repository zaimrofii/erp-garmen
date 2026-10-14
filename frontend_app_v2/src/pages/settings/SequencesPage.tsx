import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Eye, Plus, Save, Trash2 } from 'lucide-react';
import { Badge } from '@/components/atoms/Badge';
import { Button } from '@/components/atoms/Button';
import { Input } from '@/components/atoms/Input';
import { Modal } from '@/components/atoms/Modal';
import { Select, type SelectOption } from '@/components/atoms/Select';
import { Toast, type ToastTone } from '@/components/atoms/Toast';
import { DenseTable, type DenseTableColumn } from '@/components/molecules/DenseTable';
import { PageHeader } from '@/components/molecules/PageHeader';
import { PaginationBar } from '@/components/molecules/PaginationBar';
import { TableToolbar } from '@/components/molecules/TableToolbar';
import {
  createSequence,
  deleteSequence,
  fetchSequences,
  previewSequenceNumber,
  SEQUENCES_LIMIT_MAX,
  updateSequence,
} from '@/api/masterSequences';
import { useFeedback } from '@/app/app-runtime';
import { useApiClient } from '@/hooks/useApiClient';
import { usePagination } from '@/hooks/use-pagination';
import { cn } from '@/lib/cn';
import {
  createSequenceInputFromForm,
  EMPTY_CREATE_SEQUENCE_FORM,
  sequenceInputFromForm,
  validateCreateSequenceForm,
  validateSequenceForm,
  type CreateSequenceFormValues,
  type SequenceFormValues,
} from '@/lib/master-sequence';
import { CARD } from '@/lib/tokens';
import type { MasterSequenceRow, SequencePreview } from '@/types/master-sequence';

/**
 * SequencesPage - route `/settings/sequences` (Sprint C + CRUD H5.3, khusus admin).
 *
 * Penomoran dokumen MES: ``<PREFIX>-<YEAR>-<SEQ:04d>``, **reset per tahun** (satu baris
 * per `(code, year)`; baris tahun baru dibuat backend saat penomoran pertama).
 *
 *   * list `GET /api/v1/settings/sequences/` (filter `?search=&active=&year=`; default
 *     tahun berjalan) — kolom Kode/Nama/Prefix/Tahun/Terakhir/Nomor Berikutnya/Padding/Status;
 *   * **Preview** → `GET …/<code>/preview/` → modal menampilkan nomor berikutnya TANPA
 *     menaikkan counter (read-only);
 *   * **Ubah** → `PUT …/<code>/` untuk prefix/padding/nama/aktif (izin tulis backend
 *     **ADMIN/OWNER**); `code`/`year`/`last_seq` TIDAK bisa diubah dari UI (backend
 *     menolak 400) — counter hanya naik lewat `next_number` (dipakai H2.1+);
 *   * **Buat** (H5.3) → `POST …/sequences/` (kode `^[A-Z0-9]{2,16}$`, auto-upper);
 *   * **Hapus** (H5.3) → `DELETE …/<code>/` = **soft delete** (`is_active=false`, 204)
 *     dengan `window.confirm`; backend menolak 400 kalau kode seed terlindungi
 *     (SO/PO/WO/INV/VB/PAY/JE/ADJ/TRF) atau `last_seq > 0`;
 *   * **MES-only**: tanpa tombol Sync (nomor tidak dikirim ke Odoo); setiap tulis
 *     mencatat ledger `SKIPPED` di `/api/v1/sync/records/?status=SKIPPED`.
 *
 * Guard route: `SETTINGS_ROLES` (pola `/settings/routing`).
 */

const EMPTY_ROWS: MasterSequenceRow[] = [];
const QUERY_KEY = 'settings-sequences';
const CURRENT_YEAR = new Date().getFullYear();

/** Opsi filter tahun (dikirim `?year=`; `''` = tahun berjalan backend). */
const YEAR_FILTERS: SelectOption[] = [
  { value: '', label: `Tahun berjalan (${String(CURRENT_YEAR)})` },
  { value: String(CURRENT_YEAR - 1), label: String(CURRENT_YEAR - 1) },
  { value: String(CURRENT_YEAR + 1), label: String(CURRENT_YEAR + 1) },
  { value: 'all', label: 'Semua tahun' },
];

/** Chip filter status (dikirim sebagai `?active=`). */
const STATUS_FILTERS: { id: string; label: string }[] = [
  { id: 'all', label: 'Semua' },
  { id: 'active', label: 'Aktif' },
  { id: 'inactive', label: 'Nonaktif' },
];

interface ToastState {
  tone: ToastTone;
  title: string;
  description: string;
}

const COLUMNS: DenseTableColumn<MasterSequenceRow>[] = [
  {
    key: 'code',
    label: 'Kode',
    render: (row) => <span className="font-mono tabular-nums">{row.code}</span>,
  },
  { key: 'name', label: 'Nama' },
  {
    key: 'prefix',
    label: 'Prefix',
    render: (row) => <span className="font-mono tabular-nums">{row.prefix}</span>,
  },
  {
    key: 'year',
    label: 'Tahun',
    align: 'right',
    render: (row) => <span className="tabular-nums">{row.year}</span>,
  },
  {
    key: 'last_seq',
    label: 'Terakhir',
    align: 'right',
    render: (row) => <span className="tabular-nums">{row.last_seq}</span>,
  },
  {
    key: 'next_number',
    label: 'Nomor Berikutnya',
    render: (row) => <span className="font-mono text-xs tabular-nums">{row.next_number}</span>,
  },
  {
    key: 'padding',
    label: 'Padding',
    align: 'right',
    render: (row) => <span className="tabular-nums">{row.padding}</span>,
  },
  {
    key: 'is_active',
    label: 'Status',
    render: (row) => (
      <Badge tone={row.is_active ? 'blue' : 'muted'}>
        {row.is_active ? 'Aktif' : 'Nonaktif'}
      </Badge>
    ),
  },
];

export function SequencesPage() {
  const client = useApiClient();
  const queryClient = useQueryClient();
  const { trigger } = useFeedback();

  const [search, setSearch] = useState('');
  const [status, setStatus] = useState('all');
  const [year, setYear] = useState('');
  const [preview, setPreview] = useState<{ code: string; data: SequencePreview | null } | null>(
    null,
  );
  const [editing, setEditing] = useState<{ code: string; values: SequenceFormValues } | null>(null);
  const [creating, setCreating] = useState<CreateSequenceFormValues | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<ToastState | null>(null);

  const active = status === 'all' ? null : status === 'active';
  const yearParam = year === '' ? null : year === 'all' ? 'all' : Number(year);

  const {
    data,
    isLoading,
    isFetching,
    error: queryError,
    refetch,
  } = useQuery({
    queryKey: [QUERY_KEY, active, year],
    queryFn: () =>
      fetchSequences(client, { active, year: yearParam, limit: SEQUENCES_LIMIT_MAX }),
    staleTime: 15_000,
  });

  const rows = useMemo(() => {
    const all = data?.rows ?? EMPTY_ROWS;
    const needle = search.trim().toLowerCase();
    if (!needle) return all;
    return all.filter(
      (row) =>
        row.code.toLowerCase().includes(needle) ||
        row.name.toLowerCase().includes(needle) ||
        row.prefix.toLowerCase().includes(needle),
    );
  }, [data, search]);

  const pagination = usePagination(rows, { pageSize: 20 });

  const previewMutation = useMutation({
    mutationFn: (code: string) => previewSequenceNumber(client, code),
    onSuccess: (result) => setPreview({ code: result.code, data: result }),
    onError: (caught) => {
      trigger('error');
      setError(caught instanceof Error ? caught.message : 'Gagal memuat pratinjau.');
    },
  });

  const saveMutation = useMutation({
    mutationFn: () => {
      if (editing === null) throw new Error('Tidak ada sequence yang diedit.');

      return updateSequence(client, editing.code, sequenceInputFromForm(editing.values));
    },
    onSuccess: (saved) => {
      trigger('success');
      setToast({
        tone: 'success',
        title: 'Sequence diperbarui',
        description: `${saved.code}: prefix ${saved.prefix}, padding ${String(saved.padding)} — nomor berikutnya ${saved.next_number}.`,
      });
      setEditing(null);
      void queryClient.invalidateQueries({ queryKey: [QUERY_KEY] });
    },
    onError: (caught) => {
      trigger('error');
      setError(caught instanceof Error ? caught.message : 'Permintaan simpan gagal.');
    },
  });

  const createMutation = useMutation({
    mutationFn: () => {
      if (creating === null) throw new Error('Tidak ada sequence yang dibuat.');

      return createSequence(
        client,
        createSequenceInputFromForm(creating),
        yearParam === 'all' ? null : yearParam,
      );
    },
    onSuccess: (saved) => {
      trigger('success');
      setToast({
        tone: 'success',
        title: 'Sequence dibuat',
        description: `${saved.code}: prefix ${saved.prefix}, padding ${String(saved.padding)} — nomor berikutnya ${saved.next_number}.`,
      });
      setCreating(null);
      void queryClient.invalidateQueries({ queryKey: [QUERY_KEY] });
    },
    onError: (caught) => {
      trigger('error');
      setError(caught instanceof Error ? caught.message : 'Permintaan buat gagal.');
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (code: string) => deleteSequence(client, code),
    onSuccess: (_result, code) => {
      trigger('success');
      setToast({
        tone: 'success',
        title: 'Sequence dinonaktifkan',
        description: `${code} di-soft delete (is_active=false). Kode seed terlindungi & sequence yang sudah dipakai tetap dijaga backend.`,
      });
      void queryClient.invalidateQueries({ queryKey: [QUERY_KEY] });
    },
    onError: (caught) => {
      trigger('error');
      setError(caught instanceof Error ? caught.message : 'Permintaan hapus gagal.');
    },
  });

  function openCreate(): void {
    setError(null);
    setCreating({ ...EMPTY_CREATE_SEQUENCE_FORM });
  }

  function confirmDelete(row: MasterSequenceRow): void {
    setError(null);
    if (typeof window !== 'undefined' && !window.confirm(`Nonaktifkan sequence ${row.code}?`)) {
      return;
    }
    deleteMutation.mutate(row.code);
  }

  function openEdit(row: MasterSequenceRow): void {
    setError(null);
    setEditing({
      code: row.code,
      values: {
        name: row.name,
        prefix: row.prefix,
        padding: String(row.padding),
        active: row.is_active,
      },
    });
  }

  function openPreview(code: string): void {
    setError(null);
    setPreview({ code, data: null });
    previewMutation.mutate(code);
  }

  const editErrors = editing === null ? {} : validateSequenceForm(editing.values);
  const canSave = editing !== null && Object.keys(editErrors).length === 0;

  const createErrors = creating === null ? {} : validateCreateSequenceForm(creating);
  const canCreate = creating !== null && Object.keys(createErrors).length === 0;

  /** Kolom aksi dibuat di dalam komponen (butuh handler halaman). */
  const columns: DenseTableColumn<MasterSequenceRow>[] = [
    ...COLUMNS,
    {
      key: 'actions',
      label: 'Aksi',
      render: (row) => (
        <div className="flex items-center gap-1">
          <Button
            variant="ghost"
            size="sm"
            icon={Eye}
            aria-label={`Pratinjau ${row.code}`}
            onClick={() => openPreview(row.code)}
          >
            Preview
          </Button>
          <Button
            variant="ghost"
            size="sm"
            icon={Save}
            aria-label={`Ubah ${row.code}`}
            onClick={() => openEdit(row)}
          >
            Ubah
          </Button>
          <Button
            variant="ghost"
            size="sm"
            icon={Trash2}
            aria-label={`Hapus ${row.code}`}
            disabled={deleteMutation.isPending}
            onClick={() => confirmDelete(row)}
          >
            Hapus
          </Button>
        </div>
      ),
    },
  ];


  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <PageHeader
        title="Number Sequence"
        subtitle={`Penomoran dokumen MES (<PREFIX>-<TAHUN>-<NNNN>, reset per tahun) — ${String(
          data?.total_count ?? 0,
        )} baris · MES-only, tidak disinkron ke Odoo`}
        breadcrumb={[{ label: 'Settings' }, { label: 'Number Sequence' }]}
      />

      <section className={cn(CARD, 'flex flex-col gap-3 p-4')}>
        <TableToolbar
          search={search}
          onSearchChange={(value) => {
            setSearch(value);
            pagination.reset();
          }}
          searchLabel="Cari sequence"
          searchPlaceholder="Cari kode / nama / prefix"
          filters={STATUS_FILTERS}
          activeFilter={status}
          onFilterChange={(value) => {
            setStatus(value);
            pagination.reset();
          }}
          refreshing={isFetching}
          onRefresh={() => {
            void refetch();
          }}
        />
        <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
          <div className="w-full sm:w-64">
            <Select
              label="Tahun"
              options={YEAR_FILTERS}
              value={year}
              onChange={(event) => {
                setYear(event.target.value);
                pagination.reset();
              }}
            />
          </div>
          <Button icon={Plus} onClick={openCreate}>
            Buat Sequence
          </Button>
        </div>
        <p className="text-xs text-muted-foreground">
          Nomor bersifat pratinjau: counter hanya naik saat dokumen benar-benar dibuat
          (H2.1+) — tombol mata tidak menaikkannya. Kode seed terlindungi dari penghapusan.
        </p>
      </section>

      {error !== null ? (
        <p role="alert" className="text-sm font-medium text-accent-coral">
          {error}
        </p>
      ) : null}

      <section className={cn(CARD, 'p-0')}>
        <DenseTable
          columns={columns}
          rows={pagination.pageRows}
          loading={isLoading}
          error={queryError === null ? null : 'Gagal memuat number sequence.'}
          onRetry={() => {
            void refetch();
          }}
          emptyMessage="Belum ada sequence."
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
        open={preview !== null}
        onOpenChange={(open) => {
          if (!open) setPreview(null);
        }}
        title={preview === null ? 'Pratinjau nomor' : `Pratinjau ${preview.code}`}
        description="Nomor berikutnya — dihitung tanpa menaikkan counter."
        footer={
          <Button variant="secondary" onClick={() => setPreview(null)}>
            Tutup
          </Button>
        }
      >
        {preview?.data === null || preview?.data === undefined ? (
          <p className="text-sm text-muted-foreground">Memuat pratinjau…</p>
        ) : (
          <div className="flex flex-col gap-2 text-sm">
            <span className="font-mono text-lg tabular-nums">{preview.data.next_number}</span>
            <span className="text-muted-foreground">
              Prefix {preview.data.prefix} · tahun {String(preview.data.year)} · nomor terakhir{' '}
              {String(preview.data.last_seq)} · padding {String(preview.data.padding)}
            </span>
          </div>
        )}
      </Modal>

      <Modal
        open={editing !== null}
        onOpenChange={(open) => {
          if (!open) setEditing(null);
        }}
        title={editing === null ? 'Ubah sequence' : `Ubah ${editing.code}`}
        description="Prefix, padding, nama, dan status aktif. Kode & counter tidak dapat diubah."
        footer={
          <div className="flex items-center gap-2">
            <Button
              icon={Save}
              disabled={!canSave || saveMutation.isPending}
              loading={saveMutation.isPending}
              onClick={() => saveMutation.mutate()}
            >
              Simpan
            </Button>
            <Button variant="ghost" onClick={() => setEditing(null)}>
              Batal
            </Button>
          </div>
        }
      >
        {editing === null ? null : (
          <div className="flex flex-col gap-3">
            <Input
              label="Nama"
              value={editing.values.name}
              onChange={(event) =>
                setEditing({ ...editing, values: { ...editing.values, name: event.target.value } })
              }
              {...(editErrors.name === undefined ? {} : { error: editErrors.name })}
            />
            <Input
              label="Prefix"
              value={editing.values.prefix}
              onChange={(event) =>
                setEditing({
                  ...editing,
                  values: { ...editing.values, prefix: event.target.value },
                })
              }
              {...(editErrors.prefix === undefined ? {} : { error: editErrors.prefix })}
            />
            <Input
              label="Padding"
              type="number"
              value={editing.values.padding}
              onChange={(event) =>
                setEditing({
                  ...editing,
                  values: { ...editing.values, padding: event.target.value },
                })
              }
              {...(editErrors.padding === undefined ? {} : { error: editErrors.padding })}
            />
            <Button
              type="button"
              variant="secondary"
              size="sm"
              onClick={() =>
                setEditing({
                  ...editing,
                  values: { ...editing.values, active: !editing.values.active },
                })
              }
            >
              {editing.values.active ? 'Nonaktifkan' : 'Aktifkan'}
            </Button>
          </div>
        )}
      </Modal>

      <Modal
        open={creating !== null}
        onOpenChange={(open) => {
          if (!open) setCreating(null);
        }}
        title={creating === null ? 'Buat sequence' : `Buat sequence ${creating.code}`}
        description="Kode unik per tahun (A-Z/0-9). Prefix opsional (default = kode); padding 1-10."
        footer={
          <div className="flex items-center gap-2">
            <Button
              icon={Plus}
              disabled={!canCreate || createMutation.isPending}
              loading={createMutation.isPending}
              onClick={() => createMutation.mutate()}
            >
              Buat
            </Button>
            <Button variant="ghost" onClick={() => setCreating(null)}>
              Batal
            </Button>
          </div>
        }
      >
        {creating === null ? null : (
          <div className="flex flex-col gap-3">
            <Input
              label="Kode"
              value={creating.code}
              onChange={(event) => setCreating({ ...creating, code: event.target.value })}
              {...(createErrors.code === undefined ? {} : { error: createErrors.code })}
            />
            <Input
              label="Nama"
              value={creating.name}
              onChange={(event) => setCreating({ ...creating, name: event.target.value })}
              {...(createErrors.name === undefined ? {} : { error: createErrors.name })}
            />
            <Input
              label="Prefix (opsional)"
              value={creating.prefix}
              onChange={(event) => setCreating({ ...creating, prefix: event.target.value })}
              {...(createErrors.prefix === undefined ? {} : { error: createErrors.prefix })}
            />
            <Input
              label="Padding"
              type="number"
              value={creating.padding}
              onChange={(event) => setCreating({ ...creating, padding: event.target.value })}
              {...(createErrors.padding === undefined ? {} : { error: createErrors.padding })}
            />
          </div>
        )}
      </Modal>

      {toast !== null ? (
        <Toast
          open={toast !== null}
          onOpenChange={() => setToast(null)}
          title={toast.title}
          tone={toast.tone}
          description={toast.description}
        />
      ) : null}
    </div>
  );
}


