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
import { fetchWarehouses, WAREHOUSES_LIMIT_MAX } from '@/api/masterWarehouses';
import { useApiClient } from '@/hooks/useApiClient';
import { useCsvExport, type CsvColumn } from '@/hooks/use-csv-export';
import { usePagination } from '@/hooks/use-pagination';
import { cn } from '@/lib/cn';
import { DELIVERY_STEP_OPTIONS, RECEPTION_STEP_OPTIONS } from '@/lib/master-warehouse';
import { CARD } from '@/lib/tokens';
import type { DeliverySteps, MasterWarehouseRow, ReceptionSteps } from '@/types/master-warehouse';

/**
 * WarehousesPage - route `/master/warehouses` (H1.3, app Inventory).
 *
 * MES = source of truth master (docs/REPLACE-NOTICE.md): daftar gudang NYATA dari
 * `GET /api/v1/master/warehouses/` (`api/masterWarehouses.ts` → MODE.masterWarehouses='real').
 *
 *   * filter server: `?search=` (code/name) + `?active=` (tab Semua/Aktif/Nonaktif);
 *   * kolom: Kode, Nama, Penerimaan, Pengiriman, Status, Odoo ID (`-` = belum push);
 *   * klik baris → detail (`/master/warehouses/:id`); "Gudang Baru" → `/master/warehouses/new`;
 *   * Export CSV via `useCsvExport` (kolom = bentuk backend).
 *
 * Guard route: `INVENTORY_ROLES`; izin **tulis** API hanya ADMIN/OWNER (brief H1.3).
 * Field `usage` tidak ada di sini (di Odoo itu milik stock.location — H1.4).
 */

const EMPTY_ROWS: MasterWarehouseRow[] = [];

const STATUS_FILTERS: { id: string; label: string }[] = [
  { id: 'all', label: 'Semua' },
  { id: 'active', label: 'Aktif' },
  { id: 'inactive', label: 'Nonaktif' },
];

const STATUS_IDS: readonly string[] = STATUS_FILTERS.map((filter) => filter.id);

type WarehouseStatusFilter = 'all' | 'active' | 'inactive';

/** PURE - menyempitkan `string` dari Tabs ke filter status TANPA cast `as`. */
function isStatusFilter(value: string): value is WarehouseStatusFilter {
  return STATUS_IDS.includes(value);
}

/** PURE - filter status UI → param `active` backend (`null` = tidak difilter). */
function activeParamForStatus(status: WarehouseStatusFilter): boolean | null {
  if (status === 'active') return true;
  if (status === 'inactive') return false;

  return null;
}

/** PURE - label penerimaan dari daftar opsi. */
function receptionLabel(value: ReceptionSteps): string {
  return RECEPTION_STEP_OPTIONS.find((option) => option.value === value)?.label ?? value;
}

/** PURE - label pengiriman dari daftar opsi. */
function deliveryLabel(value: DeliverySteps): string {
  return DELIVERY_STEP_OPTIONS.find((option) => option.value === value)?.label ?? value;
}

const COLUMNS: DenseTableColumn<MasterWarehouseRow>[] = [
  {
    key: 'code',
    label: 'Kode',
    render: (row) => <span className="font-mono tabular-nums">{row.code}</span>,
  },
  { key: 'name', label: 'Nama' },
  {
    key: 'reception_steps',
    label: 'Penerimaan',
    render: (row) => receptionLabel(row.reception_steps),
  },
  {
    key: 'delivery_steps',
    label: 'Pengiriman',
    render: (row) => deliveryLabel(row.delivery_steps),
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

const CSV_COLUMNS: CsvColumn<MasterWarehouseRow>[] = [
  { key: 'code', label: 'code' },
  { key: 'name', label: 'name' },
  { key: 'reception_steps', label: 'reception_steps' },
  { key: 'delivery_steps', label: 'delivery_steps' },
  { key: 'active', label: 'active' },
  { key: 'odoo_id', label: 'odoo_id' },
];

export function WarehousesPage() {
  const client = useApiClient();
  const navigate = useNavigate();
  const { exportCsv } = useCsvExport();

  const [search, setSearch] = useState('');
  const [status, setStatus] = useState<WarehouseStatusFilter>('all');

  const { data, isLoading, isFetching, error, refetch } = useQuery({
    queryKey: ['master-warehouses', search, status],
    queryFn: () =>
      fetchWarehouses(client, {
        search,
        active: activeParamForStatus(status),
        limit: WAREHOUSES_LIMIT_MAX,
      }),
    staleTime: 15_000,
  });

  const rows = data?.rows ?? EMPTY_ROWS;
  const pagination = usePagination(rows, { pageSize: 20 });

  const hasFilter = search.trim().length > 0 || status !== 'all';

  function handleSearch(value: string): void {
    setSearch(value);
    pagination.reset();
  }

  function handleStatus(id: string): void {
    if (!isStatusFilter(id)) return;

    setStatus(id);
    pagination.reset();
  }

  function resetFilters(): void {
    setSearch('');
    setStatus('all');
    pagination.reset();
  }

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <PageHeader
        title="Master Gudang"
        subtitle={`Gudang (warehouse) MES — ${String(data?.total_count ?? 0)} baris`}
        breadcrumb={[
          { label: 'Inventory', href: '/inventory/products' },
          { label: 'Master Gudang' },
        ]}
        actions={
          <Button icon={Plus} onClick={() => navigate('/master/warehouses/new')}>
            Gudang Baru
          </Button>
        }
      />

      <section className={cn(CARD, 'flex flex-col gap-3 p-4')}>
        <TableToolbar
          search={search}
          onSearchChange={handleSearch}
          searchLabel="Cari gudang"
          searchPlaceholder="Cari kode / nama"
          filters={STATUS_FILTERS}
          activeFilter={status}
          onFilterChange={handleStatus}
          exportDisabled={rows.length === 0}
          onExport={() => exportCsv(rows, 'master-warehouses.csv', CSV_COLUMNS)}
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
          error={error === null ? null : 'Gagal memuat master gudang.'}
          onRetry={() => {
            void refetch();
          }}
          onRowClick={(row) => navigate(`/master/warehouses/${String(row.id)}`)}
          emptyMessage={
            hasFilter
              ? 'Tidak ada gudang yang cocok dengan filter.'
              : 'Belum ada gudang. Tambahkan lewat tombol "Gudang Baru".'
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

