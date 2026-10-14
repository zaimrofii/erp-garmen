import { useQuery } from '@tanstack/react-query';
import { Activity, Clock, PackageCheck } from 'lucide-react';
import { BarChart, BarChartCard } from '@/components/molecules/BarChart';
import { DenseTable, type DenseTableColumn } from '@/components/molecules/DenseTable';
import { KpiCard } from '@/components/molecules/KpiCard';
import { PageHeader } from '@/components/molecules/PageHeader';
import { fetchLineEfficiency, type LineEfficiencyRow } from '@/api/reports';
import { useApiClient } from '@/hooks/useApiClient';
import { cn } from '@/lib/cn';
import { CARD } from '@/lib/tokens';

/**
 * LineEfficiencyPage - route `/reports/line-efficiency` (F2C.2).
 * Data NYATA `GET /api/v1/reports/line-efficiency/` (B13 + G4b).
 */

const TARGET_EFFICIENCY = 85;

const COLUMNS: DenseTableColumn<LineEfficiencyRow>[] = [
  { key: 'wc_code', label: 'Work Center' },
  { key: 'bundles_done', label: 'Selesai', align: 'right' },
  {
    key: 'avg_min_per_bundle',
    label: 'Rata-rata (mnt)',
    align: 'right',
    render: (row) => row.avg_min_per_bundle,
  },
  {
    key: 'efficiency_pct',
    label: 'Efficiency',
    align: 'right',
    render: (row) => (
      <span
        className={cn(
          'font-medium tabular-nums',
          row.efficiency_pct < TARGET_EFFICIENCY ? 'text-accent-coral' : 'text-foreground',
        )}
      >
        {row.efficiency_pct}%
      </span>
    ),
  },
];

export function LineEfficiencyPage() {
  const client = useApiClient();

  const report = useQuery({
    queryKey: ['reports-line-efficiency'],
    queryFn: () => fetchLineEfficiency(client),
    staleTime: 30_000,
  });

  const rows = report.data?.rows ?? [];
  const average =
    rows.length === 0 ? 0 : rows.reduce((total, row) => total + row.efficiency_pct, 0) / rows.length;
  const totalDone = rows.reduce((total, row) => total + row.bundles_done, 0);
  const lowCount = rows.filter((row) => row.efficiency_pct < TARGET_EFFICIENCY).length;
  const series = rows.map((row) => ({ label: row.wc_code, value: row.efficiency_pct }));

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <PageHeader
        title="Line Efficiency"
        subtitle="Efisiensi per work center"
        breadcrumb={[{ label: 'Reports' }, { label: 'Line Efficiency' }]}
      />

      <section className="grid grid-cols-1 gap-2 sm:grid-cols-3">
        <KpiCard
          label="Line Efficiency"
          value={`${average.toLocaleString('id-ID', { maximumFractionDigits: 1 })}%`}
          trend={`${rows.length} work center`}
          tone="blue"
          icon={Activity}
        />
        <KpiCard
          label="Total Selesai (periode)"
          value={totalDone.toLocaleString('id-ID')}
          trend="bundle"
          tone="muted"
          icon={PackageCheck}
        />
        <KpiCard
          label="Di Bawah Target"
          value={String(lowCount)}
          trend={`target ${TARGET_EFFICIENCY}%`}
          tone={lowCount > 0 ? 'coral' : 'muted'}
          icon={Clock}
        />
      </section>

      <BarChartCard title="Efisiensi per Work Center" hint="snapshot saat ini">
        <BarChart
          data={series}
          max={100}
          valueFormatter={(value) => `${value}%`}
          emptyMessage="Belum ada data efisiensi."
        />
      </BarChartCard>

      <section className={cn(CARD, 'p-0')}>
        <DenseTable
          columns={COLUMNS}
          rows={rows}
          loading={report.isLoading}
          error={report.error === null ? null : 'Gagal memuat laporan efisiensi.'}
          onRetry={() => {
            void report.refetch();
          }}
          emptyMessage="Belum ada data work center."
        />
      </section>
    </div>
  );
}
