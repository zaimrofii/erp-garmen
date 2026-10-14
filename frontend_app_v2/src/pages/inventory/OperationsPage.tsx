import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { DenseTable, type DenseTableColumn } from '@/components/molecules/DenseTable';
import { PageHeader } from '@/components/molecules/PageHeader';
import { PaginationBar } from '@/components/molecules/PaginationBar';
import { TableToolbar } from '@/components/molecules/TableToolbar';
import { fetchOperations, type OperationRow } from '@/api/inventory';
import { useApiClient } from '@/hooks/useApiClient';
import { useCsvExport, type CsvColumn } from '@/hooks/use-csv-export';
import { usePagination } from '@/hooks/use-pagination';
import { cn } from '@/lib/cn';
import { CARD } from '@/lib/tokens';

/**
 * OperationsPage - route `/inventory/operations` (F2C.2).
 *
 * Data NYATA `GET /api/v1/inventory/operations/` (B8) = MONITOR sync stok
 * (`WIP_ISSUE|FG_RECEIPT|SCRAP|INVOICE`); `product_code`/`qty` bisa `null` → "—".
 */

const ALL = 'all';

const EMPTY_ROWS: OperationRow[] = [];

const FILTERS = [
  { id: ALL, label: 'Semua' },
  { id: 'WIP_ISSUE', label: 'WIP Issue' },
  { id: 'FG_RECEIPT', label: 'FG Receipt' },
  { id: 'SCRAP', label: 'Scrap' },
  { id: 'INVOICE', label: 'Invoice' },
];

const COLUMNS: DenseTableColumn<OperationRow>[] = [
  { key: 'type', label: 'Tipe' },
  {
    key: 'ref',
    label: 'Ref',
    render: (row) => <span className="font-mono tabular-nums">{row.ref}</span>,
  },
  { key: 'product_code', label: 'Produk', render: (row) => row.product_code ?? '—' },
  {
    key: 'qty',
    label: 'Qty',
    align: 'right',
    render: (row) => (row.qty === null ? '—' : row.qty),
  },
  { key: 'status', label: 'Status' },
  {
    key: 'at',
    label: 'Waktu',
    render: (row) => (row.at === null ? '—' : new Date(row.at).toLocaleString('id-ID')),
  },
];

const CSV_COLUMNS: CsvColumn<OperationRow>[] = [
  { key: 'type', label: 'type' },
  { key: 'ref', label: 'ref' },
  { key: 'product_code', label: 'product_code' },
  { key: 'qty', label: 'qty' },
  { key: 'status', label: 'status' },
  { key: 'at', label: 'at' },
];

export function OperationsPage() {
  const client = useApiClient();
  const [search, setSearch] = useState('');
  const [typeFilter, setTypeFilter] = useState<string>(ALL);

  const { data, isLoading, isFetching, error, refetch } = useQuery({
    queryKey: ['inventory-operations'],
    queryFn: () => fetchOperations(client),
    staleTime: 15_000,
  });

  const { exportCsv } = useCsvExport();
  const rows = data ?? EMPTY_ROWS;

  const filtered = useMemo(() => {
    const needle = search.trim().toLowerCase();

    return rows.filter((row) => {
      if (typeFilter !== ALL && row.type !== typeFilter) return false;
      if (needle.length === 0) return true;

      return (
        row.ref.toLowerCase().includes(needle) ||
        (row.product_code ?? '').toLowerCase().includes(needle)
      );
    });
  }, [rows, search, typeFilter]);

  const pagination = usePagination(filtered, { pageSize: 20 });

  function handleSearch(value: string): void {
    setSearch(value);
    pagination.reset();
  }

  function handleFilter(id: string): void {
    setTypeFilter(id);
    pagination.reset();
  }

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <PageHeader
        title="Operations"
        subtitle="Monitor operasi sync stok (WIP issue, FG receipt, scrap, invoice)"
        breadcrumb={[{ label: 'Inventory' }, { label: 'Operations' }]}
      />

      <TableToolbar
        search={search}
        onSearchChange={handleSearch}
        searchLabel="Cari operasi"
        searchPlaceholder="Cari ref / produk"
        filters={FILTERS}
        activeFilter={typeFilter}
        onFilterChange={handleFilter}
        exportDisabled={filtered.length === 0}
        onExport={() => exportCsv(filtered, 'inventory-operations.csv', CSV_COLUMNS)}
        refreshing={isFetching}
        onRefresh={() => {
          void refetch();
        }}
      />

      <section className={cn(CARD, 'p-0')}>
        <DenseTable
          columns={COLUMNS}
          rows={pagination.pageRows}
          loading={isLoading}
          error={error === null ? null : 'Gagal memuat daftar operasi.'}
          onRetry={() => {
            void refetch();
          }}
          emptyMessage="Tidak ada operasi yang cocok dengan filter."
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
    </div>
  );
}
