import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Plus } from 'lucide-react';
import { Badge } from '@/components/atoms/Badge';
import { Button } from '@/components/atoms/Button';
import { DenseTable, type DenseTableColumn } from '@/components/molecules/DenseTable';
import { PageHeader } from '@/components/molecules/PageHeader';
import { PaginationBar } from '@/components/molecules/PaginationBar';
import { TableToolbar } from '@/components/molecules/TableToolbar';
import { fetchTaxes, TAXES_LIMIT_MAX } from '@/api/masterTaxes';
import { useApiClient } from '@/hooks/useApiClient';
import { useCsvExport, type CsvColumn } from '@/hooks/use-csv-export';
import { usePagination } from '@/hooks/use-pagination';
import { cn } from '@/lib/cn';
import { taxAmountLabel, taxUseLabel, TAX_USE_FILTERS } from '@/lib/master-tax';
import { CARD } from '@/lib/tokens';
import type { MasterTaxRow, TaxUse } from '@/types/master-tax';

/**
 * TaxesPage - route `/master/taxes` (H3.6, app Inventory).
 *
 * MES = source of truth master (docs/REPLACE-NOTICE.md): daftar pajak NYATA dari
 * `GET /api/v1/master/taxes/` (`api/masterTaxes.ts` → MODE.masterTaxes='real').
 *
 *   * filter server: `?search=` (code/name) + `?type_tax_use=` (tab Semua/Penjualan/Pembelian);
 *   * kolom: Kode, Nama, Tarif (`amount` + `amount_type`), Jenis, Harga termasuk,
 *     Default MES (badge — mes-only), Status, Odoo ID (`-` = belum push);
 *   * klik baris → detail (`/master/taxes/:id`); "Pajak Baru" → `/master/taxes/new`;
 *   * Export CSV via `useCsvExport` (kolom = bentuk backend).
 *
 * Guard route: `INVENTORY_ROLES`; izin **tulis** API hanya ADMIN/OWNER (brief H3.6).
 */

const EMPTY_ROWS: MasterTaxRow[] = [];

const FILTER_IDS: readonly string[] = TAX_USE_FILTERS.map((filter) => filter.id);

type TaxUseFilter = 'all' | TaxUse;

/** PURE - menyempitkan `string` dari Tabs ke filter jenis TANPA cast `as`. */
function isTaxUseFilter(value: string): value is TaxUseFilter {
  return FILTER_IDS.includes(value);
}

/** PURE - filter jenis UI → param `type_tax_use` backend (`null` = tidak difilter). */
function taxUseParamForFilter(filter: TaxUseFilter): TaxUse | null {
  return filter === 'all' ? null : filter;
}

const CSV_COLUMNS: CsvColumn<MasterTaxRow>[] = [
  { key: 'code', label: 'Kode' },
  { key: 'name', label: 'Nama' },
  { key: 'amount', label: 'Tarif' },
  { key: 'amount_type', label: 'Tipe nilai' },
  { key: 'type_tax_use', label: 'Jenis' },
  { key: 'price_include', label: 'Harga termasuk' },
  { key: 'is_default', label: 'Default MES' },
  { key: 'active', label: 'Aktif' },
  { key: 'odoo_id', label: 'Odoo ID' },
];

const COLUMNS: DenseTableColumn<MasterTaxRow>[] = [
  {
    key: 'code',
    label: 'Kode',
    render: (row) => <span className="font-mono tabular-nums">{row.code}</span>,
  },
  { key: 'name', label: 'Nama' },
  { key: 'amount', label: 'Tarif', align: 'right', render: (row) => taxAmountLabel(row) },
  { key: 'type_tax_use', label: 'Jenis', render: (row) => taxUseLabel(row.type_tax_use) },
  {
    key: 'price_include',
    label: 'Harga termasuk',
    render: (row) => (row.price_include ? 'Ya' : 'Tidak'),
  },
  {
    key: 'is_default',
    label: 'Default MES',
    render: (row) =>
      row.is_default ? (
        <Badge tone="blue">Default</Badge>
      ) : (
        <span className="text-muted-foreground">-</span>
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
    key: 'odoo_id',
    label: 'Odoo ID',
    align: 'right',
    render: (row) =>
      row.odoo_id === null ? (
        <span className="text-muted-foreground">-</span>
      ) : (
        <span className="font-mono tabular-nums">{String(row.odoo_id)}</span>
      ),
  },
];

export function TaxesPage() {
  const navigate = useNavigate();
  const client = useApiClient();
  const { exportCsv } = useCsvExport();

  const [search, setSearch] = useState('');
  const [filter, setFilter] = useState<TaxUseFilter>('all');

  const { data, isLoading, isFetching, error, refetch } = useQuery({
    queryKey: ['master-taxes', search, filter],
    queryFn: () =>
      fetchTaxes(client, {
        search,
        type_tax_use: taxUseParamForFilter(filter),
        limit: TAXES_LIMIT_MAX,
      }),
    staleTime: 15_000,
  });

  const rows = data?.rows ?? EMPTY_ROWS;
  const pagination = usePagination(rows, { pageSize: 20 });

  const hasFilter = search.trim().length > 0 || filter !== 'all';

  function handleSearch(value: string): void {
    setSearch(value);
    pagination.reset();
  }

  function handleFilter(id: string): void {
    if (!isTaxUseFilter(id)) return;

    setFilter(id);
    pagination.reset();
  }

  function resetFilters(): void {
    setSearch('');
    setFilter('all');
    pagination.reset();
  }

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <PageHeader
        title="Master Pajak"
        subtitle={`Pajak (PPN) MES — ${String(data?.total_count ?? 0)} baris`}
        breadcrumb={[
          { label: 'Inventory', href: '/inventory/products' },
          { label: 'Master Pajak' },
        ]}
        actions={
          <Button icon={Plus} onClick={() => navigate('/master/taxes/new')}>
            Pajak Baru
          </Button>
        }
      />

      <section className={cn(CARD, 'flex flex-col gap-3 p-4')}>
        <TableToolbar
          search={search}
          onSearchChange={handleSearch}
          searchLabel="Cari pajak"
          searchPlaceholder="Cari kode / nama pajak"
          filters={TAX_USE_FILTERS}
          activeFilter={filter}
          onFilterChange={handleFilter}
          exportDisabled={rows.length === 0}
          onExport={() => exportCsv(rows, 'master-taxes.csv', CSV_COLUMNS)}
          refreshing={isFetching}
          onRefresh={() => {
            void refetch();
          }}
        />

        <div className="flex flex-wrap items-end gap-3">
          <Button variant="secondary" size="sm" disabled={!hasFilter} onClick={resetFilters}>
            Reset Filter
          </Button>
        </div>
      </section>

      <section className={cn(CARD, 'p-0')}>
        <DenseTable
          columns={COLUMNS}
          rows={pagination.pageRows}
          loading={isLoading}
          error={error === null ? null : 'Gagal memuat master pajak.'}
          onRetry={() => {
            void refetch();
          }}
          onRowClick={(row) => navigate(`/master/taxes/${String(row.id)}`)}
          emptyMessage={
            hasFilter
              ? 'Tidak ada pajak yang cocok dengan filter.'
              : 'Belum ada pajak. Tambahkan lewat tombol "Pajak Baru".'
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
