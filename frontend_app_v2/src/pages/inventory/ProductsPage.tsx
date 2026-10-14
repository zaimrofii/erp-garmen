import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { DenseTable, type DenseTableColumn } from '@/components/molecules/DenseTable';
import { PageHeader } from '@/components/molecules/PageHeader';
import { PaginationBar } from '@/components/molecules/PaginationBar';
import { TableToolbar } from '@/components/molecules/TableToolbar';
import { fetchProducts } from '@/api/inventory';
import { useApiClient } from '@/hooks/useApiClient';
import { useCsvExport, type CsvColumn } from '@/hooks/use-csv-export';
import { usePagination } from '@/hooks/use-pagination';
import { cn } from '@/lib/cn';
import { CARD } from '@/lib/tokens';
import type { ProductRow } from '@/types/inventory-product';

/**
 * ProductsPage - route `/inventory/products` (inventory/admin/owner).
 * Tabel dense + search + export CSV + pagination.
 * F2c.1: data NYATA `GET /api/v1/inventory/products/` (B7). Kolom `type`/`uom`
 * DIBUANG (tidak ada di backend) - lihat `docs/contract-gap-f1f2.md`.
 */

const EMPTY_ROWS: ProductRow[] = [];

const COLUMNS: DenseTableColumn<ProductRow>[] = [
  {
    key: 'code',
    label: 'Kode',
    render: (row) => <span className="font-mono tabular-nums">{row.code}</span>,
  },
  { key: 'name', label: 'Nama' },
  {
    key: 'odoo_id',
    label: 'Odoo ID',
    align: 'right',
    render: (row) => (row.odoo_id === null ? '-' : row.odoo_id),
  },
  { key: 'stock_qty', label: 'Stok', align: 'right' },
];

const CSV_COLUMNS: CsvColumn<ProductRow>[] = [
  { key: 'code', label: 'code' },
  { key: 'name', label: 'name' },
  { key: 'odoo_id', label: 'odoo_id' },
  { key: 'stock_qty', label: 'stock_qty' },
];

export function ProductsPage() {
  const client = useApiClient();
  const [search, setSearch] = useState('');

  const { data, isLoading, isFetching, error, refetch } = useQuery({
    queryKey: ['inventory-products'],
    queryFn: () => fetchProducts(client),
    staleTime: 15_000,
  });

  const { exportCsv } = useCsvExport();
  const rows = data ?? EMPTY_ROWS;

  const filtered = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (needle.length === 0) return rows;

    return rows.filter(
      (row) => row.code.toLowerCase().includes(needle) || row.name.toLowerCase().includes(needle),
    );
  }, [rows, search]);

  const pagination = usePagination(filtered, { pageSize: 20 });

  function handleSearch(value: string): void {
    setSearch(value);
    pagination.reset();
  }

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <PageHeader
        title="Products"
        subtitle="Master produk: bahan baku, WIP, dan barang jadi"
        breadcrumb={[{ label: 'Inventory' }, { label: 'Products' }]}
      />

      <TableToolbar
        search={search}
        onSearchChange={handleSearch}
        searchLabel="Cari produk"
        searchPlaceholder="Cari kode / nama produk"
        exportDisabled={filtered.length === 0}
        onExport={() => exportCsv(filtered, 'inventory-products.csv', CSV_COLUMNS)}
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
          error={error === null ? null : 'Gagal memuat daftar produk.'}
          onRetry={() => {
            void refetch();
          }}
          emptyMessage="Tidak ada produk yang cocok dengan filter."
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
