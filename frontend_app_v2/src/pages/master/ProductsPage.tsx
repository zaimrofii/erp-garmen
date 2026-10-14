import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Plus, RotateCcw } from 'lucide-react';
import { Badge } from '@/components/atoms/Badge';
import { Button } from '@/components/atoms/Button';
import { Input } from '@/components/atoms/Input';
import { DenseTable, type DenseTableColumn } from '@/components/molecules/DenseTable';
import { PageHeader } from '@/components/molecules/PageHeader';
import { PaginationBar } from '@/components/molecules/PaginationBar';
import { TableToolbar } from '@/components/molecules/TableToolbar';
import { fetchProducts, PRODUCTS_LIMIT_MAX } from '@/api/masterProducts';
import { useApiClient } from '@/hooks/useApiClient';
import { useCsvExport, type CsvColumn } from '@/hooks/use-csv-export';
import { usePagination } from '@/hooks/use-pagination';
import { cn } from '@/lib/cn';
import {
  activeParamForStatus,
  displayOrDash,
  formatPrice,
  STATUS_FILTERS,
  type ProductStatusFilter,
} from '@/lib/master-product';
import { CARD } from '@/lib/tokens';
import type { MasterProductRow } from '@/types/master-product';

/**
 * ProductsPage - route `/master/products` (H1.1, app Inventory).
 *
 * MES = source of truth master (docs/REPLACE-NOTICE.md): daftar produk NYATA dari
 * `GET /api/v1/master/products/` (`api/masterProducts.ts` → MODE.masterProducts='real').
 *
 *   * filter server: `?search=` (code/name/category), `?category=`, `?active=`
 *     (tab Semua/Aktif/Nonaktif) — satu query per kombinasi (jumlah produk kecil);
 *   * pagination klien (`usePagination`) di atas satu halaman `limit=200`;
 *   * kolom: Kode, Nama, Kategori, UoM, Harga Jual, Status, Odoo ID (`-` = belum push);
 *   * klik baris → form edit (`/master/products/:id`); "Produk Baru" → `/master/products/new`;
 *   * Export CSV memakai `useCsvExport` (kolom = bentuk backend, bukan label).
 *
 * Guard route: `INVENTORY_ROLES` (`inventory`/`admin`/`owner`) — sedangkan izin
 * tulis API juga menerima role `purchasing` (H1.1).
 */

const EMPTY_ROWS: MasterProductRow[] = [];

const STATUS_IDS: readonly string[] = STATUS_FILTERS.map((filter) => filter.id);

/** PURE - menyempitkan `string` dari Tabs ke `ProductStatusFilter` TANPA cast `as`. */
function isStatusFilter(value: string): value is ProductStatusFilter {
  return STATUS_IDS.includes(value);
}

const COLUMNS: DenseTableColumn<MasterProductRow>[] = [
  {
    key: 'code',
    label: 'Kode',
    render: (row) => <span className="font-mono tabular-nums">{row.code}</span>,
  },
  { key: 'name', label: 'Nama' },
  {
    key: 'category',
    label: 'Kategori',
    render: (row) => displayOrDash(row.category),
  },
  {
    key: 'uom_code',
    label: 'UoM',
    render: (row) => displayOrDash(row.uom_code),
  },
  {
    key: 'sale_price',
    label: 'Harga Jual',
    align: 'right',
    render: (row) => <span className="tabular-nums">{formatPrice(row.sale_price)}</span>,
  },
  {
    key: 'active',
    label: 'Status',
    render: (row) => (
      <Badge tone={row.active ? 'blue' : 'muted'}>{row.active ? 'Aktif' : 'Nonaktif'}</Badge>
    ),
  },
  {
    key: 'odoo_id',
    label: 'Odoo ID',
    align: 'right',
    render: (row) =>
      row.odoo_id === null ? (
        <span className="text-muted-foreground">-</span>
      ) : (
        <span className="tabular-nums">{row.odoo_id}</span>
      ),
  },
];

