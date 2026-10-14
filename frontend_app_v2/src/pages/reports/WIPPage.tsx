import { useQuery } from '@tanstack/react-query';
import { Flame, Layers } from 'lucide-react';
import { BarChart, BarChartCard } from '@/components/molecules/BarChart';
import { DenseTable, type DenseTableColumn } from '@/components/molecules/DenseTable';
import { KpiCard } from '@/components/molecules/KpiCard';
import { PageHeader } from '@/components/molecules/PageHeader';
import { fetchWip, type WipRow } from '@/api/reports';
import { useApiClient } from '@/hooks/useApiClient';
import { cn } from '@/lib/cn';
import { CARD } from '@/lib/tokens';

/**
 * WIPPage - route `/reports/wip` (F2C.2).
 * Data NYATA `GET /api/v1/reports/wip/` (B16 + G4).
 */

const COLUMNS: DenseTableColumn<WipRow>[] = [
  { key: 'wc_code', label: 'Work Center' },
  { key: 'wip_qty', label: 'WIP (pcs)', align: 'right' },
  { key: 'queue_depth', label: 'Antrean', align: 'right' },
];

export function WIPPage() {
  const client = useApiClient();

  const report = useQuery({
    queryKey: ['reports-wip'],
    queryFn: () => fetchWip(client),
    staleTime: 30_000,
  });

  const rows = report.data?.rows ?? [];
  const totalWip = report.data?.total_wip ?? 0;
  const average = rows.length === 0 ? 0 : totalWip / rows.length;
  const busiest = rows.reduce<WipRow | null>(
    (worst, row) => (worst === null || row.wip_qty > worst.wip_qty ? row : worst),
    null,
  );
  const series = rows.map((row) => ({ label: row.wc_code, value: row.wip_qty }));

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <PageHeader
        title="Work In Progress"
        subtitle="Sebaran bundle WIP antar work center"
        breadcrumb={[{ label: 'Reports' }, { label: 'WIP' }]}
      />

      <section className="grid grid-cols-1 gap-2 sm:grid-cols-3">
        <KpiCard
          label="Total WIP"
          value={`${totalWip.toLocaleString('id-ID')} pcs`}
          trend={`${rows.length} work center`}
          tone="blue"
          icon={Layers}
        />
        <KpiCard
          label="WC Paling Padat"
          value={busiest === null ? '—' : busiest.wc_code}
          trend={busiest === null ? 'tidak ada data' : `${busiest.wip_qty} pcs WIP`}
          tone="coral"
          icon={Flame}
        />
        <KpiCard
          label="Rata-rata WIP / WC"
          value={`${average.toLocaleString('id-ID', { maximumFractionDigits: 1 })} pcs`}
          trend="snapshot saat ini"
          tone="muted"
          icon={Layers}
        />
      </section>

      <BarChartCard title="Sebaran WIP per Work Center" hint="snapshot saat ini">
        <BarChart
          data={series}
          valueFormatter={(value) => `${value.toLocaleString('id-ID')} pcs`}
          emptyMessage="Belum ada data per WC."
        />
      </BarChartCard>

      <section className={cn(CARD, 'p-0')}>
        <DenseTable
          columns={COLUMNS}
          rows={rows}
          loading={report.isLoading}
          error={report.error === null ? null : 'Gagal memuat laporan WIP.'}
          onRetry={() => {
            void report.refetch();
          }}
          emptyMessage="Tidak ada work center dengan WIP."
        />
      </section>
    </div>
  );
}
