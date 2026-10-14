import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Timer, TrendingDown, TrendingUp } from 'lucide-react';
import { DenseTable, type DenseTableColumn } from '@/components/molecules/DenseTable';
import { KpiCard } from '@/components/molecules/KpiCard';
import { PageHeader } from '@/components/molecules/PageHeader';
import { PaginationBar } from '@/components/molecules/PaginationBar';
import { TableToolbar } from '@/components/molecules/TableToolbar';
import { fetchLeadTime, type LeadTimeRow } from '@/api/reports';
import { useApiClient } from '@/hooks/useApiClient';
import { useCsvExport, type CsvColumn } from '@/hooks/use-csv-export';
import { usePagination } from '@/hooks/use-pagination';
import { cn } from '@/lib/cn';
import { CARD } from '@/lib/tokens';

/**
 * LeadTimePage - route `/reports/lead-time` (supervisor/admin/owner).
 *
 * REAL (F3A.CLOSE): `GET /api/v1/reports/lead-time/` (B19) — per bundle selesai:
 * `hours_total` + `stages[{wc_code, minutes}]`. `avg_hours` = rata-rata backend
 * (SUDAH memperhitungkan seluruh baris, bukan hanya halaman).
 */

const ROW_LIMIT = 200;
const EMPTY_ROWS: LeadTimeRow[] = [];

function formatNumber(value: number): string {
  return value.toLocaleString('id-ID', {
    minimumFractionDigits: Number.isInteger(value) ? 0 : 1,
    maximumFractionDigits: 1,
  });
}

function hoursToDays(hours: number): number {
  return hours / 24;
}

const COLUMNS: DenseTableColumn<LeadTimeRow>[] = [
  {
    key: 'bundle_code',
    label: 'Bundle',
    render: (row) => <span className="font-mono tabular-nums">{row.bundle_code}</span>,
  },
  {
    key: 'stages',
    label: 'Stage',
    align: 'right',
    render: (row) => `${row.stages.length} stage`,
  },
  {
    key: 'hours_total',
    label: 'Lead Time',
    align: 'right',
    render: (row) => (
      <span className="font-medium tabular-nums">
        {formatNumber(row.hours_total)} jam
        <span className="ml-1 text-xs font-normal text-muted-foreground">
          ({formatNumber(hoursToDays(row.hours_total))} hari)
        </span>
      </span>
    ),
  },
  {
    key: 'finished_at',
    label: 'Selesai',
    render: (row) =>
      row.finished_at === null ? '—' : new Date(row.finished_at).toLocaleString('id-ID'),
  },
];

const CSV_COLUMNS: CsvColumn<LeadTimeRow>[] = [
  { key: 'bundle_code', label: 'bundle_code' },
  { key: 'hours_total', label: 'hours_total' },
  { key: 'finished_at', label: 'finished_at' },
];

export function LeadTimePage() {
  const client = useApiClient();
  const [search, setSearch] = useState('');

  const report = useQuery({
    queryKey: ['reports-lead-time'],
    queryFn: () => fetchLeadTime(client, { limit: ROW_LIMIT }),
    staleTime: 30_000,
  });

  const { exportCsv } = useCsvExport();
  const rows = report.data?.rows ?? EMPTY_ROWS;
  const avgHours = report.data?.avg_hours ?? 0;

  const filtered = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (needle.length === 0) return rows;

    return rows.filter((row) => row.bundle_code.toLowerCase().includes(needle));
  }, [rows, search]);

  const pagination = usePagination(filtered, { pageSize: 20 });

  const hours = filtered.map((row) => row.hours_total);
  const hasRows = hours.length > 0;
  const maxHours = hasRows ? Math.max(...hours) : 0;
  const minHours = hasRows ? Math.min(...hours) : 0;

  function handleSearch(value: string): void {
    setSearch(value);
    pagination.reset();
  }

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <PageHeader
        title="Lead Time"
        subtitle="Waktu tempuh bundle dari dibuat sampai selesai"
        breadcrumb={[{ label: 'Reports' }, { label: 'Lead Time' }]}
      />

      <section className="grid grid-cols-1 gap-2 sm:grid-cols-3">
        <KpiCard
          label="Rata-rata Lead Time"
          value={`${formatNumber(hoursToDays(avgHours))} hari`}
          trend={`${formatNumber(avgHours)} jam rata-rata`}
          tone="blue"
          icon={Timer}
        />
        <KpiCard
          label="Max Lead Time (periode)"
          value={hasRows ? `${formatNumber(hoursToDays(maxHours))} hari` : '-'}
          trend={hasRows ? `${formatNumber(maxHours)} jam` : 'tidak ada baris'}
          tone={hasRows ? 'coral' : 'muted'}
          icon={TrendingUp}
        />
        <KpiCard
          label="Min Lead Time (periode)"
          value={hasRows ? `${formatNumber(hoursToDays(minHours))} hari` : '-'}
          trend={hasRows ? `${formatNumber(minHours)} jam` : 'tidak ada baris'}
          tone="muted"
          icon={TrendingDown}
        />
      </section>

      <TableToolbar
        search={search}
        onSearchChange={handleSearch}
        searchLabel="Cari bundle"
        searchPlaceholder="Cari kode bundle"
        exportDisabled={filtered.length === 0}
        onExport={() => exportCsv(filtered, 'reports-lead-time.csv', CSV_COLUMNS)}
        refreshing={report.isFetching}
        onRefresh={() => {
          void report.refetch();
        }}
      />

      <section className={cn(CARD, 'p-0')}>
        <DenseTable
          columns={COLUMNS}
          rows={pagination.pageRows}
          loading={report.isLoading}
          error={report.error === null ? null : 'Gagal memuat detail lead time.'}
          onRetry={() => {
            void report.refetch();
          }}
          emptyMessage="Belum ada bundle selesai pada periode ini."
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