const CSV_COLUMNS: CsvColumn<MasterProductRow>[] = [
  { key: 'code', label: 'code' },
  { key: 'name', label: 'name' },
  { key: 'category', label: 'category' },
  { key: 'uom_id', label: 'uom_id' },
  { key: 'sale_price', label: 'sale_price' },
  { key: 'cost_price', label: 'cost_price' },
  { key: 'active', label: 'active' },
  { key: 'odoo_id', label: 'odoo_id' },
];

export function ProductsPage() {
  const client = useApiClient();
  const navigate = useNavigate();
  const { exportCsv } = useCsvExport();

  const [search, setSearch] = useState('');
  const [category, setCategory] = useState('');
  const [status, setStatus] = useState<ProductStatusFilter>('all');

  const { data, isLoading, isFetching, error, refetch } = useQuery({
    queryKey: ['master-products', search, category, status],
    queryFn: () =>
      fetchProducts(client, {
        search,
        category,
        active: activeParamForStatus(status),
        limit: PRODUCTS_LIMIT_MAX,
      }),
    staleTime: 15_000,
  });

  const rows = data?.rows ?? EMPTY_ROWS;
  const pagination = usePagination(rows, { pageSize: 20 });

  const hasFilter = search.trim().length > 0 || category.trim().length > 0 || status !== 'all';

  function handleSearch(value: string): void {
    setSearch(value);
    pagination.reset();
  }

  function handleCategory(value: string): void {
    setCategory(value);
    pagination.reset();
  }

  function handleStatus(id: string): void {
    if (!isStatusFilter(id)) return;

    setStatus(id);
    pagination.reset();
  }

  function resetFilters(): void {
    setSearch('');
    setCategory('');
    setStatus('all');
    pagination.reset();
  }

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <PageHeader
        title="Master Products"
        subtitle={`Produk MES (bahan/WIP/barang jadi) — ${String(data?.total_count ?? 0)} baris`}
        breadcrumb={[
          { label: 'Inventory', href: '/inventory/products' },
          { label: 'Master Products' },
        ]}
        actions={
          <Button icon={Plus} onClick={() => navigate('/master/products/new')}>
            Produk Baru
          </Button>
        }
      />

      <section className={cn(CARD, 'flex flex-col gap-3 p-4')}>
        <TableToolbar
          search={search}
          onSearchChange={handleSearch}
          searchLabel="Cari produk"
          searchPlaceholder="Cari kode / nama / kategori"
          filters={STATUS_FILTERS}
          activeFilter={status}
          onFilterChange={handleStatus}
          exportDisabled={rows.length === 0}
          onExport={() => exportCsv(rows, 'master-products.csv', CSV_COLUMNS)}
          refreshing={isFetching}
          onRefresh={() => {
            void refetch();
          }}
        />

        <div className="flex flex-wrap items-end gap-3">
          <div className="w-full sm:w-56">
            <Input
              label="Kategori"
              value={category}
              placeholder="mis. Atasan"
              onChange={(event) => handleCategory(event.target.value)}
            />
          </div>

          <Button
            variant="secondary"
            size="sm"
            icon={RotateCcw}
            disabled={!hasFilter}
            onClick={resetFilters}
          >
            Reset Filter
          </Button>
        </div>
      </section>

      <section className={cn(CARD, 'p-0')}>
        <DenseTable
          columns={COLUMNS}
          rows={pagination.pageRows}
          loading={isLoading}
          error={error === null ? null : 'Gagal memuat master produk.'}
          onRetry={() => {
            void refetch();
          }}
          onRowClick={(row) => navigate(`/master/products/${String(row.id)}`)}
          emptyMessage={
            hasFilter
              ? 'Tidak ada produk yang cocok dengan filter.'
              : 'Belum ada produk. Tambahkan lewat tombol "Produk Baru".'
          }
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

