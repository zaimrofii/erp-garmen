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
import { fetchUoms, UOMS_LIMIT_MAX } from '@/api/masterUoms';
import { useApiClient } from '@/hooks/useApiClient';
import { useCsvExport, type CsvColumn } from '@/hooks/use-csv-export';
import { usePagination } from '@/hooks/use-pagination';
import { cn } from '@/lib/cn';
import { UOM_TYPE_OPTIONS } from '@/lib/master-uom';
import { CARD } from '@/lib/tokens';
import type { MasterUomRow, UomType } from '@/types/master-uom';

/**
 * UomsPage - route `/master/uoms` (H1.2, app Inventory).
 *
 * MES = source of truth master (docs/REPLACE-NOTICE.md): daftar UoM NYATA dari
 * `GET /api/v1/master/uoms/` (`api/masterUoms.ts` → MODE.masterUoms='real').
 *
 *   * filter server: `?search=` (code/name/category) + `?active=` (tab Semua/Aktif/Nonaktif);
 *   * kolom: Kode, Nama, Kategori, Tipe, Rasio (`factor`), Presisi (`rounding`),
 *     Status, Odoo ID (`-` = belum push);
 *   * klik baris → detail (`/master/uoms/:id`); "UoM Baru" → `/master/uoms/new`;
 *   * Export CSV via `useCsvExport` (kolom = bentuk backend).
 *
 * Guard route: `INVENTORY_ROLES`; izin **tulis** API hanya ADMIN/OWNER (brief H1.2).
 */

const EMPTY_ROWS: MasterUomRow[] = [];

const STATUS_FILTERS: { id: string; label: string }[] = [
  { id: 'all', label: 'Semua' },
  { id: 'active', label: 'Aktif' },
  { id: 'inactive', label: 'Nonaktif' },
];

const STATUS_IDS: readonly string[] = STATUS_FILTERS.map((filter) => filter.id);

type UomStatusFilter = 'all' | 'active' | 'inactive';

/** PURE - menyempitkan `string` dari Tabs ke filter status TANPA cast `as`. */
function isStatusFilter(value: string): value is UomStatusFilter {
  return STATUS_IDS.includes(value);
}

/** PURE - filter status UI → param `active` backend (`null` = tidak difilter). */
function activeParamForStatus(status: UomStatusFilter): boolean | null {
  if (status === 'active') return true;
  if (status === 'inactive') return false;

  return null;
}

/** PURE - label tipe dari daftar opsi (`reference` default). */
function uomTypeLabel(value: UomType): string {
  return UOM_TYPE_OPTIONS.find((option) => option.value === value)?.label ?? value;
}

const COLUMNS: DenseTableColumn<MasterUomRow>[] = [
  {
    key: 'code',
    label: 'Kode',
    render: (row) => <span className="font-mono tabular-nums">{row.code}</span>,
  },
  { key: 'name', label: 'Nama' },
  { key: 'category', label: 'Kategori' },
  {
    key: 'uom_type',
    label: 'Tipe',
    render: (row) => uomTypeLabel(row.uom_type),
  },
  { key: 'factor', label: 'Rasio', align: 'right' },
  { key: 'rounding', label: 'Presisi', align: 'right' },
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

const CSV_COLUMNS: CsvColumn<MasterUomRow>[] = [
  { key: 'code', label: 'code' },
  { key: 'name', label: 'name' },
  { key: 'category', label: 'category' },
  { key: 'uom_type', label: 'uom_type' },
  { key: 'factor', label: 'factor' },
  { key: 'rounding', label: 'rounding' },
  { key: 'active', label: 'active' },
  { key: 'odoo_id', label: 'odoo_id' },
];

export function UomsPage() {
  const client = useApiClient();
  const navigate = useNavigate();
  const { exportCsv } = useCsvExport();

  const [search, setSearch] = useState('');
  const [status, setStatus] = useState<UomStatusFilter>('all');

  const { data, isLoading, isFetching, error, refetch } = useQuery({
    queryKey: ['master-uoms', search, status],
    queryFn: () =>
      fetchUoms(client, {
        search,
        active: activeParamForStatus(status),
        limit: UOMS_LIMIT_MAX,
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
        title="Master UoM"
        subtitle={`Satuan (unit of measure) MES — ${String(data?.total_count ?? 0)} baris`}
        breadcrumb={[
          { label: 'Inventory', href: '/inventory/products' },
          { label: 'Master UoM' },
        ]}
        actions={
          <Button icon={Plus} onClick={() => navigate('/master/uoms/new')}>
            UoM Baru
          </Button>
        }
      />

      <section className={cn(CARD, 'flex flex-col gap-3 p-4')}>
        <TableToolbar
          search={search}
          onSearchChange={handleSearch}
          searchLabel="Cari UoM"
          searchPlaceholder="Cari kode / nama / kategori"
          filters={STATUS_FILTERS}
          activeFilter={status}
          onFilterChange={handleStatus}
          exportDisabled={rows.length === 0}
          onExport={() => exportCsv(rows, 'master-uoms.csv', CSV_COLUMNS)}
          refreshing={isFetching}
          onRefresh={() => {
            void refetch();
          }}
        />

        <div className="flex flex-wrap items-end gap-3">
          <Button
            variant="secondary"
            size="sm"
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
          error={error === null ? null : 'Gagal memuat master UoM.'}
          onRetry={() => {
            void refetch();
          }}
          onRowClick={(row) => navigate(`/master/uoms/${String(row.id)}`)}
          emptyMessage={
            hasFilter
              ? 'Tidak ada UoM yang cocok dengan filter.'
              : 'Belum ada UoM. Tambahkan lewat tombol "UoM Baru".'
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

