import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, Pencil, Play, Scissors, Trash2, XCircle } from 'lucide-react';
import { Button } from '@/components/atoms/Button';
import { Spinner } from '@/components/atoms/Spinner';
import { Toast, type ToastTone } from '@/components/atoms/Toast';
import { PageHeader } from '@/components/molecules/PageHeader';
import { StatusChip } from '@/components/molecules/StatusChip';
import {
  deleteWorkOrderCrud,
  fetchWorkOrderCrud,
  runWorkOrderCrudAction,
  splitWorkOrderCrud,
  type WorkOrderAction,
} from '@/api/workOrdersCrud';
import { useApiClient } from '@/hooks/useApiClient';
import { chipStatusFromState } from '@/lib/state-display';
import {
  allowedWoActions,
  displayOrDash,
  isWoEditable,
  isWoSplittable,
  parseSplitParts,
  validateSplitParts,
  woActionLabel,
  woDetailItems,
  woStateLabel,
} from '@/lib/work-order';
import { CARD } from '@/lib/tokens';

/**
 * WorkOrderDetailPage - route `/production/work-orders/:id` (H2.3).
 *
 * Read-only + aksi:
 *   * **transisi state memakai endpoint aksi EXISTING** (`POST /work-orders/<id>/WO_START|WO_CLOSE|WO_CANCEL/`
 *     dari state machine yang di-SEED `garment.work_order`: `DRAFT → IN_PROGRESS → DONE`,
 *     `DRAFT|IN_PROGRESS → CANCELLED`) — H2.3 TIDAK menambah endpoint transisi baru;
 *   * **split** (DRAFT & belum punya bundle): jumlah qty WAJIB = qty rencana sumber;
 *   * **hapus hibrida**: DRAFT tanpa bundle = hard delete, selain itu soft delete
 *     (`CANCELLED`), sudah `CANCELLED` = ditolak (409);
 *   * Work Order = **MES-only** ⇒ tidak ada tombol push ke Odoo.
 */

interface ToastState {
  tone: ToastTone;
  title: string;
  description: string;
}

/** Ikon tiap aksi state machine (label teks dari `woActionLabel`). */
const ACTION_ICONS: Record<string, typeof Play> = {
  WO_START: Play,
  WO_CLOSE: XCircle,
  WO_CANCEL: XCircle,
};

