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
import { fetchProductionLines, PRODUCTION_LINES_LIMIT_MAX } from '@/api/masterProductionLines';
import { useApiClient } from '@/hooks/useApiClient';
import { useCsvExport, type CsvColumn } from '@/hooks/use-csv-export';
import { usePagination } from '@/hooks/use-pagination';
import { cn } from '@/lib/cn';
import {
  workCentersSummary,
} from '@/lib/master-production-line';
import { CARD } from '@/lib/tokens';
import type { MasterProductionLineRow } from '@/types/master-production-line';

/**
 * ProductionLinesPage - route `/master/production-lines` (H1.8, app Inventory).
 *
 * MES = source of truth: daftar lini NYATA dari `GET /api/v1/master/production-lines/`
 * (`api/masterProductionLines.ts` → MODE.masterProductionLines='real').
 *
 *   * filter server: `?search=` (kode/nama) + `?capability_tag=` (isi list tag,
 *     case-insensitive) + `?active=`;
 *   * kolom: Kode, Nama, Tag Kapabilitas, Anggota (ringkas 3 WC), Aturan, Status;
 *   * **tanpa kolom Odoo ID** — Production Line MES-only (Odoo 17 tidak punya wadah lini);
 *   * klik baris → detail; "Production Line Baru" → `/new`; Export CSV.
 *
 * Guard route: `INVENTORY_ROLES` (konsisten H1.1–H1.7); izin **tulis** API ADMIN/OWNER.
 */

const EMPTY_ROWS: MasterProductionLineRow[] = [];

/** Chip filter tag = saran baku H1.7 (free-form tetap boleh lewat kotak cari). */
const TAG_FILTERS: { id: string; label: string }[] = [
  { id: 'all', label: 'Semua Tag' },
  { id: 'JAHIT', label: 'JAHIT' },
  { id: 'OBRAS', label: 'OBRAS' },
  { id: 'CUTTING', label: 'CUTTING' },
  { id: 'QC', label: 'QC' },
];

const TAG_IDS: readonly string[] = TAG_FILTERS.map((filter) => filter.id);

type LineTagFilter = 'all' | string;

/** PURE - menyempitkan `string` dari Tabs ke id filter yang dikenal. */
function isTagFilter(value: string): value is LineTagFilter {
  return TAG_IDS.includes(value);
}

/** PURE - chip filter → param backend (`null` = tidak difilter). */
function tagParamForStatus(status: LineTagFilter): string | null {
  return status === 'all' ? null : status;
}

const COLUMNS: DenseTableColumn<MasterProductionLineRow>[] = [
  {
    key: 'code',
    label: 'Kode',
    render: (row) => <span className="font-mono tabular-nums">{row.code}</span>,
  },
  { key: 'name', label: 'Nama' },
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
    key: 'work_centers_count',
    label: 'Anggota',
    render: (row) => <span className="text-xs">{workCentersSummary(row)}</span>,
  },
  {
    key: 'allocation_rules_count',
    label: 'Aturan',
    align: 'right',
    render: (row) => <span className="tabular-nums">{row.allocation_rules_count}</span>,
  },
  {
    key: 'active',
    label: 'Status',
    render: (row) => (
      <Badge tone={row.active ? 'blue' : 'muted'}>{row.active ? 'Aktif' : 'Nonaktif'}</Badge>
    ),
  },
];

/** Baris siap-CSV (tag & anggota digabung karena `CsvColumn` hanya key skalar). */
interface ProductionLineCsvRow {
  code: string;
  name: string;
  capability_tags: string;
  work_centers: string;
  work_centers_count: number;
  allocation_rules_count: number;
  active: boolean;
}

const CSV_COLUMNS: CsvColumn<ProductionLineCsvRow>[] = [
  { key: 'code', label: 'code' },
  { key: 'name', label: 'name' },
  { key: 'capability_tags', label: 'capability_tags' },
  { key: 'work_centers', label: 'work_centers' },
  { key: 'work_centers_count', label: 'work_centers_count' },
  { key: 'allocation_rules_count', label: 'allocation_rules_count' },
  { key: 'active', label: 'active' },
];

/** PURE — baris master → baris CSV (tag & anggota jadi string `|`). */
function toCsvRow(row: MasterProductionLineRow): ProductionLineCsvRow {
  return {
    code: row.code,
    name: row.name,
    capability_tags: row.capability_tags.join('|'),
    work_centers: row.work_center_names.join('|'),
    work_centers_count: row.work_centers_count,
    allocation_rules_count: row.allocation_rules_count,
    active: row.active,
  };
}

export function ProductionLinesPage() {
  const client = useApiClient();
  const navigate = useNavigate();
  const { exportCsv } = useCsvExport();

  const [search, setSearch] = useState('');
  const [capabilityTag, setCapabilityTag] = useState<LineTagFilter>('all');

  const { data, isLoading, isFetching, error, refetch } = useQuery({
    queryKey: ['master-production-lines', search, capabilityTag],
    queryFn: () =>
      fetchProductionLines(client, {
        search,
        capability_tag: tagParamForStatus(capabilityTag),
        limit: PRODUCTION_LINES_LIMIT_MAX,
      }),
    staleTime: 15_000,
  });

  const rows = data?.rows ?? EMPTY_ROWS;
  const pagination = usePagination(rows, { pageSize: 20 });

  const hasFilter = search.trim().length > 0 || capabilityTag !== 'all';

  function handleSearch(value: string): void {
    setSearch(value);
    pagination.reset();
  }

  function handleTag(id: string): void {
    if (!isTagFilter(id)) return;

    setCapabilityTag(id);
    pagination.reset();
  }

  function resetFilters(): void {
    setSearch('');
    setCapabilityTag('all');
    pagination.reset();
  }

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <PageHeader
        title="Master Production Line"
        subtitle={`Lini produksi MES — ${String(data?.total_count ?? 0)} baris (MES-only, tidak disinkron ke Odoo)`}
        breadcrumb={[
          { label: 'Inventory', href: '/inventory/products' },
          { label: 'Master Production Line' },
        ]}
        actions={
          <Button icon={Plus} onClick={() => navigate('/master/production-lines/new')}>
            Production Line Baru
          </Button>
        }
      />

      <section className={cn(CARD, 'flex flex-col gap-3 p-4')}>
        <TableToolbar
          search={search}
          onSearchChange={handleSearch}
          searchLabel="Cari production line"
          searchPlaceholder="Cari kode / nama lini"
          filters={TAG_FILTERS}
          activeFilter={capabilityTag}
          onFilterChange={handleTag}
          exportDisabled={rows.length === 0}
          onExport={() =>
            exportCsv(rows.map(toCsvRow), 'master-production-lines.csv', CSV_COLUMNS)
          }
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
          error={error === null ? null : 'Gagal memuat master production line.'}
          onRetry={() => {
            void refetch();
          }}
          onRowClick={(row) => navigate(`/master/production-lines/${String(row.id)}`)}
          emptyMessage={
            hasFilter
              ? 'Tidak ada production line yang cocok dengan filter.'
              : 'Belum ada production line. Tambahkan lewat tombol "Production Line Baru".'
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
