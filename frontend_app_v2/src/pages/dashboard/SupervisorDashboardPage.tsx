import { useQuery } from '@tanstack/react-query';
import { Activity, AlertOctagon, CheckCircle2, TrendingUp } from 'lucide-react';
import { Button } from '@/components/atoms/Button';
import { Spinner } from '@/components/atoms/Spinner';
import { BarChart, BarChartCard } from '@/components/molecules/BarChart';
import { BufferQueueTable } from '@/components/molecules/BufferQueueTable';
import { KpiCard } from '@/components/molecules/KpiCard';
import { PageHeader } from '@/components/molecules/PageHeader';
import { fetchDashboardSummary } from '@/api/dashboard';
import { fetchBufferQueue } from '@/api/bufferQueue';
import { fetchOnTimeDelivery } from '@/api/reports';
import { useApiClient } from '@/hooks/useApiClient';

/**
 * SupervisorDashboardPage - route `/dashboard` (supervisor/admin/owner).
 *
 * F2C.2: `dashboard` + `bufferQueue` = REAL; `reportsOTD` masih dummy.
 */

export function SupervisorDashboardPage() {
  const client = useApiClient();

  const summary = useQuery({
    queryKey: ['dashboard-summary'],
    queryFn: () => fetchDashboardSummary(client),
    staleTime: 15_000,
  });

  const queue = useQuery({
    queryKey: ['buffer-queue'],
    queryFn: () => fetchBufferQueue(client),
    staleTime: 15_000,
  });

  const onTimeDelivery = useQuery({
    queryKey: ['reports-otd'],
    queryFn: () => fetchOnTimeDelivery(client),
    staleTime: 30_000,
  });

  const isLoading = summary.isLoading || queue.isLoading || onTimeDelivery.isLoading;
  const hasError = summary.error !== null || queue.error !== null || onTimeDelivery.error !== null;

  const retry = (): void => {
    void summary.refetch();
    void queue.refetch();
    void onTimeDelivery.refetch();
  };

  if (isLoading) {
    return (
      <div className="flex min-h-full items-center justify-center p-8">
        <Spinner size="lg" />
      </div>
    );
  }

  if (hasError || summary.data === undefined || queue.data === undefined) {
    return (
      <div className="flex min-h-full flex-col items-center justify-center gap-4 p-8">
        <p role="alert" className="text-sm font-semibold text-foreground">
          Gagal memuat data supervisor.
        </p>
        <Button variant="secondary" onClick={retry}>
          Coba Lagi
        </Button>
      </div>
    );
  }

  const data = summary.data;
  const queueData = queue.data;
  const otd = onTimeDelivery.data;
  const alert = data.alerts[0];
  const wipSeries = data.trend.map((point) => ({ label: point.date, value: point.wip }));

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <PageHeader
        title="Supervisor Dashboard"
        subtitle="Agregat lantai produksi + antrean antar work center"
        breadcrumb={[{ label: 'Dashboard' }, { label: 'Supervisor' }]}
        actions={
          <Button
            variant="secondary"
            size="sm"
            loading={queue.isFetching}
            onClick={() => {
              void queue.refetch();
            }}
          >
            Refresh Antrean
          </Button>
        }
      />

      <section className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-4">
        <KpiCard
          label="Total WIP"
          value={data.wip_qty.toLocaleString('id-ID')}
          trend={`${data.fg_qty.toLocaleString('id-ID')} FG selesai`}
          tone="blue"
          icon={Activity}
        />
        <KpiCard
          label="Bottleneck"
          value={alert === undefined ? 'Aman' : alert.code}
          trend={`${data.alerts.length} alert`}
          tone="coral"
          icon={AlertOctagon}
        />
        <KpiCard
          label="Line Efficiency"
          value={`${data.line_efficiency.pct}%`}
          trend={`${data.line_efficiency.delta >= 0 ? '+' : ''}${data.line_efficiency.delta}% vs 7 hari lalu`}
          tone="blue"
          icon={TrendingUp}
        />
        <KpiCard
          label="On-Time Delivery"
          value={otd === undefined ? '-' : `${otd.otd_pct}%`}
          trend={otd === undefined ? 'memuat...' : 'agregat global'}
          tone={otd !== undefined && otd.otd_pct >= 95 ? 'blue' : 'coral'}
          icon={CheckCircle2}
        />
      </section>

      <BarChartCard title="Tren WIP (7 hari)" hint="snapshot akhir hari">
        <BarChart
          data={wipSeries}
          valueFormatter={(value) => `${value} bundle`}
          emptyMessage="Belum ada seri WIP."
        />
      </BarChartCard>

      <section className="flex flex-col gap-2">
        <h2 className="text-sm font-semibold tracking-tight text-foreground">
          Antrean Buffer (semua work center)
        </h2>
        <BufferQueueTable
          rows={queueData.rows}
          onRefresh={() => {
            void queue.refetch();
          }}
        />
      </section>
    </div>
  );
}
