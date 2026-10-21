import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { RefreshCw } from 'lucide-react';
import { Button } from '@/components/atoms/Button';
import { DenseTable, type DenseTableColumn } from '@/components/molecules/DenseTable';
import { PageHeader } from '@/components/molecules/PageHeader';
import { fetchAnalyticsMetrics, type AnalyticsMetricRow } from '@/api/analytics';
import { useApiClient } from '@/hooks/useApiClient';
import { cn } from '@/lib/cn';
import { CARD } from '@/lib/tokens';

/**
 * AnalyticsPage — route `/analytics` (Sprint C.3).
 *
 * Read-only: GET `/api/v1/analytics/metrics/garment/`. Saat toggle OFF,
 * backend membalas 200 `enabled:false` → halaman menampilkan banner
 * penjelasan + link ke /settings/analytics (BUKAN tabel kosong tanpa alasan).
 */
export const ANALYTICS_PAGE_PATH = '/analytics';
const DOMAIN = 'garment';

const COLUMNS: DenseTableColumn<AnalyticsMetricRow>[] = [
  {
    key: 'label',
    label: 'Metrik',
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
  { key: 'unit', label: 'Satuan' },
  {
    key: 'action',
    label: '',
    render: (row) => (
      <Link
        className="text-sm text-accent-blue hover:underline"
        to={`/analytics/metrics/${encodeURIComponent(row.key)}`}
      >
        Lihat Detail
      </Link>
    ),
  },
];

export function AnalyticsPage() {
  const client = useApiClient();
  const [nocache, setNocache] = useState(false);
  const [nonce, setNonce] = useState(0);

  const query = useQuery({
    queryKey: ['analytics-metrics', DOMAIN, nocache, nonce],
    queryFn: () => fetchAnalyticsMetrics(client, DOMAIN, { nocache }),
    staleTime: 60_000,
  });

  const data = query.data;
  const disabled = data !== undefined && data.enabled === false;

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <PageHeader
        title="Analitik"
        subtitle="Metrik operasional produksi — read-only, event-driven"
        breadcrumb={[{ label: 'Analitik' }]}
        actions={
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
        }
      />

      {disabled ? (
        <section
          data-analytics-disabled="true"
          className={cn(CARD, 'border-l-4 border-l-accent-coral text-sm')}
        >
          <p className="font-semibold text-foreground">
            Analitik dinonaktifkan — data belum siap.
          </p>
          <p className="mt-1 text-muted-foreground">
            Hubungi admin untuk mengaktifkan di{' '}
            <Link className="text-accent-blue hover:underline" to="/settings/analytics">
              Pengaturan → Analitik
            </Link>
            .
          </p>
          {data.historical_data_available ? (
            <p className="mt-2 text-xs text-muted-foreground">
              Snapshot historis masih tersimpan.
            </p>
          ) : (
            <p className="mt-2 text-xs text-muted-foreground">
              Belum ada data historis tersimpan.
            </p>
          )}
        </section>
      ) : null}

      {query.error !== null ? (
        <p className="text-sm text-accent-coral">
          Gagal memuat analitik. Coba lagi.
        </p>
      ) : null}

      {data !== undefined && data.enabled ? (
        <section className={cn(CARD, 'p-0')}>
          <DenseTable columns={COLUMNS} rows={data.rows} />
        </section>
      ) : null}
    </div>
  );
}
