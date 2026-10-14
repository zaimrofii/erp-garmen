import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Pencil, Plus, Save, Star, Trash2 } from 'lucide-react';
import { Badge } from '@/components/atoms/Badge';
import { Button } from '@/components/atoms/Button';
import { Input } from '@/components/atoms/Input';
import { Modal } from '@/components/atoms/Modal';
import { Toast, type ToastTone } from '@/components/atoms/Toast';
import { DenseTable, type DenseTableColumn } from '@/components/molecules/DenseTable';
import { PageHeader } from '@/components/molecules/PageHeader';
import { PaginationBar } from '@/components/molecules/PaginationBar';
import { TableToolbar } from '@/components/molecules/TableToolbar';
import {
  CURRENCIES_LIMIT_MAX,
  createCurrency,
  deleteCurrency,
  fetchCurrencies,
  setDefaultCurrency,
  updateCurrency,
} from '@/api/masterCurrencies';
import { useFeedback } from '@/app/app-runtime';
import { useApiClient } from '@/hooks/useApiClient';
import { usePagination } from '@/hooks/use-pagination';
import { cn } from '@/lib/cn';
import {
  EMPTY_CURRENCY_FORM,
  currencyCreateInputFromForm,
  currencyFormFromRow,
  currencyRateLabel,
  currencySourceLabel,
  currencyUpdateInputFromForm,
  validateCurrencyCreateForm,
  validateCurrencyEditForm,
  type CurrencyFormValues,
} from '@/lib/master-currency';
import { CARD } from '@/lib/tokens';
import type { MasterCurrencyRow } from '@/types/master-currency';

/**
 * CurrenciesPage - route `/settings/currencies` (H5.2, khusus admin).
 *
 * Mata uang MES = **mirror `res.currency` Odoo** (pull I1 harian) + CRUD di MES:
 *
 *   * list `GET /api/v1/settings/currencies/` (filter `?search=&active=`);
 *   * **Buat** → `POST …/currencies/` (kode ISO 3 huruf A-Z, auto-upper & unik);
 *   * **Ubah** → `PUT …/currencies/<id>/` (nama/simbol/kurs/status; `code` hanya
 *     boleh berubah kalau formatnya ISO — baris hasil pull `ODOO-<id>` tetap bisa
 *     diedit tanpa 400);
 *   * **Set Default** → `POST …/currencies/<id>/set-default/` (atomik; maksimal
 *     satu `is_default` MES);
 *   * **Hapus** → `DELETE …/currencies/<id>/` = **soft delete** (`is_active=false`,
 *     200 + body) dengan `window.confirm`; backend menolak 400 kalau masih dipakai
 *     (`is_default` / kode terlindungi IDR–USD / baris hasil pull Odoo).
 *
 * **MES-only**: tanpa tombol Sync (mata uang tidak dikirim ke Odoo); setiap tulis
 * mencatat ledger `SKIPPED` di `/api/v1/sync/records/?status=SKIPPED`.
 *
 * Guard route: `SETTINGS_ROLES` (pola `/settings/sequences`).
 */

const EMPTY_ROWS: MasterCurrencyRow[] = [];
const QUERY_KEY = 'settings-currencies';

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

