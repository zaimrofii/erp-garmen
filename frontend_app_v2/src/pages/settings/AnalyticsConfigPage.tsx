import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { RefreshCw } from 'lucide-react';
import { Button } from '@/components/atoms/Button';
import { Input } from '@/components/atoms/Input';
import { Toast, type ToastTone } from '@/components/atoms/Toast';
import { PageHeader } from '@/components/molecules/PageHeader';
import {
  disableAnalytics,
  enableAnalytics,
  fetchAnalyticsConfig,
  fetchAnalyticsReadiness,
  updateAnalyticsConfig,
} from '@/api/analyticsConfig';
import { useApiClient } from '@/hooks/useApiClient';
import { cn } from '@/lib/cn';
import { CARD } from '@/lib/tokens';

/**
 * AnalyticsConfigPage — route `/settings/analytics` (Sprint C.3, ADMIN/OWNER).
 *
 * Sumber: docs/analytics/TOGGLE-CONTRACT.md §3. Aturan UI:
 * - `ready=false` (hard blockers) → tombol Aktifkan DISABLED + alasan.
 * - `soft_blockers` (mis. no_active_bundles) → warning, TIDAK memblokir.
 * - Disable WAJIB alasan (tombol disabled selama textarea kosong).
 */
const REASON_LABEL: Record<string, string> = {
  not_yet_enabled: 'Belum pernah diaktifkan',
  analytics_disabled: 'Dinonaktifkan manual',
  readiness_failed: 'Aktif gagal: kesiapan data',
  auto_disabled: 'Dinonaktifkan otomatis (anomali)',
};

function parseList(value: string): string[] {
  return value
    .split(',')
    .map((item) => item.trim())
    .filter((item) => item.length > 0);
}

