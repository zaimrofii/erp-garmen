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
import { fetchWorkCenters, WORK_CENTERS_LIMIT_MAX } from '@/api/masterWorkCenters';
import { useApiClient } from '@/hooks/useApiClient';
import { useCsvExport, type CsvColumn } from '@/hooks/use-csv-export';
import { usePagination } from '@/hooks/use-pagination';
import { cn } from '@/lib/cn';
import {
  displayOrDash,
  formatCapacity,
  WC_TYPE_SUGGESTIONS,
} from '@/lib/master-work-center';
import { CARD } from '@/lib/tokens';
import type { MasterWorkCenterRow } from '@/types/master-work-center';

/**
 * WorkCentersPage - route `/master/work-centers` (H1.7, app Inventory).
 *
 * MES = source of truth master: daftar work center NYATA dari
 * `GET /api/v1/master/work-centers/` (`api/masterWorkCenters.ts` →
 * MODE.masterWorkCenters='real').
 *
 *   * filter server: `?search=` (kode/nama/tipe) + `?wc_type=` (exact, case-insensitive)
 *     + `?active=`; chip tipe memakai `WC_TYPE_SUGGESTIONS` (free-form tetap boleh);
 *   * kolom: Kode, Nama, Tipe, Kapasitas/jam, Tag Kapabilitas, Status;
 *   * **tanpa kolom Odoo ID** — Work Center MES-only (tidak ada push/pull, jadi
 *     memang tidak ada id ERP);
 *   * klik baris → detail (`/master/work-centers/:id`); "Work Center Baru" → `/new`;
 *   * Export CSV via `useCsvExport` (kolom = bentuk backend).
 *
 * Guard route: `INVENTORY_ROLES` (konsisten H1.1–H1.6); izin **tulis** API ADMIN/OWNER.
 */

const EMPTY_ROWS: MasterWorkCenterRow[] = [];

/** Chip filter tipe = saran baku + "Semua Tipe". */
const TYPE_FILTERS: { id: string; label: string }[] = [
  { id: 'all', label: 'Semua Tipe' },
  ...WC_TYPE_SUGGESTIONS.map((type) => ({ id: type, label: type })),
];

const TYPE_IDS: readonly string[] = TYPE_FILTERS.map((filter) => filter.id);

type WorkCenterTypeFilter = 'all' | string;

/** PURE - menyempitkan `string` dari Tabs ke id filter yang dikenal. */
function isTypeFilter(value: string): value is WorkCenterTypeFilter {
  return TYPE_IDS.includes(value);
}

/** PURE - chip filter → param backend (`null` = tidak difilter). */
function typeParamForStatus(status: WorkCenterTypeFilter): string | null {
  return status === 'all' ? null : status;
}

const COLUMNS: DenseTableColumn<MasterWorkCenterRow>[] = [
  {
    key: 'code',
    label: 'Kode',
    render: (row) => <span className="font-mono tabular-nums">{row.code}</span>,
  },
  { key: 'name', label: 'Nama' },
  { key: 'wc_type', label: 'Tipe', render: (row) => displayOrDash(row.wc_type) },
  {
    key: 'capacity_per_hour',
    label: 'Kapasitas/jam',
    align: 'right',
    render: (row) => (
      <span className="tabular-nums">{formatCapacity(row.capacity_per_hour)}</span>
    ),
  },
  {
    key: 'capability_tags',
    label: 'Tag Kapabilitas',
    render: (row) =>
      row.capability_tags.length === 0 ? (
        <span className="text-muted-foreground">-</span>
      ) : (
        <span className="flex flex-wrap gap-1">
          {row.capability_tags.map((tag) => (
            <Badge key={tag} tone="muted">
              {tag}
            </Badge>
          ))}
        </span>
      ),
  },
  {
    key: 'active',
    label: 'Status',
    render: (row) => (
      <Badge tone={row.active ? 'blue' : 'muted'}>{row.active ? 'Aktif' : 'Nonaktif'}</Badge>
    ),
  },
];

/** Baris siap-CSV (tag digabung `|` karena `CsvColumn` hanya mendukung key skalar). */
interface WorkCenterCsvRow {
  code: string;
  name: string;
  wc_type: string;
  capacity_per_hour: number;
  capability_tags: string;
  active: boolean;
}

const CSV_COLUMNS: CsvColumn<WorkCenterCsvRow>[] = [
  { key: 'code', label: 'code' },
  { key: 'name', label: 'name' },
  { key: 'wc_type', label: 'wc_type' },
  { key: 'capacity_per_hour', label: 'capacity_per_hour' },
  { key: 'capability_tags', label: 'capability_tags' },
  { key: 'active', label: 'active' },
];

/** PURE — baris master → baris CSV (tag list → string `|`). */
function toCsvRow(row: MasterWorkCenterRow): WorkCenterCsvRow {
  return {
    code: row.code,
    name: row.name,
    wc_type: row.wc_type,
    capacity_per_hour: row.capacity_per_hour,
    capability_tags: row.capability_tags.join('|'),
    active: row.active,
  };
}

export function WorkCentersPage() {
  const client = useApiClient();
  const navigate = useNavigate();
  const { exportCsv } = useCsvExport();

  const [search, setSearch] = useState('');
  const [wcType, setWcType] = useState<WorkCenterTypeFilter>('all');

  const { data, isLoading, isFetching, error, refetch } = useQuery({
    queryKey: ['master-work-centers', search, wcType],
    queryFn: () =>
      fetchWorkCenters(client, {
        search,
        wc_type: typeParamForStatus(wcType),
        limit: WORK_CENTERS_LIMIT_MAX,
      }),
    staleTime: 15_000,
  });

  const rows = data?.rows ?? EMPTY_ROWS;
  const pagination = usePagination(rows, { pageSize: 20 });

  const hasFilter = search.trim().length > 0 || wcType !== 'all';

  function handleSearch(value: string): void {
    setSearch(value);
    pagination.reset();
  }

  function handleType(id: string): void {
    if (!isTypeFilter(id)) return;

    setWcType(id);
    pagination.reset();
  }

  function resetFilters(): void {
    setSearch('');
    setWcType('all');
    pagination.reset();
  }

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <PageHeader
        title="Master Work Center"
        subtitle={`Stasiun kerja MES — ${String(data?.total_count ?? 0)} baris (MES-only, tidak disinkron ke Odoo)`}
        breadcrumb={[
          { label: 'Inventory', href: '/inventory/products' },
          { label: 'Master Work Center' },
        ]}
        actions={
          <Button icon={Plus} onClick={() => navigate('/master/work-centers/new')}>
            Work Center Baru
          </Button>
        }
      />

      <section className={cn(CARD, 'flex flex-col gap-3 p-4')}>
        <TableToolbar
          search={search}
          onSearchChange={handleSearch}
          searchLabel="Cari work center"
          searchPlaceholder="Cari kode / nama / tipe"
          filters={TYPE_FILTERS}
          activeFilter={wcType}
          onFilterChange={handleType}
          exportDisabled={rows.length === 0}
          onExport={() => exportCsv(rows.map(toCsvRow), 'master-work-centers.csv', CSV_COLUMNS)}
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
          error={error === null ? null : 'Gagal memuat master work center.'}
          onRetry={() => {
            void refetch();
          }}
          onRowClick={(row) => navigate(`/master/work-centers/${String(row.id)}`)}
          emptyMessage={
            hasFilter
              ? 'Tidak ada work center yang cocok dengan filter.'
              : 'Belum ada work center. Tambahkan lewat tombol "Work Center Baru".'
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