export function WorkOrderDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const client = useApiClient();
  const queryClient = useQueryClient();

  const parsedId = id === undefined ? null : Number(id);
  const workOrderId = parsedId !== null && Number.isFinite(parsedId) ? parsedId : 0;

  const [toast, setToast] = useState<ToastState | null>(null);
  const [splitText, setSplitText] = useState('');
  const [splitError, setSplitError] = useState<string | null>(null);

  const detail = useQuery({
    queryKey: ['work-order-crud', workOrderId],
    queryFn: () => fetchWorkOrderCrud(client, workOrderId),
    staleTime: 15_000,
  });

  function onDone(message: string) {
    void queryClient.invalidateQueries({ queryKey: ['work-order-crud', workOrderId] });
    void queryClient.invalidateQueries({ queryKey: ['work-orders'] });
    setToast({ tone: 'success', title: 'Berhasil', description: message });
  }

  function onFail(error: unknown) {
    setToast({
      tone: 'error',
      title: 'Gagal',
      description: error instanceof Error ? error.message : 'Terjadi kesalahan tak terduga.',
    });
  }

  const action = useMutation({
    mutationFn: (name: WorkOrderAction) => runWorkOrderCrudAction(client, workOrderId, name),
    onSuccess: (_data, name) => onDone(`Aksi ${woActionLabel(name)} dijalankan.`),
    onError: onFail,
  });

  const split = useMutation({
    mutationFn: (parts: number[]) => splitWorkOrderCrud(client, workOrderId, parts),
    onSuccess: (saved) => {
      setSplitText('');
      setSplitError(null);
      onDone(`WO dipecah menjadi ${String(saved.summary.created + 1)} bagian.`);
    },
    onError: onFail,
  });

  const remove = useMutation({
    mutationFn: () => deleteWorkOrderCrud(client, workOrderId),
    onSuccess: (saved) => {
      if (saved === null) {
        setToast({ tone: 'success', title: 'Work Order dihapus', description: 'Hard delete (DRAFT tanpa bundle).' });
      } else {
        setToast({ tone: 'success', title: 'Work Order dibatalkan', description: `Soft delete → ${saved.state}.` });
      }
      navigate('/production/work-orders');
    },
    onError: onFail,
  });

  if (detail.isLoading) {
    return (
      <div className="p-4">
        <Spinner />
      </div>
    );
  }

  if (detail.error !== null || detail.data === undefined) {
    return (
      <div className="p-4">
        <p className="text-accent-coral">Gagal memuat Work Order #{String(workOrderId)}.</p>
      </div>
    );
  }

  const row = detail.data;
  const actions = row.allowed_actions.length > 0 ? row.allowed_actions : allowedWoActions(row.state);
  const splittable = isWoSplittable(row);
  const editable = isWoEditable(row.state);

  function onSplit() {
    const parts = parseSplitParts(splitText);
    const error = validateSplitParts(parts, row.qty_planned);
    setSplitError(error);
    if (error !== null) return;

    split.mutate(parts);
  }

  function onDelete() {
    const message = editable && row.bundles_count === 0
      ? 'Hapus permanen WO ini? (DRAFT tanpa bundle)'
      : 'WO ini akan DIBATALKAN (soft delete) — lanjutkan?';
    if (typeof window !== 'undefined' && !window.confirm(message)) return;

    remove.mutate();
  }

  return (
    <div className="mx-auto max-w-3xl space-y-4 p-4">
      <PageHeader
        title={`Work Order ${row.code}`}
        subtitle="WO = unit kerja MES per baris order (MES-only, tanpa padanan Odoo)."
        breadcrumb={[
          { label: 'Production', href: '/production/work-orders' },
          { label: row.code },
        ]}
        actions={
          <>
            <Button variant="secondary" icon={ArrowLeft} onClick={() => navigate(-1)}>
              Kembali
            </Button>
            {editable ? (
              <Link to={`/production/work-orders/${String(row.id)}/edit`}>
                <Button variant="secondary" icon={Pencil}>
                  Ubah
                </Button>
              </Link>
            ) : null}
            {row.state !== 'CANCELLED' ? (
              <Button
                variant="danger"
                icon={Trash2}
                onClick={onDelete}
                disabled={remove.isPending}
              >
                Hapus
              </Button>
            ) : null}
          </>
        }
      />

      <section className={CARD + ' space-y-3'}>
        <div className="flex items-center gap-2">
          <StatusChip
            status={chipStatusFromState(row.state)}
            label={woStateLabel(row.state)}
          />
          <span className="text-xs text-muted-foreground">
            {actions.length === 0 ? 'state terminal' : `aksi: ${actions.map(woActionLabel).join(', ')}`}
          </span>
        </div>

        <dl className="grid gap-2 sm:grid-cols-2">
          {woDetailItems(row).map((item) => (
            <div key={item.label} className="flex flex-col">
              <dt className="text-xs text-muted-foreground">{item.label}</dt>
              <dd className={item.mono === true ? 'font-mono text-sm text-foreground' : 'text-sm text-foreground'}>
                {item.value}
              </dd>
            </div>
          ))}
        </dl>

        {actions.length > 0 ? (
          <div className="flex flex-wrap gap-2">
            {actions.map((name) => {
              const Icon = ACTION_ICONS[name] ?? Play;

              return (
                <Button
                  key={name}
                  variant="secondary"
                  icon={Icon}
                  disabled={action.isPending}
                  onClick={() => action.mutate(name as WorkOrderAction)}
                >
                  {woActionLabel(name)}
                </Button>
              );
            })}
          </div>
        ) : null}
      </section>

      <section className={CARD + ' space-y-3'}>
        <h2 className="text-sm font-semibold text-foreground">Split WO</h2>
        {splittable ? (
          <>
            <p className="text-xs text-muted-foreground">
              Pecah qty rencana ({row.qty_planned}) menjadi beberapa WO pada baris order yang
              sama — jumlah bagian WAJIB = {row.qty_planned} (mis. 60, 40). WO ini menjadi
              bagian pertama.
            </p>
            <div className="flex flex-col gap-2 sm:flex-row">
              <input
                aria-label="Qty split"
                className="w-full rounded-lg border border-input bg-card px-3 py-2 text-sm text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                placeholder="60, 40"
                value={splitText}
                onChange={(event) => setSplitText(event.target.value)}
              />
              <Button
                variant="secondary"
                icon={Scissors}
                disabled={split.isPending}
                onClick={onSplit}
              >
                Split
              </Button>
            </div>
            {splitError !== null ? (
              <p className="text-xs text-accent-coral" role="alert">
                {splitError}
              </p>
            ) : null}
          </>
        ) : (
          <p className="text-xs text-muted-foreground">
            Split hanya untuk WO <strong>DRAFT</strong> yang belum punya bundle.
          </p>
        )}
      </section>

      <section className={CARD + ' space-y-3'}>
        <h2 className="text-sm font-semibold text-foreground">
          Bundle ({row.bundles.length})
        </h2>
        {row.bundles.length === 0 ? (
          <p className="text-xs text-muted-foreground">
            Belum ada bundle. Bundle dibuat dari halaman bundle/WO (BundleEngine menempelkan
            bundle ke WorkOrder pertama baris order ini).
          </p>
        ) : (
          <ul className="divide-y divide-border">
            {row.bundles.map((bundle) => (
              <li key={bundle.id} className="flex items-center justify-between gap-2 py-2">
                <span className="font-mono text-sm text-foreground">{bundle.code}</span>
                <span className="text-xs text-muted-foreground">
                  {displayOrDash(bundle.size)} · {bundle.qty_done}/{bundle.qty}
                </span>
                <StatusChip
                  status={chipStatusFromState(bundle.state)}
                  label={bundle.state}
                />
              </li>
            ))}
          </ul>
        )}
      </section>

      {toast !== null ? (
        <Toast
          open
          onOpenChange={(open) => {
            if (!open) setToast(null);
          }}
          tone={toast.tone}
          title={toast.title}
          description={toast.description}
        />
      ) : null}
    </div>
  );
}