export function AnalyticsConfigPage() {
  const client = useApiClient();
  const queryClient = useQueryClient();
  const [toast, setToast] = useState<{ title: string; tone: ToastTone } | null>(null);
  const [domainsDraft, setDomainsDraft] = useState<string | null>(null);
  const [metricsDraft, setMetricsDraft] = useState<string | null>(null);
  const [confirmEnable, setConfirmEnable] = useState(false);
  const [disableOpen, setDisableOpen] = useState(false);
  const [reason, setReason] = useState('');

  const configQuery = useQuery({
    queryKey: ['analytics-config'],
    queryFn: () => fetchAnalyticsConfig(client),
  });
  const readinessQuery = useQuery({
    queryKey: ['analytics-readiness'],
    queryFn: () => fetchAnalyticsReadiness(client),
  });

  const config = configQuery.data;
  const readiness = readinessQuery.data;
  const domainsValue = domainsDraft ?? (config?.enabled_domains.join(', ') ?? '');
  const metricsValue = metricsDraft ?? (config?.enabled_metrics.join(', ') ?? '');
  const canEnable = readiness?.ready === true && config?.enabled !== true;
  const firstBlocker = readiness?.blockers[0];

  function refreshAll() {
    void queryClient.invalidateQueries({ queryKey: ['analytics-config'] });
    void queryClient.invalidateQueries({ queryKey: ['analytics-readiness'] });
  }

  const enableMutation = useMutation({
    mutationFn: () =>
      enableAnalytics(client, {
        enabled_domains: parseList(domainsValue),
        enabled_metrics: parseList(metricsValue),
      }),
    onSuccess: () => {
      setConfirmEnable(false);
      setToast({ title: 'Analitik diaktifkan', tone: 'success' });
      refreshAll();
    },
    onError: (error: Error) => setToast({ title: error.message, tone: 'error' }),
  });

  const disableMutation = useMutation({
    mutationFn: () => disableAnalytics(client, reason),
    onSuccess: () => {
      setDisableOpen(false);
      setReason('');
      setToast({ title: 'Analitik dinonaktifkan', tone: 'success' });
      refreshAll();
    },
    onError: (error: Error) => setToast({ title: error.message, tone: 'error' }),
  });

  const filterMutation = useMutation({
    mutationFn: () =>
      updateAnalyticsConfig(client, {
        enabled_domains: parseList(domainsValue),
        enabled_metrics: parseList(metricsValue),
      }),
    onSuccess: () => {
      setToast({ title: 'Filter tersimpan', tone: 'success' });
      refreshAll();
    },
    onError: (error: Error) => setToast({ title: error.message, tone: 'error' }),
  });

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <PageHeader
        title="Analitik"
        subtitle="Aktifkan, atur cakupan metrik, dan cek kesiapan data"
        breadcrumb={[{ label: 'Pengaturan' }, { label: 'Analitik' }]}
        actions={
          <Button
            variant="secondary"
            icon={RefreshCw}
            onClick={() => {
              void readinessQuery.refetch();
              refreshAll();
            }}
          >
            Cek Ulang
          </Button>
        }
      />

      <section className={cn(CARD, 'flex flex-col gap-2 text-sm')}>
        <h2 className="text-base font-semibold text-foreground">Status</h2>
        <p>
          Aktif: <span className="font-medium">{config?.enabled ? 'Ya' : 'Tidak'}</span>
        </p>
        <p>
          Alasan OFF:{' '}
          <span className="font-medium">
            {REASON_LABEL[config?.disabled_reason ?? ''] ?? config?.disabled_reason ?? '—'}
          </span>
        </p>
        <p className="text-muted-foreground">
          Aktif sejak: {config?.enabled_at ?? '—'} · oleh: {config?.enabled_by ?? '—'}
        </p>
      </section>

      <section className={cn(CARD, 'flex flex-col gap-2 text-sm')}>
        <h2 className="text-base font-semibold text-foreground">Kesiapan Data</h2>
        {readiness?.blockers.length ? (
          <ul data-analytics-blockers="hard" className="list-disc pl-5 text-accent-coral">
            {readiness.blockers.map((blocker) => (
              <li key={blocker}>{blocker}</li>
            ))}
          </ul>
        ) : (
          <p className="text-muted-foreground">Tidak ada penghalang keras.</p>
        )}
        {readiness?.soft_blockers.length ? (
          <ul data-analytics-blockers="soft" className="list-disc pl-5 text-accent-amber">
            {readiness.soft_blockers.map((blocker) => (
              <li key={blocker}>{blocker}</li>
            ))}
          </ul>
        ) : null}
        <p className="text-xs text-muted-foreground">
          Diperiksa: {readiness?.checked_at ?? '—'}
        </p>
      </section>

      <section className={cn(CARD, 'flex flex-col gap-3')}>
        <h2 className="text-base font-semibold text-foreground">Filter Cakupan</h2>
        <Input
          label="Domain aktif (pisahkan koma; kosong = semua)"
          value={domainsValue}
          onChange={(event) => setDomainsDraft(event.target.value)}
        />
        <Input
          label="Metrik aktif (pisahkan koma; menang atas domain)"
          value={metricsValue}
          onChange={(event) => setMetricsDraft(event.target.value)}
        />
        <div>
          <Button
            variant="secondary"
            disabled={filterMutation.isPending}
            onClick={() => filterMutation.mutate()}
          >
            Simpan Filter
          </Button>
        </div>
      </section>

      <section className={cn(CARD, 'flex flex-wrap items-center gap-3')}>
        <Button
          disabled={!canEnable}
          title={
            canEnable
              ? 'Aktifkan analitik'
              : `Kesiapan data belum terpenuhi: ${firstBlocker ?? 'sudah aktif'}`
          }
          onClick={() => setConfirmEnable(true)}
        >
          Aktifkan Analitik
        </Button>
        <Button
          variant="secondary"
          disabled={config?.enabled !== true}
          onClick={() => setDisableOpen(true)}
        >
          Nonaktifkan Analitik
        </Button>
      </section>

      {confirmEnable ? (
        <section data-analytics-confirm="enable" className={cn(CARD, 'flex flex-col gap-2')}>
          <p className="font-semibold text-foreground">
            Data siap? Analitik akan aktif. Yakin?
          </p>
          {readiness?.soft_blockers.map((blocker) => (
            <p key={blocker} className="text-xs text-accent-amber">
              Peringatan: {blocker}
            </p>
          ))}
          <div className="flex gap-2">
            <Button disabled={enableMutation.isPending} onClick={() => enableMutation.mutate()}>
              Ya, Aktifkan
            </Button>
            <Button variant="secondary" onClick={() => setConfirmEnable(false)}>
              Batal
            </Button>
          </div>
        </section>
      ) : null}

      {disableOpen ? (
        <section data-analytics-confirm="disable" className={cn(CARD, 'flex flex-col gap-2')}>
          <p className="font-semibold text-foreground">Alasan menonaktifkan (wajib)</p>
          <textarea
            className="min-h-20 rounded-md border border-border bg-background p-2 text-sm"
            value={reason}
            onChange={(event) => setReason(event.target.value)}
          />
          <div className="flex gap-2">
            <Button
              disabled={reason.trim().length === 0 || disableMutation.isPending}
              onClick={() => disableMutation.mutate()}
            >
              Nonaktifkan
            </Button>
            <Button variant="secondary" onClick={() => setDisableOpen(false)}>
              Batal
            </Button>
          </div>
        </section>
      ) : null}

      <Toast
        open={toast !== null}
        onOpenChange={(open) => {
          if (!open) setToast(null);
        }}
        title={toast?.title ?? ''}
        tone={toast?.tone ?? 'default'}
      />
    </div>
  );
}
