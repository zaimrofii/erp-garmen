import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link, useParams } from 'react-router-dom';
import { ArrowLeft, RefreshCw } from 'lucide-react';
import { Button } from '@/components/atoms/Button';
import { Input } from '@/components/atoms/Input';
import { Select, type SelectOption } from '@/components/atoms/Select';
import { DenseTable, type DenseTableColumn } from '@/components/molecules/DenseTable';
import { PageHeader } from '@/components/molecules/PageHeader';
import {
  fetchAnalyticsMetric,
  type AnalyticsGroupBy,
  type AnalyticsMetricMetadata,
  type AnalyticsMetricRow,
} from '@/api/analytics';
import { useApiClient } from '@/hooks/useApiClient';
import { cn } from '@/lib/cn';
import { CARD } from '@/lib/tokens';

/**
 * AnalyticsMetricDetailPage — route `/analytics/metrics/:metricId` (Sprint C.3).
 *
 * Filter server: `?period=YYYY-MM`, `?group_by=period|work_center|line`.
 * Export sengaja DISABLED (backlog; pola H4.1 sebelum H4.8).
 */
const GROUP_BY_OPTIONS: SelectOption[] = [
  { value: 'period', label: 'Periode' },
  { value: 'work_center', label: 'Work Center' },
  { value: 'line', label: 'Line' },
];

const COLUMNS: DenseTableColumn<AnalyticsMetricRow>[] = [
  {
    key: 'label',
    label: 'Grup',
    render: (row) => <span className="font-medium text-foreground">{row.label}</span>,
  },
  {
    key: 'value',
    label: 'Nilai',
    align: 'right',
    render: (row) => (
      <span>{row.value === null ? '—' : row.value.toLocaleString('id-ID')}</span>
    ),
  },
];

function readMetadata(summary: Record<string, unknown>): AnalyticsMetricMetadata | null {
  const raw = summary['metadata'];
  if (typeof raw !== 'object' || raw === null) return null;
  return raw as AnalyticsMetricMetadata;
}

export function AnalyticsMetricDetailPage() {
  const { metricId = '' } = useParams<{ metricId: string }>();
  const client = useApiClient();
  const [period, setPeriod] = useState('');
  const [groupBy, setGroupBy] = useState<AnalyticsGroupBy>('period');
  const [nonce, setNonce] = useState(0);
  const [nocache, setNocache] = useState(false);

  const query = useQuery({
    queryKey: ['analytics-metric', metricId, period, groupBy, nonce, nocache],
    queryFn: () =>
      fetchAnalyticsMetric(client, metricId, {
        period: period || null,
        groupBy,
        nocache,
      }),
    enabled: metricId !== '',
    staleTime: 60_000,
  });

  const data = query.data;
  const disabled = data !== undefined && data.enabled === false;
  const metadata = data === undefined ? null : readMetadata(data.summary);

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <PageHeader
        title={metadata?.label ?? 'Detail Metrik'}
        subtitle={
          metadata === null
            ? 'Metrik analytics'
            : `${metadata.metric_id} · ${metadata.granularity} · formula ${metadata.formula_version}`
        }
        breadcrumb={[
          { label: 'Analitik', href: '/analytics' },
          { label: 'Detail' },
        ]}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Link to="/analytics">
              <Button variant="secondary" icon={ArrowLeft}>
                Kembali
              </Button>
            </Link>
            <Button
              variant="secondary"
              icon={RefreshCw}
              onClick={() => {
                setNocache(true);
                setNonce((value) => value + 1);
              }}
            >
              Muat Ulang
            </Button>
            <Button variant="secondary" disabled title="Akan tersedia di sprint berikutnya">
              Export
            </Button>
          </div>
        }
      />

      <section className={cn(CARD, 'flex flex-wrap items-end gap-3')}>
        <Input
          type="month"
          label="Periode"
          value={period}
          className="w-40"
          onChange={(event) => setPeriod(event.target.value)}
        />
        <Select
          label="Kelompok"
          options={GROUP_BY_OPTIONS}
          value={groupBy}
          className="w-48"
          onChange={(event) => setGroupBy(event.target.value as AnalyticsGroupBy)}
        />
      </section>

      {disabled ? (
        <section
          data-analytics-disabled="true"
          className={cn(CARD, 'border-l-4 border-l-accent-coral text-sm')}
        >
          <p className="font-semibold text-foreground">
            Analitik dinonaktifkan — data belum siap.
          </p>
          <p className="mt-1 text-muted-foreground">
            Aktifkan di{' '}
            <Link className="text-accent-blue hover:underline" to="/settings/analytics">
              Pengaturan → Analitik
            </Link>
            .
          </p>
          {data?.historical_data_available ? (
            <p className="mt-2 text-xs text-muted-foreground">
              Tab Data Historis: endpoint snapshot menyusul (backlog Sprint C/D).
            </p>
          ) : null}
        </section>
      ) : null}

      {query.error !== null ? (
        <p className="text-sm text-accent-coral">Gagal memuat metrik. Coba lagi.</p>
      ) : null}

      {data !== undefined && data.enabled ? (
        <section className={cn(CARD, 'p-0')}>
          <DenseTable columns={COLUMNS} rows={data.rows} />
        </section>
      ) : null}
    </div>
  );
}
