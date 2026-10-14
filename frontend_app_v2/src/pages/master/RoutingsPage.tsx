import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Plus } from 'lucide-react';
import { Badge } from '@/components/atoms/Badge';
import { Button } from '@/components/atoms/Button';
import { DenseTable, type DenseTableColumn } from '@/components/molecules/DenseTable';
import { PageHeader } from '@/components/molecules/PageHeader';
import { PaginationBar } from '@/components/molecules/PaginationBar';
import { TableToolbar } from '@/components/molecules/TableToolbar';
import { fetchRoutings, ROUTINGS_LIMIT_MAX } from '@/api/masterRoutings';
import { useApiClient } from '@/hooks/useApiClient';
import { useCsvExport, type CsvColumn } from '@/hooks/use-csv-export';
import { usePagination } from '@/hooks/use-pagination';
import { cn } from '@/lib/cn';
import { routingStatusLabel } from '@/lib/master-routing';
import { CARD } from '@/lib/tokens';
import type { MasterRoutingRow } from '@/types/master-routing';

/**
 * RoutingsPage - route `/master/routings` (H1.9, app Inventory).
 *
 * MES = source of truth: daftar routing NYATA dari `GET /api/v1/settings/routing/`
 * (B22) lewat `api/masterRoutings.ts` (MODE.masterRoutings='real').
 *
 *   * list B22 **hanya** mendukung `limit`/`cursor` (shape F3A dipin 16 test) ⇒
 *     kotak cari menyaring **halaman yang termuat** (kode/nama) di klien, jadi
 *     kontrak backend tidak berubah;
 *   * kolom: Kode, Nama, Langkah (jumlah step + step awal/akhir), Status;
 *     **tanpa kolom Odoo ID** — H1.9 MES-only (Odoo 17 tidak punya DAG routing);
 *   * `capability_tags` **tidak** ada di baris list (field baru H1.9 hanya di
 *     detail) → tag tampil di halaman detail/form;
 *   * klik baris → detail; "Routing Baru" → `/new`; Export CSV.
 *
 * Guard route: `INVENTORY_ROLES` (konsisten H1.1–H1.8); izin **tulis** API
 * ADMIN/OWNER (POST B22 lama tetap `IsAuthenticated` — keputusan H1.9 di JSON).
 */

const EMPTY_ROWS: MasterRoutingRow[] = [];

const COLUMNS: DenseTableColumn<MasterRoutingRow>[] = [
  {
    key: 'code',
    label: 'Kode',
    render: (row) => <span className="font-mono tabular-nums">{row.code}</span>,
  },
  { key: 'name', label: 'Nama' },
  {
    key: 'steps',
    label: 'Langkah',
    render: (row) => {
      const initial = row.steps.filter((step) => step.is_initial).length;
      const terminal = row.steps.filter((step) => step.is_terminal).length;
      return (
        <span className="text-xs tabular-nums">
          {row.steps.length} step · {initial} awal · {terminal} akhir
        </span>
      );
    },
  },
  {
    key: 'is_active',
    label: 'Status',
    render: (row) => (
      <Badge tone={row.is_active ? 'blue' : 'muted'}>{routingStatusLabel(row.is_active)}</Badge>
    ),
  },
];

interface RoutingCsvRow {
  code: string;
  name: string;
  steps_count: number;
  active: boolean;
}

const CSV_COLUMNS: CsvColumn<RoutingCsvRow>[] = [
  { key: 'code', label: 'code' },
  { key: 'name', label: 'name' },
  { key: 'steps_count', label: 'steps_count' },
  { key: 'active', label: 'active' },
];

export function RoutingsPage() {
  const client = useApiClient();
  const navigate = useNavigate();
  const { exportCsv } = useCsvExport();

  const [search, setSearch] = useState('');

  const { data, isLoading, isFetching, error, refetch } = useQuery({
    queryKey: ['master-routings'],
    queryFn: () => fetchRoutings(client, { limit: ROUTINGS_LIMIT_MAX }),
    staleTime: 15_000,
  });

  const allRows = data?.rows ?? EMPTY_ROWS;
  const rows = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (!needle) return allRows;
    return allRows.filter(
      (row) =>
        row.code.toLowerCase().includes(needle) || row.name.toLowerCase().includes(needle),
    );
  }, [allRows, search]);

  const pagination = usePagination(rows, { pageSize: 20 });
  const hasFilter = search.trim().length > 0;

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <PageHeader
        title="Master Routing"
        subtitle={`Alur proses produksi (DAG) — ${String(data?.total_count ?? 0)} baris · MES-only, tidak disinkron ke Odoo`}
        breadcrumb={[
          { label: 'Inventory', href: '/inventory/products' },
          { label: 'Master Routing' },
        ]}
        actions={
          <Button icon={Plus} onClick={() => navigate('/master/routings/new')}>
            Routing Baru
          </Button>
        }
      />

      <section className={cn(CARD, 'flex flex-col gap-3 p-4')}>
        <TableToolbar
          search={search}
          onSearchChange={(value) => {
            setSearch(value);
            pagination.reset();
          }}
          searchLabel="Cari routing"
          searchPlaceholder="Cari kode / nama routing"
          exportDisabled={rows.length === 0}
          onExport={() =>
            exportCsv(
              rows.map((row) => ({
                code: row.code,
                name: row.name,
                steps_count: row.steps.length,
                active: row.is_active,
              })),
              'master-routings.csv',
              CSV_COLUMNS,
            )
          }
          refreshing={isFetching}
          onRefresh={() => {
            void refetch();
          }}
        />
        <p className="text-xs text-muted-foreground">
          Pencarian menyaring halaman yang termuat (endpoint list B22 hanya menerima
          `limit`/`cursor` supaya shape F3A tidak berubah).
        </p>
      </section>

      <section className={cn(CARD, 'p-0')}>
        <DenseTable
          columns={COLUMNS}
          rows={pagination.pageRows}
          loading={isLoading}
          error={error === null ? null : 'Gagal memuat master routing.'}
          onRetry={() => {
            void refetch();
          }}
          onRowClick={(row) => navigate(`/master/routings/${String(row.id)}`)}
          emptyMessage={
            hasFilter
              ? 'Tidak ada routing yang cocok dengan pencarian.'
              : 'Belum ada routing. Tambahkan lewat tombol "Routing Baru".'
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

