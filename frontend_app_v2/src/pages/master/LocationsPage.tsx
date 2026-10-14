import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Plus } from 'lucide-react';
import { Badge } from '@/components/atoms/Badge';
import { Button } from '@/components/atoms/Button';
import { Select } from '@/components/atoms/Select';
import { DenseTable, type DenseTableColumn } from '@/components/molecules/DenseTable';
import { PageHeader } from '@/components/molecules/PageHeader';
import { PaginationBar } from '@/components/molecules/PaginationBar';
import { TableToolbar } from '@/components/molecules/TableToolbar';
import { fetchLocations, LOCATIONS_LIMIT_MAX } from '@/api/masterLocations';
import { useApiClient } from '@/hooks/useApiClient';
import { useCsvExport, type CsvColumn } from '@/hooks/use-csv-export';
import { usePagination } from '@/hooks/use-pagination';
import { cn } from '@/lib/cn';
import { displayOrDash, isLocationUsage, LOCATION_USAGE_OPTIONS, usageLabel } from '@/lib/master-location';
import { CARD } from '@/lib/tokens';
import type { LocationUsage, MasterLocationRow } from '@/types/master-location';

/**
 * LocationsPage - route `/master/locations` (H1.4, app Inventory).
 *
 * MES = source of truth master (docs/REPLACE-NOTICE.md): daftar lokasi NYATA dari
 * `GET /api/v1/master/locations/` (`api/masterLocations.ts` → MODE.masterLocations='real').
 *
 *   * filter server: `?search=` (code/name) + `?active=` (tab) + `?usage=` (dropdown);
 *   * kolom: Kode, Nama, Jenis, Induk, Gudang, Anak, Status, Odoo ID (`-` = belum push);
 *   * klik baris → detail (`/master/locations/:id`); "Lokasi Baru" → `/master/locations/new`;
 *   * Export CSV via `useCsvExport` (kolom = bentuk backend).
 *
 * Guard route: `INVENTORY_ROLES`; izin **tulis** API hanya ADMIN/OWNER (brief H1.4).
 * `complete_name` (Induk/Anak) dihitung backend dan HANYA ada di detail supaya daftar
 * tetap satu query (`annotate(Count)`).
 */

const EMPTY_ROWS: MasterLocationRow[] = [];

const STATUS_FILTERS: { id: string; label: string }[] = [
  { id: 'all', label: 'Semua' },
  { id: 'active', label: 'Aktif' },
  { id: 'inactive', label: 'Nonaktif' },
];

const STATUS_IDS: readonly string[] = STATUS_FILTERS.map((filter) => filter.id);

type LocationStatusFilter = 'all' | 'active' | 'inactive';

/** PURE - menyempitkan `string` dari Tabs ke filter status TANPA cast `as`. */
function isStatusFilter(value: string): value is LocationStatusFilter {
  return STATUS_IDS.includes(value);
}

/** PURE - filter status UI → param `active` backend (`null` = tidak difilter). */
function activeParamForStatus(status: LocationStatusFilter): boolean | null {
  if (status === 'active') return true;
  if (status === 'inactive') return false;

  return null;
}

/** Nilai dropdown jenis: `''` = semua (tidak difilter). */
/** Nilai dropdown jenis: `''` = semua (tidak difilter). */
const USAGE_FILTER_OPTIONS: { value: string; label: string }[] = [
  { value: '', label: 'Semua jenis' },
  ...LOCATION_USAGE_OPTIONS.map((option) => ({ value: option.value, label: option.label })),
];

