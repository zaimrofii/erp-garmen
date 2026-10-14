import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Plus, RefreshCw } from 'lucide-react';
import { Button } from '@/components/atoms/Button';
import { Input } from '@/components/atoms/Input';
import { Modal } from '@/components/atoms/Modal';
import { DenseTable, type DenseTableColumn } from '@/components/molecules/DenseTable';
import { FormField } from '@/components/molecules/FormField';
import { PageHeader } from '@/components/molecules/PageHeader';
import { PaginationBar } from '@/components/molecules/PaginationBar';
import { TableToolbar } from '@/components/molecules/TableToolbar';
import {
  createLineAllocation,
  fetchLineAllocations,
  type LineAllocationRow,
} from '@/api/settings';
import { useApiClient } from '@/hooks/useApiClient';
import { useCsvExport, type CsvColumn } from '@/hooks/use-csv-export';
import { usePagination } from '@/hooks/use-pagination';
import { cn } from '@/lib/cn';
import { CARD } from '@/lib/tokens';

/**
 * LineAllocationPage - route `/settings/line-allocation` (khusus admin).
 *
 * REAL (F3A.CLOSE / B25): `GET` + `POST /api/v1/settings/line-allocation/`.
 * Baris = aturan `{name, wc_type, line_id, priority, config}` (model backend);
 * `line_id` diisi manual (backend tidak menyediakan endpoint daftar lini).
 */

const QUERY_KEY = ['settings-line-allocations'];
const EMPTY_ROWS: LineAllocationRow[] = [];

const COLUMNS: DenseTableColumn<LineAllocationRow>[] = [
  { key: 'name', label: 'Nama' },
  { key: 'wc_type', label: 'Tipe WC' },
  {
    key: 'line_code',
    label: 'Lini',
    render: (row) => (
      <span className="font-mono text-xs tabular-nums">
        {row.line_code ?? `#${row.line_id}`}
      </span>
    ),
  },
  { key: 'priority', label: 'Prioritas', align: 'right' },
  {
    key: 'is_active',
    label: 'Status',
    render: (row) => (row.is_active ? 'Aktif' : 'Nonaktif'),
  },
];

const CSV_COLUMNS: CsvColumn<LineAllocationRow>[] = [
  { key: 'name', label: 'name' },
  { key: 'wc_type', label: 'wc_type' },
  { key: 'line_id', label: 'line_id' },
  { key: 'priority', label: 'priority' },
];

