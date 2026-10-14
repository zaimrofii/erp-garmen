import { useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, Ban, Pencil } from 'lucide-react';
import { Badge } from '@/components/atoms/Badge';
import { Button } from '@/components/atoms/Button';
import { Spinner } from '@/components/atoms/Spinner';
import { Toast, type ToastTone } from '@/components/atoms/Toast';
import { DenseTable, type DenseTableColumn } from '@/components/molecules/DenseTable';
import { PageHeader } from '@/components/molecules/PageHeader';
import { RoutingGraph } from '@/components/molecules/RoutingGraph';
import { deleteRouting, fetchRouting } from '@/api/masterRoutings';
import { useFeedback } from '@/app/app-runtime';
import { useApiClient } from '@/hooks/useApiClient';
import { cn } from '@/lib/cn';
import { detailToGraph, routingStatusLabel, stepsSummary } from '@/lib/master-routing';
import { CARD, PILL_GHOST } from '@/lib/tokens';
import type { MasterRoutingStepRow } from '@/types/master-routing';

/**
 * RoutingDetailPage - route `/master/routings/:id` (H1.9, read-only + aksi).
 *
 *   * data dari `GET /api/v1/settings/routing/<id>/` (B22 di-extend): baris B22 +
 *     `capability_tags`, `steps_count`, **`nodes[]`/`edges[]`** (shape
 *     `/api/v1/routing/graph/`) ⇒ visualisasi memakai molekul `RoutingGraph` yang sama
 *     dengan editor Settings (B22) — tidak ada komponen DAG baru;
 *   * tabel step menampilkan `depends_on` (step_no), rework, dan flag awal/akhir
 *     (flag dihitung ulang backend dari edge, bukan diedit manual);
 *   * **Nonaktifkan** = `DELETE` (soft delete `is_active=false`); **400** kalau masih
 *     dipakai rule tag-router aktif — pesan backend ditampilkan apa adanya;
 *   * tanpa kolom Odoo ID — H1.9 MES-only, tanpa `odoo_id`.
 */

interface ToastState {
  tone: ToastTone;
  title: string;
  description: string;
}

const STEP_COLUMNS: DenseTableColumn<MasterRoutingStepRow>[] = [
  {
    key: 'step_no',
    label: 'Order',
    align: 'right',
    render: (row) => <span className="tabular-nums">{row.step_no}</span>,
  },
  { key: 'wc_type', label: 'Label / Work Center' },
  {
    key: 'depends_on',
    label: 'Menunggu',
    render: (row) =>
      row.depends_on.length === 0 ? (
        <span className="text-xs text-muted-foreground">(step awal)</span>
      ) : (
        <span className="text-xs tabular-nums">{row.depends_on.join(', ')}</span>
      ),
  },
  {
    key: 'rework_target_step',
    label: 'Rework ke',
    render: (row) =>
      row.rework_target_step === null ? (
        <span className="text-muted-foreground">-</span>
      ) : (
        <span className="text-xs tabular-nums">order {row.rework_target_step}</span>
      ),
  },
  {
    key: 'flags',
    label: 'Peran',
    render: (row) => (
      <span className="flex gap-1">
        {row.is_initial ? <Badge tone="muted">awal</Badge> : null}
        {row.is_terminal ? <Badge tone="muted">akhir</Badge> : null}
      </span>
    ),
  },
];

