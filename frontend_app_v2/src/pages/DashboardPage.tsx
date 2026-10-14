import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  AlertOctagon,
  ChevronRight,
  ListChecks,
  Package,
  ScanLine,
  TrendingUp,
} from 'lucide-react';
import { Button } from '@/components/atoms/Button';
import { Spinner } from '@/components/atoms/Spinner';
import { BarChart, BarChartCard } from '@/components/molecules/BarChart';
import { KpiCard } from '@/components/molecules/KpiCard';
import { PageHeader } from '@/components/molecules/PageHeader';
import { StatusChip } from '@/components/molecules/StatusChip';
import { fetchDashboardSummary } from '@/api/dashboard';
import { fetchBufferQueue, type BufferQueueBundle } from '@/api/bufferQueue';
import { useApiClient } from '@/hooks/useApiClient';
import { cn } from '@/lib/cn';
import { CARD, PILL_GHOST, PILL_PRIMARY, PILL_SECONDARY } from '@/lib/tokens';
import type { StatusChipStatus } from '@/lib/state-display';

/**
 * DashboardPage - route `/` (overview pabrik, semua role).
 * F2C.2: data NYATA `GET /dashboard/summary/` (B1 + G1) & `GET /production/buffer-queue/`.
 */

const QUEUE_PREVIEW_ROWS = 5;

const STATE_CHIP: Record<string, StatusChipStatus> = {
  DRAFT: 'delay',
  CUTTING: 'delay',
  SEWING: 'on_track',
  QC: 'on_track',
  DONE: 'on_track',
};

function formatToday(): string {
  return new Date().toLocaleDateString('id-ID', {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
    year: 'numeric',
  });
}

export function DashboardPage() {
  const navigate = useNavigate();
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

  const isLoading = summary.isLoading || queue.isLoading;
  const hasError = summary.error !== null || queue.error !== null;

  const retry = (): void => {
    void summary.refetch();
    void queue.refetch();
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
          Gagal memuat ringkasan dashboard.
        </p>
        <Button variant="secondary" onClick={retry}>
          Coba Lagi
        </Button>
      </div>
    );
  }

  const data = summary.data;
  const queueData = queue.data;

  const preview: { wc_code: string; bundle: BufferQueueBundle }[] = queueData.rows
    .flatMap((row) => row.bundles.map((bundle) => ({ wc_code: row.wc_code, bundle })))
    .slice(0, QUEUE_PREVIEW_ROWS);

  const wipSeries = data.trend.map((point) => ({ label: point.date, value: point.wip }));
  const efficiencyTrend = `${data.line_efficiency.delta >= 0 ? '+' : ''}${
    data.line_efficiency.delta
  }% vs 7 hari lalu`;
  const alert = data.alerts[0];

  return (
    <div className="flex flex-col gap-4 p-4 md:p-6 lg:p-8">
      <PageHeader
        title="Dashboard Produksi"
        subtitle={`Ringkasan pabrik - ${formatToday()}`}
        breadcrumb={[{ label: 'Dashboard' }]}
        actions={
          <>
            <button
              type="button"
              className={cn(PILL_SECONDARY, 'gap-2 px-3 py-2 text-sm')}
              onClick={() => navigate('/production/buffer-queue')}
            >
              <ListChecks className="h-4 w-4" aria-hidden="true" />
              Lihat Antrean
            </button>
            <button
              type="button"
              className={cn(PILL_PRIMARY, 'gap-2 px-3 py-2 text-sm')}
              onClick={() => navigate('/production/scan')}
            >
              <ScanLine className="h-4 w-4" aria-hidden="true" />
              Scan Bundle
            </button>
          </>
        }
      />

      <section className="grid grid-cols-1 gap-2 lg:grid-cols-3">
        <KpiCard
          label="Total WIP"
          value={data.wip_qty.toLocaleString('id-ID')}
          trend={`${data.fg_qty.toLocaleString('id-ID')} FG selesai`}
          tone="blue"
          icon={Package}
        />
        <KpiCard
          label="Bottleneck"
          value={alert === undefined ? 'Aman' : alert.code}
          trend={data.alerts.length === 0 ? 'tidak ada alert' : `${data.alerts.length} alert`}
          tone="coral"
          icon={AlertOctagon}
        />
        <KpiCard
          label="Line Efficiency"
          value={`${data.line_efficiency.pct}%`}
          trend={efficiencyTrend}
          tone="blue"
          icon={TrendingUp}
        />
      </section>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <BarChartCard title="Tren WIP (7 hari)" hint="snapshot akhir hari">
          <BarChart
            data={wipSeries}
            valueFormatter={(value) => `${value} bundle`}
            emptyMessage="Belum ada seri WIP."
          />
        </BarChartCard>

        <section className={cn(CARD, 'flex flex-col gap-4')}>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-lg font-semibold tracking-tight text-foreground">
              Antrean Terkini
            </h2>
            <button
              type="button"
              className={cn(PILL_GHOST, 'gap-1 px-2 py-1 text-xs')}
              onClick={() => navigate('/production/buffer-queue')}
            >
              Lihat Semua
              <ChevronRight className="h-3.5 w-3.5" aria-hidden="true" />
            </button>
          </div>

          {preview.length > 0 ? (
            <ul className="flex flex-col gap-2">
              {preview.map(({ wc_code, bundle }) => (
                <li
                  key={`${wc_code}-${bundle.code}`}
                  className="flex items-center justify-between gap-2 rounded-lg border border-border/40 px-3 py-2"
                >
                  <div className="flex flex-col">
                    <span className="font-mono text-xs font-semibold tabular-nums text-foreground">
                      {bundle.code}
                    </span>
                    <span className="text-[11px] text-muted-foreground">
                      {wc_code} - {bundle.qty} pcs
                    </span>
                  </div>
                  <StatusChip
                    status={STATE_CHIP[bundle.status] ?? 'on_track'}
                    label={bundle.status}
                  />
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted-foreground">Tidak ada antrean saat ini.</p>
          )}
        </section>
      </div>

      {alert === undefined ? null : (
        <div
          role="alert"
          className="flex items-start gap-3 rounded-lg border border-accent-coral/30 bg-accent-coral/10 p-4"
        >
          <AlertOctagon className="mt-0.5 h-4 w-4 shrink-0 text-accent-coral" aria-hidden="true" />
          <p className="text-sm text-foreground">
            <span className="font-semibold">{alert.code}</span> - {alert.message}
          </p>
        </div>
      )}
    </div>
  );
}