export function LineAllocationPage() {
  const client = useApiClient();
  const queryClient = useQueryClient();

  const [search, setSearch] = useState('');
  const [formOpen, setFormOpen] = useState(false);
  const [name, setName] = useState('');
  const [wcType, setWcType] = useState('');
  const [lineIdText, setLineIdText] = useState('');
  const [priorityText, setPriorityText] = useState('0');
  const [errorText, setErrorText] = useState<string | null>(null);

  const allocations = useQuery({
    queryKey: QUERY_KEY,
    queryFn: () => fetchLineAllocations(client),
    staleTime: 30_000,
  });

  const create = useMutation({
    mutationFn: (payload: {
      name: string;
      wc_type: string;
      line_id: number;
      priority: number;
    }) => createLineAllocation(client, payload),
    onSuccess: () => {
      setFormOpen(false);
      setName('');
      setWcType('');
      setLineIdText('');
      setPriorityText('0');
      setErrorText(null);
      void queryClient.invalidateQueries({ queryKey: QUERY_KEY });
    },
    onError: () => {
      setErrorText('Gagal menyimpan aturan alokasi (cek `line_id`).');
    },
  });

  const { exportCsv } = useCsvExport();
  const rows = allocations.data?.rows ?? EMPTY_ROWS;

  const filtered = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (needle.length === 0) return rows;

    return rows.filter(
      (row) =>
        row.name.toLowerCase().includes(needle) || row.wc_type.toLowerCase().includes(needle),
    );
  }, [rows, search]);

  const pagination = usePagination(filtered, { pageSize: 20 });

  const wcTypeOptions = useMemo(() => {
    const types = rows.map((row) => row.wc_type);
    return Array.from(new Set(types)).filter((value) => value.length > 0);
  }, [rows]);

  function handleSearch(value: string): void {
    setSearch(value);
    pagination.reset();
  }

  function handleSubmit(): void {
    const lineId = Number(lineIdText);
    const priority = Number(priorityText);

    if (name.trim().length === 0) {
      setErrorText('Nama wajib diisi.');
      return;
    }
    if (wcType.trim().length === 0) {
      setErrorText('Tipe WC wajib diisi.');
      return;
    }
    if (!Number.isInteger(lineId) || lineId <= 0) {
      setErrorText('Line ID harus angka positif (id ProductionLine).');
      return;
    }
    if (!Number.isInteger(priority)) {
      setErrorText('Prioritas harus angka.');
      return;
    }

    setErrorText(null);
    create.mutate({
      name: name.trim(),
      wc_type: wcType.trim(),
      line_id: lineId,
      priority,
    });
  }

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <PageHeader
        title="Line Allocation"
        subtitle="Aturan alokasi work center ke lini produksi"
        breadcrumb={[{ label: 'Settings' }, { label: 'Line Allocation' }]}
        actions={
          <>
            <Button
              variant="secondary"
              size="sm"
              icon={RefreshCw}
              loading={allocations.isFetching}
              onClick={() => {
                void allocations.refetch();
              }}
            >
              Refresh
            </Button>
            <Button variant="primary" size="sm" icon={Plus} onClick={() => setFormOpen(true)}>
              Tambah Aturan
            </Button>
          </>
        }
      />

      <TableToolbar
        search={search}
        onSearchChange={handleSearch}
        searchLabel="Cari aturan"
        searchPlaceholder="Cari nama / tipe WC"
        exportDisabled={filtered.length === 0}
        onExport={() => exportCsv(filtered, 'settings-line-allocation.csv', CSV_COLUMNS)}
        refreshing={allocations.isFetching}
        onRefresh={() => {
          void allocations.refetch();
        }}
      />

      <section className={cn(CARD, 'p-0')}>
        <DenseTable
          columns={COLUMNS}
          rows={pagination.pageRows}
          loading={allocations.isLoading}
          error={allocations.error === null ? null : 'Gagal memuat aturan alokasi.'}
          onRetry={() => {
            void allocations.refetch();
          }}
          emptyMessage="Belum ada aturan alokasi."
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
        title="Tambah Aturan Alokasi"
        description="`Line ID` = id ProductionLine di backend (angka)."
        footer={
          <>
            <Button variant="secondary" onClick={() => setFormOpen(false)}>
              Batal
            </Button>
            <Button variant="primary" loading={create.isPending} onClick={handleSubmit}>
              Tambah
            </Button>
          </>
        }
      >
        <div className="flex flex-col gap-4">
          <FormField label="Nama" htmlFor="alloc-name" required>
            <Input
              id="alloc-name"
              value={name}
              placeholder="mis. Sewing ke LINE-A"
              onChange={(event) => setName(event.target.value)}
            />
          </FormField>

          <FormField label="Tipe WC" htmlFor="alloc-wc" required>
            <>
              <Input
                id="alloc-wc"
                list="alloc-wc-options"
                value={wcType}
                placeholder="mis. SEWING"
                onChange={(event) => setWcType(event.target.value)}
              />
              <datalist id="alloc-wc-options">
                {wcTypeOptions.map((option) => (
                  <option key={option} value={option} />
                ))}
              </datalist>
            </>
          </FormField>

          <FormField label="Line ID" htmlFor="alloc-line" required>
            <Input
              id="alloc-line"
              type="number"
              min={1}
              value={lineIdText}
              onChange={(event) => setLineIdText(event.target.value)}
            />
          </FormField>

          <FormField label="Prioritas" htmlFor="alloc-priority">
            <Input
              id="alloc-priority"
              type="number"
              value={priorityText}
              onChange={(event) => setPriorityText(event.target.value)}
            />
          </FormField>

          {errorText === null ? null : (
            <p role="alert" className="text-xs font-medium text-accent-coral">
              {errorText}
            </p>
          )}
        </div>
      </Modal>
    </div>
  );
}
