import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useParams } from 'react-router-dom';
import { RefreshCw } from 'lucide-react';
import { Button } from '@/components/atoms/Button';
import { Toast, type ToastTone } from '@/components/atoms/Toast';
import { PageHeader } from '@/components/molecules/PageHeader';
import { ReadinessTable } from '@/components/molecules/ReadinessTable';
import { getOrderReadiness, postRecomputeReadiness } from '@/api/readiness';
import { useFeedback } from '@/app/app-runtime';
import { useApiClient } from '@/hooks/useApiClient';
import { cn } from '@/lib/cn';
import { CARD } from '@/lib/tokens';

/**
 * MaterialReadinessPage - route `/production/readiness/:orderId` (F8).
 *
 * PENTING: parameter URL = **id ORDER** (`:orderId`), bukan OrderLine - backend
 * (`/garmen/orders/{id}/readiness/`, §5.4) mengembalikan `{order_id, lines[]}`.
 *
 * `IsAuthenticated` → tanpa session backend membalas 403; halaman menampilkan pesan
 * (tidak blank). Tombol Recompute memanggil Odoo lewat backend (§5.5) = efek nyata,
 * jadi hanya dikirim saat operator menekan + hasilnya dilaporkan lewat toast.
 */

interface ToastState {
  tone: ToastTone;
  title: string;
  description: string;
}

export function MaterialReadinessPage() {
  const { orderId } = useParams<{ orderId: string }>();
  const apiClient = useApiClient();
  const queryClient = useQueryClient();
  const { trigger } = useFeedback();

  const [toast, setToast] = useState<ToastState | null>(null);

  const key = orderId ?? '';

  const readiness = useQuery({
    queryKey: ['order-readiness', key],
    queryFn: () => getOrderReadiness(apiClient, key),
    enabled: key.length > 0,
    staleTime: 15_000,
  });

  const recompute = useMutation({
    mutationFn: () => postRecomputeReadiness(apiClient, key),
    onSuccess: (result) => {
      trigger('success');
      setToast({
        tone: 'success',
        title: 'Recompute selesai',
        description: `${result.queued} OrderLine dihitung (siap ${result.ready}, sebagian ${result.partial}, menunggu ${result.waiting}, error ${result.errors}).`,
      });
      void queryClient.invalidateQueries({ queryKey: ['order-readiness', key] });
    },
    onError: (caught) => {
      trigger('error');
      setToast({
        tone: 'error',
        title: 'Recompute gagal',
        description: caught instanceof Error ? caught.message : 'Recompute readiness gagal.',
      });
    },
  });

  const lines = readiness.data?.lines ?? [];
  const loadError = readiness.error === null ? null : 'Gagal memuat readiness (perlu login?).';

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <PageHeader
        title={`Kesiapan Material Order #${key}`}
        subtitle="Status PO/vendor bill per OrderLine (backend Odoo)"
        breadcrumb={[{ label: 'Production' }, { label: 'Readiness' }]}
      />

      <section className={cn(CARD, 'flex flex-wrap items-center justify-between gap-3')}>
        <div className="flex flex-col gap-0.5">
          <span className="text-sm font-semibold text-foreground">
            {readiness.isLoading ? 'Memuat…' : `${lines.length} OrderLine`}
          </span>
          <span className="text-xs text-muted-foreground">
            Recompute memicu pengambilan PO/vendor bill dari Odoo (efek nyata).
          </span>
        </div>

        <Button
          variant="secondary"
          icon={RefreshCw}
          loading={recompute.isPending}
          disabled={key.length === 0 || recompute.isPending}
          onClick={() => {
            recompute.mutate();
          }}
        >
          Recompute
        </Button>
      </section>

      <section className={cn(CARD, 'p-0')}>
        <ReadinessTable
          lines={lines}
          loading={readiness.isLoading}
          error={loadError}
          onRetry={() => {
            void readiness.refetch();
          }}
        />
      </section>

      <Toast
        open={toast !== null}
        onOpenChange={(open) => {
          if (!open) setToast(null);
        }}
        tone={toast?.tone ?? 'default'}
        title={toast?.title ?? ''}
        description={toast?.description}
      />
    </div>
  );
}