export function RoutingDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const client = useApiClient();
  const queryClient = useQueryClient();
  const { trigger } = useFeedback();

  const parsedId = id === undefined ? null : Number(id);
  const routingId = parsedId !== null && Number.isFinite(parsedId) ? parsedId : null;

  const [toast, setToast] = useState<ToastState | null>(null);

  const detail = useQuery({
    queryKey: ['master-routing', routingId],
    queryFn: () => fetchRouting(client, routingId ?? 0),
    enabled: routingId !== null,
    staleTime: 15_000,
  });

  const deactivate = useMutation({
    mutationFn: () => deleteRouting(client, routingId ?? 0),
    onSuccess: (saved) => {
      trigger('success');
      setToast({
        tone: 'success',
        title: 'Routing dinonaktifkan',
        description: `${saved.code} di-soft delete (is_active=false); baris tetap ada.`,
      });
      void queryClient.invalidateQueries({ queryKey: ['master-routing', routingId] });
      void queryClient.invalidateQueries({ queryKey: ['master-routings'] });
    },
    onError: (caught) => {
      trigger('error');
      setToast({
        tone: 'error',
        title: 'Gagal menonaktifkan routing',
        description: caught instanceof Error ? caught.message : 'Permintaan gagal.',
      });
    },
  });

  if (routingId === null) {
    return (
      <div className="p-4 lg:p-6">
        <p role="alert" className="text-sm font-medium text-accent-coral">
          Id routing tidak valid.
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <PageHeader
        title={detail.data === undefined ? 'Detail Routing' : detail.data.name}
        subtitle="Alur proses produksi (DAG) — MES-only, tidak disinkron ke Odoo"
        breadcrumb={[
          { label: 'Inventory', href: '/inventory/products' },
          { label: 'Master Routing', href: '/master/routings' },
          { label: 'Detail' },
        ]}
        actions={
          <div className="flex items-center gap-2">
            <Button
              variant="secondary"
              icon={Pencil}
              onClick={() => navigate(`/master/routings/${String(routingId)}/edit`)}
            >
              Ubah
            </Button>
            <Button
              variant="ghost"
              icon={Ban}
              disabled={deactivate.isPending || detail.data?.is_active === false}
              onClick={() => deactivate.mutate()}
            >
              Nonaktifkan
            </Button>
            <Button variant="ghost" icon={ArrowLeft} onClick={() => navigate('/master/routings')}>
              Kembali
            </Button>
          </div>
        }
      />

      {detail.isLoading ? (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Spinner size="sm" /> Memuat routing…
        </div>
      ) : null}

      {detail.error !== null ? (
        <section className={cn(CARD, 'flex flex-col gap-2')}>
          <p role="alert" className="text-sm font-medium text-accent-coral">
            Gagal memuat routing (perlu login atau routing tidak ada).
          </p>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => {
              void detail.refetch();
            }}
          >
            Coba Lagi
          </Button>
        </section>
      ) : null}

      {detail.data !== undefined ? (
        <>
          <section className={cn(CARD, 'grid grid-cols-1 gap-4 md:grid-cols-3')}>
            <div className="flex flex-col gap-1">
              <span className="text-xs text-muted-foreground">Kode</span>
              <span className="font-mono text-sm tabular-nums">{detail.data.code}</span>
            </div>
            <div className="flex flex-col gap-1">
              <span className="text-xs text-muted-foreground">Status</span>
              <span>
                <Badge tone={detail.data.is_active ? 'blue' : 'muted'}>
                  {routingStatusLabel(detail.data.is_active)}
                </Badge>
              </span>
            </div>
            <div className="flex flex-col gap-1">
              <span className="text-xs text-muted-foreground">Langkah</span>
              <span className="text-sm">{stepsSummary(detail.data)}</span>
            </div>
            <div className="flex flex-col gap-1 md:col-span-3">
              <span className="text-xs text-muted-foreground">Catatan</span>
              <span className="text-sm">
                {detail.data.description === '' ? '-' : detail.data.description}
              </span>
            </div>
            <div className="flex flex-col gap-1 md:col-span-3">
              <span className="text-xs text-muted-foreground">Tag Kapabilitas</span>
              <span className="flex flex-wrap gap-1">
                {detail.data.capability_tags.length === 0 ? (
                  <span className="text-xs text-muted-foreground">Belum ada tag.</span>
                ) : (
                  detail.data.capability_tags.map((tag) => (
                    <span key={tag} className={cn(PILL_GHOST, 'text-xs')}>
                      {tag}
                    </span>
                  ))
                )}
              </span>
            </div>
          </section>

          <section className={cn(CARD, 'flex flex-col gap-2')}>
            <span className="text-sm font-medium text-foreground">Visualisasi DAG</span>
            <RoutingGraph graph={detailToGraph(detail.data)} />
          </section>

          <section className={cn(CARD, 'p-0')}>
            <DenseTable
              columns={STEP_COLUMNS}
              rows={detail.data.steps}
              emptyMessage="Routing ini belum punya step."
            />
          </section>

          <p className="text-xs text-muted-foreground">
            Diubah: {detail.data.updated_at === '' ? '-' : detail.data.updated_at}
          </p>
        </>
      ) : null}

      {toast !== null ? (
        <Toast
          open={toast !== null}
          onOpenChange={() => setToast(null)}
          title={toast.title}
          tone={toast.tone}
          description={toast.description}
        />
      ) : null}
    </div>
  );
}