const COLUMNS: DenseTableColumn<MasterLocationRow>[] = [
  {
    key: 'code',
    label: 'Kode',
    render: (row) => <span className="font-mono tabular-nums">{row.code}</span>,
  },
  { key: 'name', label: 'Nama' },
  {
    key: 'usage',
    label: 'Jenis',
    render: (row) => usageLabel(row.usage),
  },
  {
    key: 'parent_name',
    label: 'Induk',
    render: (row) => displayOrDash(row.parent_name),
  },
  {
    key: 'warehouse_name',
    label: 'Gudang',
    render: (row) => displayOrDash(row.warehouse_name),
  },
  {
    key: 'children_count',
    label: 'Anak',
    align: 'right',
    render: (row) => <span className="tabular-nums">{row.children_count}</span>,
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

const CSV_COLUMNS: CsvColumn<MasterLocationRow>[] = [
  { key: 'code', label: 'code' },
  { key: 'name', label: 'name' },
  { key: 'usage', label: 'usage' },
  { key: 'parent_name', label: 'parent_name' },
  { key: 'warehouse_name', label: 'warehouse_name' },
  { key: 'children_count', label: 'children_count' },
  { key: 'active', label: 'active' },
  { key: 'odoo_id', label: 'odoo_id' },
];

export function LocationsPage() {
  const client = useApiClient();
  const navigate = useNavigate();
  const { exportCsv } = useCsvExport();

  const [search, setSearch] = useState('');
  const [status, setStatus] = useState<LocationStatusFilter>('all');
  const [usage, setUsage] = useState<LocationUsage | ''>('');

  const { data, isLoading, isFetching, error, refetch } = useQuery({
    queryKey: ['master-locations', search, status, usage],
    queryFn: () =>
      fetchLocations(client, {
        search,
        active: activeParamForStatus(status),
        usage: usage === '' ? null : usage,
        limit: LOCATIONS_LIMIT_MAX,
      }),
    staleTime: 15_000,
  });

  const rows = data?.rows ?? EMPTY_ROWS;
  const pagination = usePagination(rows, { pageSize: 20 });

  const hasFilter = search.trim().length > 0 || status !== 'all' || usage !== '';

  function handleSearch(value: string): void {
    setSearch(value);
    pagination.reset();
  }

  function handleStatus(id: string): void {
    if (!isStatusFilter(id)) return;

    setStatus(id);
    pagination.reset();
  }

  function handleUsage(value: string): void {
    setUsage(isLocationUsage(value) ? value : '');
    pagination.reset();
  }

  function resetFilters(): void {
    setSearch('');
    setStatus('all');
    setUsage('');
    pagination.reset();
  }

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <PageHeader
        title="Master Lokasi"
        subtitle={`Lokasi (location) MES — ${String(data?.total_count ?? 0)} baris`}
        breadcrumb={[
          { label: 'Inventory', href: '/inventory/products' },
          { label: 'Master Lokasi' },
        ]}
        actions={
          <Button icon={Plus} onClick={() => navigate('/master/locations/new')}>
            Lokasi Baru
          </Button>
        }
      />

      <section className={cn(CARD, 'flex flex-col gap-3 p-4')}>
        <TableToolbar
          search={search}
          onSearchChange={handleSearch}
          searchLabel="Cari lokasi"
          searchPlaceholder="Cari kode / nama"
          filters={STATUS_FILTERS}
          activeFilter={status}
          onFilterChange={handleStatus}
          exportDisabled={rows.length === 0}
          onExport={() => exportCsv(rows, 'master-locations.csv', CSV_COLUMNS)}
          refreshing={isFetching}
          onRefresh={() => {
            void refetch();
          }}
        />

        <div className="flex flex-wrap items-end gap-3">
          <Select
            label="Jenis lokasi"
            options={USAGE_FILTER_OPTIONS}
            value={usage}
            onChange={(event) => handleUsage(event.target.value)}
          />
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
          error={error === null ? null : 'Gagal memuat master lokasi.'}
          onRetry={() => {
            void refetch();
          }}
          onRowClick={(row) => navigate(`/master/locations/${String(row.id)}`)}
          emptyMessage={
            hasFilter
              ? 'Tidak ada lokasi yang cocok dengan filter.'
              : 'Belum ada lokasi. Tambahkan lewat tombol "Lokasi Baru".'
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
