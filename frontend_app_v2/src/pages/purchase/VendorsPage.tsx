import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { DenseTable, type DenseTableColumn } from '@/components/molecules/DenseTable';
import { PageHeader } from '@/components/molecules/PageHeader';
import { PaginationBar } from '@/components/molecules/PaginationBar';
import { TableToolbar } from '@/components/molecules/TableToolbar';
import { fetchVendors, type VendorRow } from '@/api/purchase';
import { useApiClient } from '@/hooks/useApiClient';
import { useCsvExport, type CsvColumn } from '@/hooks/use-csv-export';
import { usePagination } from '@/hooks/use-pagination';
import { cn } from '@/lib/cn';
import { CARD } from '@/lib/tokens';

/**
 * VendorsPage - route `/purchase/vendors` (F2C.2).
 *
 * Data NYATA `GET /api/v1/purchase/vendors/` (B12). CATATAN: `email`/`phone`/`city`
 * SELALU `null` (master.Partner tidak punya field) → kolomnya DIBUANG.
 */

const EMPTY_VENDORS: VendorRow[] = [];

const COLUMNS: DenseTableColumn<VendorRow>[] = [
  { key: 'name', label: 'Nama' },
  {
    key: 'odoo_id',
    label: 'Odoo ID',
    align: 'right',
    render: (row) => (row.odoo_id === null ? '—' : row.odoo_id),
  },
];

const CSV_COLUMNS: CsvColumn<VendorRow>[] = [
  { key: 'name', label: 'name' },
  { key: 'odoo_id', label: 'odoo_id' },
];

export function VendorsPage() {
  const client = useApiClient();
  const [search, setSearch] = useState('');

  const vendors = useQuery({
    queryKey: ['purchase-vendors'],
    queryFn: () => fetchVendors(client),
    staleTime: 30_000,
  });

  const { exportCsv } = useCsvExport();
  const rows = vendors.data ?? EMPTY_VENDORS;

  const filtered = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (needle.length === 0) return rows;

    return rows.filter((row) => row.name.toLowerCase().includes(needle));
  }, [rows, search]);

  const pagination = usePagination(filtered, { pageSize: 20 });

  function handleSearch(value: string): void {
    setSearch(value);
    pagination.reset();
  }

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <PageHeader
        title="Vendors"
        subtitle="Daftar supplier (cache master.Partner)"
        breadcrumb={[{ label: 'Purchase' }, { label: 'Vendors' }]}
      />

      <TableToolbar
        search={search}
        onSearchChange={handleSearch}
        searchLabel="Cari vendor"
        searchPlaceholder="Cari nama vendor"
        exportDisabled={filtered.length === 0}
        onExport={() => exportCsv(filtered, 'purchase-vendors.csv', CSV_COLUMNS)}
        refreshing={vendors.isFetching}
        onRefresh={() => {
          void vendors.refetch();
        }}
      />

      <section className={cn(CARD, 'p-0')}>
        <DenseTable
          columns={COLUMNS}
          rows={pagination.pageRows}
          loading={vendors.isLoading}
          error={vendors.error === null ? null : 'Gagal memuat daftar vendor.'}
          onRetry={() => {
            void vendors.refetch();
          }}
          emptyMessage="Tidak ada vendor yang cocok dengan pencarian."
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
