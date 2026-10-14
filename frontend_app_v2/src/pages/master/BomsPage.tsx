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
import { fetchBoms, BOMS_LIMIT_MAX } from '@/api/masterBoms';
import { useApiClient } from '@/hooks/useApiClient';
import { useCsvExport, type CsvColumn } from '@/hooks/use-csv-export';
import { usePagination } from '@/hooks/use-pagination';
import { cn } from '@/lib/cn';
import { productOptionLabel } from '@/lib/master-bom';
import { CARD } from '@/lib/tokens';
import type { MasterBomRow } from '@/types/master-bom';

/**
 * BomsPage - route `/master/boms` (H1.5, app Inventory).
 *
 * MES = source of truth master (docs/REPLACE-NOTICE.md): daftar BOM NYATA dari
 * `GET /api/v1/master/boms/` (`api/masterBoms.ts` → MODE.masterBoms='real').
 *
 *   * filter server: `?search=` (kode/nama BOM + kode/nama produk) + `?active=`;
 *   * kolom: Kode, Nama, Produk, Output, Komponen (baris aktif), Status, Odoo ID;
 *   * klik baris → detail (`/master/boms/:id`); "BOM Baru" → `/master/boms/new`;
 *   * Export CSV via `useCsvExport` (kolom = bentuk backend).
 *
 * Guard route: `INVENTORY_ROLES` (konsisten H1.1–H1.4); izin **tulis** API hanya
 * ADMIN/OWNER (brief H1.5). Daftar TIDAK memuat `lines[]` (backend menghitung
 * `lines_count` lewat satu `annotate(Count)`) supaya tetap satu query.
 */

const EMPTY_ROWS: MasterBomRow[] = [];

const STATUS_FILTERS: { id: string; label: string }[] = [
  { id: 'all', label: 'Semua' },
  { id: 'active', label: 'Aktif' },
  { id: 'inactive', label: 'Nonaktif' },
];

const STATUS_IDS: readonly string[] = STATUS_FILTERS.map((filter) => filter.id);

type BomStatusFilter = 'all' | 'active' | 'inactive';

/** PURE - menyempitkan `string` dari Tabs ke filter status TANPA cast `as`. */
function isStatusFilter(value: string): value is BomStatusFilter {
  return STATUS_IDS.includes(value);
}

/** PURE - filter status UI → param `active` backend (`null` = tidak difilter). */
function activeParamForStatus(status: BomStatusFilter): boolean | null {
  if (status === 'active') return true;
  if (status === 'inactive') return false;

  return null;
}

/** PURE - label produk dari kode/nama baris (`-` kalau BOM belum berproduk). */
function productLabel(row: MasterBomRow): string {
  if (row.product_code === null && row.product_name === null) return '-';

  return productOptionLabel({ code: row.product_code ?? '', name: row.product_name ?? '' });
}

const COLUMNS: DenseTableColumn<MasterBomRow>[] = [
  {
    key: 'code',
    label: 'Kode',
    render: (row) => <span className="font-mono tabular-nums">{row.code}</span>,
  },
  { key: 'name', label: 'Nama' },
  { key: 'product_code', label: 'Produk', render: (row) => productLabel(row) },
  {
    key: 'output_qty',
    label: 'Output',
    align: 'right',
    render: (row) => (
      <span className="tabular-nums">
        {`${String(row.output_qty)} ${row.uom_code ?? ''}`.trim()}
      </span>
    ),
  },
  {
    key: 'lines_count',
    label: 'Komponen',
    align: 'right',
    render: (row) => <span className="tabular-nums">{row.lines_count}</span>,
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

const CSV_COLUMNS: CsvColumn<MasterBomRow>[] = [
  { key: 'code', label: 'code' },
  { key: 'name', label: 'name' },
  { key: 'product_code', label: 'product_code' },
  { key: 'output_qty', label: 'output_qty' },
  { key: 'uom_code', label: 'uom_code' },
  { key: 'lines_count', label: 'lines_count' },
  { key: 'active', label: 'active' },
  { key: 'odoo_id', label: 'odoo_id' },
];

export function BomsPage() {
  const client = useApiClient();
  const navigate = useNavigate();
  const { exportCsv } = useCsvExport();

  const [search, setSearch] = useState('');
  const [status, setStatus] = useState<BomStatusFilter>('all');

  const { data, isLoading, isFetching, error, refetch } = useQuery({
    queryKey: ['master-boms', search, status],
    queryFn: () =>
      fetchBoms(client, {
        search,
        active: activeParamForStatus(status),
        limit: BOMS_LIMIT_MAX,
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
        title="Master BOM"
        subtitle={`Bill of Material MES — ${String(data?.total_count ?? 0)} baris`}
        breadcrumb={[
          { label: 'Inventory', href: '/inventory/products' },
          { label: 'Master BOM' },
        ]}
        actions={
          <Button icon={Plus} onClick={() => navigate('/master/boms/new')}>
            BOM Baru
          </Button>
        }
      />

      <section className={cn(CARD, 'flex flex-col gap-3 p-4')}>
        <TableToolbar
          search={search}
          onSearchChange={handleSearch}
          searchLabel="Cari BOM"
          searchPlaceholder="Cari kode / nama / produk"
          filters={STATUS_FILTERS}
          activeFilter={status}
          onFilterChange={handleStatus}
          exportDisabled={rows.length === 0}
          onExport={() => exportCsv(rows, 'master-boms.csv', CSV_COLUMNS)}
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
          error={error === null ? null : 'Gagal memuat master BOM.'}
          onRetry={() => {
            void refetch();
          }}
          onRowClick={(row) => navigate(`/master/boms/${String(row.id)}`)}
          emptyMessage={
            hasFilter
              ? 'Tidak ada BOM yang cocok dengan filter.'
              : 'Belum ada BOM. Tambahkan lewat tombol "BOM Baru".'
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