const COLUMNS: DenseTableColumn<MasterCurrencyRow>[] = [
  {
    key: 'code',
    label: 'Kode',
    render: (row) => <span className="font-mono tabular-nums">{row.code}</span>,
  },
  { key: 'name', label: 'Nama' },
  {
    key: 'symbol',
    label: 'Simbol',
    render: (row) => <span className="font-mono tabular-nums">{row.symbol}</span>,
  },
  {
    key: 'rate',
    label: 'Kurs',
    align: 'right',
    render: (row) => <span className="tabular-nums">{currencyRateLabel(row)}</span>,
  },
  {
    key: 'is_default',
    label: 'Default',
    render: (row) =>
      row.is_default ? <Badge tone="blue">Default</Badge> : <Badge tone="muted">-</Badge>,
  },
  {
    key: 'source',
    label: 'Sumber',
    render: (row) => (
      <span className="text-muted-foreground">{currencySourceLabel(row)}</span>
    ),
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

export function CurrenciesPage() {
  const client = useApiClient();
  const queryClient = useQueryClient();
  const { trigger } = useFeedback();

  const [search, setSearch] = useState('');
  const [status, setStatus] = useState('all');
  const [creating, setCreating] = useState<CurrencyFormValues | null>(null);
  const [editing, setEditing] = useState<{
    row: MasterCurrencyRow;
    values: CurrencyFormValues;
    active: boolean;
  } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<ToastState | null>(null);

  const active = status === 'all' ? null : status === 'active';

  const {
    data,
    isLoading,
    isFetching,
    error: queryError,
    refetch,
  } = useQuery({
    queryKey: [QUERY_KEY, active],
    queryFn: () => fetchCurrencies(client, { active, limit: CURRENCIES_LIMIT_MAX }),
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
        row.symbol.toLowerCase().includes(needle),
    );
  }, [data, search]);

  const pagination = usePagination(rows, { pageSize: 20 });

  const createMutation = useMutation({
    mutationFn: () => {
      if (creating === null) throw new Error('Tidak ada mata uang yang dibuat.');

      return createCurrency(client, currencyCreateInputFromForm(creating));
    },
    onSuccess: (saved) => {
      trigger('success');
      setToast({
        tone: 'success',
        title: 'Mata uang dibuat',
        description: `${saved.code} — ${saved.name}${saved.symbol === '' ? '' : ` (${saved.symbol})`}.`,
      });
      setCreating(null);
      void queryClient.invalidateQueries({ queryKey: [QUERY_KEY] });
    },
    onError: (caught) => {
      trigger('error');
      setError(caught instanceof Error ? caught.message : 'Permintaan buat gagal.');
    },
  });

  const updateMutation = useMutation({
    mutationFn: () => {
      if (editing === null) throw new Error('Tidak ada mata uang yang diedit.');

      return updateCurrency(
        client,
        editing.row.id,
        currencyUpdateInputFromForm(editing.values, editing.row.code, editing.active),
      );
    },
    onSuccess: (saved) => {
      trigger('success');
      setToast({
        tone: 'success',
        title: 'Mata uang diperbarui',
        description: `${saved.code} — ${saved.name} (${saved.is_active ? 'aktif' : 'nonaktif'}).`,
      });
      setEditing(null);
      void queryClient.invalidateQueries({ queryKey: [QUERY_KEY] });
    },
    onError: (caught) => {
      trigger('error');
      setError(caught instanceof Error ? caught.message : 'Permintaan simpan gagal.');
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => deleteCurrency(client, id),
    onSuccess: (deleted) => {
      trigger('success');
      setToast({
        tone: 'success',
        title: 'Mata uang dinonaktifkan',
        description: `Soft delete (is_active=false) — ledger sync #${String(deleted.sync_record_id ?? '-')} (MES-only).`,
      });
      void queryClient.invalidateQueries({ queryKey: [QUERY_KEY] });
    },
    onError: (caught) => {
      trigger('error');
      setError(caught instanceof Error ? caught.message : 'Permintaan hapus gagal.');
    },
  });

  const defaultMutation = useMutation({
    mutationFn: (id: number) => setDefaultCurrency(client, id),
    onSuccess: (saved) => {
      trigger('success');
      setToast({
        tone: 'success',
        title: 'Mata uang default diperbarui',
        description: `${saved.code} — ${saved.name} kini default MES (dijaga tunggal).`,
      });
      void queryClient.invalidateQueries({ queryKey: [QUERY_KEY] });
    },
    onError: (caught) => {
      trigger('error');
      setError(caught instanceof Error ? caught.message : 'Permintaan set default gagal.');
    },
  });

  function openCreate(): void {
    setError(null);
    setCreating({ ...EMPTY_CURRENCY_FORM });
  }

  function openEdit(row: MasterCurrencyRow): void {
    setError(null);
    setEditing({ row, values: currencyFormFromRow(row), active: row.is_active });
  }

  function confirmDelete(row: MasterCurrencyRow): void {
    setError(null);
    if (typeof window !== 'undefined' && !window.confirm(`Nonaktifkan mata uang ${row.code}?`)) {
      return;
    }
    deleteMutation.mutate(row.id);
  }

  const createErrors = creating === null ? {} : validateCurrencyCreateForm(creating);
  const canCreate = creating !== null && Object.keys(createErrors).length === 0;

  const editErrors =
    editing === null ? {} : validateCurrencyEditForm(editing.values, editing.row.code);
  const canSave = editing !== null && Object.keys(editErrors).length === 0;

  /** Kolom aksi dibuat di dalam komponen (butuh handler halaman). */
  const columns: DenseTableColumn<MasterCurrencyRow>[] = [
    ...COLUMNS,
    {
      key: 'actions',
      label: 'Aksi',
      render: (row) => (
        <div className="flex items-center gap-1">
          <Button
            variant="ghost"
            size="sm"
            icon={Pencil}
            aria-label={`Ubah ${row.code}`}
            onClick={() => openEdit(row)}
          >
            Ubah
          </Button>
          <Button
            variant="ghost"
            size="sm"
            icon={Star}
            aria-label={`Set default ${row.code}`}
            disabled={row.is_default || !row.is_active || defaultMutation.isPending}
            onClick={() => defaultMutation.mutate(row.id)}
          >
            Default
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
        title="Currencies"
        subtitle={`Mata uang MES (mirror res.currency Odoo + CRUD MES) — ${String(
          data?.total_count ?? 0,
        )} baris · MES-only, tidak disinkron ke Odoo`}
        breadcrumb={[{ label: 'Settings' }, { label: 'Currencies' }]}
      />

      <section className={cn(CARD, 'flex flex-col gap-3 p-4')}>
        <TableToolbar
          search={search}
          onSearchChange={(value) => {
            setSearch(value);
            pagination.reset();
          }}
          searchLabel="Cari mata uang"
          searchPlaceholder="Cari kode / nama / simbol"
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
          <p className="text-xs text-muted-foreground">
            Kode ISO 3 huruf (A-Z). Sumber Odoo = baris hasil pull I1 — tidak dapat
            dinonaktifkan dari MES; mata uang default &amp; kode IDR/USD juga dilindungi.
          </p>
          <Button icon={Plus} onClick={openCreate}>
            Buat Mata Uang
          </Button>
        </div>
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
          error={queryError === null ? null : 'Gagal memuat mata uang.'}
          onRetry={() => {
            void refetch();
          }}
          emptyMessage="Belum ada mata uang."
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
        open={creating !== null}
        onOpenChange={(open) => {
          if (!open) setCreating(null);
        }}
        title={creating === null ? 'Buat mata uang' : `Buat mata uang ${creating.code}`}
        description="Kode ISO 3 huruf A-Z (auto-upper). Simbol & kurs opsional."
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
              label="Simbol (opsional)"
              value={creating.symbol}
              onChange={(event) => setCreating({ ...creating, symbol: event.target.value })}
              {...(createErrors.symbol === undefined ? {} : { error: createErrors.symbol })}
            />
            <Input
              label="Kurs (opsional)"
              type="number"
              value={creating.rate}
              onChange={(event) => setCreating({ ...creating, rate: event.target.value })}
              {...(createErrors.rate === undefined ? {} : { error: createErrors.rate })}
            />
          </div>
        )}
      </Modal>

      <Modal
        open={editing !== null}
        onOpenChange={(open) => {
          if (!open) setEditing(null);
        }}
        title={editing === null ? 'Ubah mata uang' : `Ubah ${editing.row.code}`}
        description="Nama, simbol, kurs, dan status aktif. Kode hanya berubah bila diganti ke format ISO lain."
        footer={
          <div className="flex items-center gap-2">
            <Button
              icon={Save}
              disabled={!canSave || updateMutation.isPending}
              loading={updateMutation.isPending}
              onClick={() => updateMutation.mutate()}
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
              label="Kode"
              value={editing.values.code}
              onChange={(event) =>
                setEditing({ ...editing, values: { ...editing.values, code: event.target.value } })
              }
              {...(editErrors.code === undefined ? {} : { error: editErrors.code })}
            />
            <Input
              label="Nama"
              value={editing.values.name}
              onChange={(event) =>
                setEditing({ ...editing, values: { ...editing.values, name: event.target.value } })
              }
              {...(editErrors.name === undefined ? {} : { error: editErrors.name })}
            />
            <Input
              label="Simbol"
              value={editing.values.symbol}
              onChange={(event) =>
                setEditing({
                  ...editing,
                  values: { ...editing.values, symbol: event.target.value },
                })
              }
              {...(editErrors.symbol === undefined ? {} : { error: editErrors.symbol })}
            />
            <Input
              label="Kurs"
              type="number"
              value={editing.values.rate}
              onChange={(event) =>
                setEditing({ ...editing, values: { ...editing.values, rate: event.target.value } })
              }
              {...(editErrors.rate === undefined ? {} : { error: editErrors.rate })}
            />
            <Button
              type="button"
              variant="secondary"
              size="sm"
              onClick={() => setEditing({ ...editing, active: !editing.active })}
            >
              {editing.active ? 'Nonaktifkan' : 'Aktifkan'}
            </Button>
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


