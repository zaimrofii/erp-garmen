import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { CircleCheck, Target, Timer } from 'lucide-react';
import { Badge, type BadgeTone } from '@/components/atoms/Badge';
import { DenseTable, type DenseTableColumn } from '@/components/molecules/DenseTable';
import { KpiCard } from '@/components/molecules/KpiCard';
import { PageHeader } from '@/components/molecules/PageHeader';
import { PaginationBar } from '@/components/molecules/PaginationBar';
import { TableToolbar } from '@/components/molecules/TableToolbar';
import { fetchOnTimeDelivery, type OtdRow } from '@/api/reports';
import { useApiClient } from '@/hooks/useApiClient';
import { useCsvExport, type CsvColumn } from '@/hooks/use-csv-export';
import { usePagination } from '@/hooks/use-pagination';
import { cn } from '@/lib/cn';
import { CARD } from '@/lib/tokens';

/**
 * OnTimeDeliveryPage - route `/reports/on-time-delivery` (supervisor/admin/owner).
 *
 * REAL (F3A.CLOSE): `GET /api/v1/reports/on-time-delivery/` (B20) — satu baris per
 * `WorkOrder` DONE; `finished_at` = event FINISH terakhir bundle-nya (fallback
 * `WorkOrder.updated_at`). `otd_pct` agregat datang dari backend (bukan hitung UI).
 */

const ROW_LIMIT = 200;
const EMPTY_ROWS: OtdRow[] = [];

const STATUS_TONE: Record<'on_time' | 'late' | 'unknown', BadgeTone> = {
  on_time: 'blue',
  late: 'coral',
  unknown: 'muted',
};

const STATUS_LABEL: Record<'on_time' | 'late' | 'unknown', string> = {
  on_time: 'Tepat Waktu',
  late: 'Terlambat',
  unknown: 'Belum Jelas',
};

function statusOf(row: OtdRow): 'on_time' | 'late' | 'unknown' {
  if (row.on_time === true) return 'on_time';
  if (row.on_time === false) return 'late';
  return 'unknown';
}

function formatDate(value: string | null): string {
  return value === null ? '—' : new Date(value).toLocaleDateString('id-ID');
}

function formatNumber(value: number): string {
  return value.toLocaleString('id-ID', {
    minimumFractionDigits: Number.isInteger(value) ? 0 : 1,
    maximumFractionDigits: 1,
  });
}

const COLUMNS: DenseTableColumn<OtdRow>[] = [
  {
    key: 'order_code',
    label: 'Order',
    render: (row) => <span className="font-mono tabular-nums">{row.order_code}</span>,
  },
  { key: 'deadline', label: 'Deadline', render: (row) => formatDate(row.deadline) },
  { key: 'finished_at', label: 'Selesai', render: (row) => formatDate(row.finished_at) },
  {
    key: 'on_time',
    label: 'Status',
    render: (row) => {
      const status = statusOf(row);
      return <Badge tone={STATUS_TONE[status]}>{STATUS_LABEL[status]}</Badge>;
    },
  },
  {
    key: 'delay_hours',
    label: 'Delay',
    align: 'right',
    render: (row) =>
      row.delay_hours <= 0 ? (
        <span className="text-muted-foreground">0 jam</span>
      ) : (
        <span className="font-medium tabular-nums text-accent-coral">
          +{formatNumber(row.delay_hours)} jam
        </span>
      ),
  },
];

const CSV_COLUMNS: CsvColumn<OtdRow>[] = [
  { key: 'order_code', label: 'order_code' },
  { key: 'deadline', label: 'deadline' },
  { key: 'finished_at', label: 'finished_at' },
  { key: 'delay_hours', label: 'delay_hours' },
];

export function OnTimeDeliveryPage() {
  const client = useApiClient();
  const [search, setSearch] = useState('');

  const report = useQuery({
    queryKey: ['reports-otd'],
    queryFn: () => fetchOnTimeDelivery(client, { limit: ROW_LIMIT }),
    staleTime: 30_000,
  });

  const { exportCsv } = useCsvExport();
  const rows = report.data?.rows ?? EMPTY_ROWS;
  const otdPct = report.data?.otd_pct ?? 0;

  const filtered = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (needle.length === 0) return rows;

    return rows.filter((row) => row.order_code.toLowerCase().includes(needle));
  }, [rows, search]);

  const pagination = usePagination(filtered, { pageSize: 20 });

  const onTimeCount = filtered.filter((row) => row.on_time === true).length;
  const lateCount = filtered.filter((row) => row.on_time === false).length;

  function handleSearch(value: string): void {
    setSearch(value);
    pagination.reset();
  }

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <PageHeader
        title="On-Time Delivery"
        subtitle="Ketepatan penyelesaian work order terhadap deadline order"
        breadcrumb={[{ label: 'Reports' }, { label: 'On-Time Delivery' }]}
      />

      <section className="grid grid-cols-1 gap-2 sm:grid-cols-3">
        <KpiCard
          label="On-Time Delivery"
          value={`${formatNumber(otdPct)}%`}
          trend={`${rows.length} work order dievaluasi`}
          tone={otdPct >= 95 ? 'blue' : 'coral'}
          icon={Target}
        />
        <KpiCard
          label="Tepat Waktu (periode)"
          value={String(onTimeCount)}
          trend={`dari ${filtered.length} baris tampil`}
          tone="blue"
          icon={CircleCheck}
        />
        <KpiCard
          label="Terlambat (periode)"
          value={String(lateCount)}
          trend={lateCount > 0 ? 'perlu tindak lanjut' : 'semua tepat waktu'}
          tone={lateCount > 0 ? 'coral' : 'muted'}
          icon={Timer}
        />
      </section>

      <TableToolbar
        search={search}
        onSearchChange={handleSearch}
        searchLabel="Cari order"
        searchPlaceholder="Cari kode order"
        exportDisabled={filtered.length === 0}
        onExport={() => exportCsv(filtered, 'reports-on-time-delivery.csv', CSV_COLUMNS)}
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
          error={report.error === null ? null : 'Gagal memuat detail on-time delivery.'}
          onRetry={() => {
            void report.refetch();
          }}
          emptyMessage="Belum ada work order selesai pada periode ini."
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
