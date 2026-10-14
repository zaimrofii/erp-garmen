import { useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, CheckCircle2, FileText, Pencil, RefreshCw, Trash2, XCircle } from 'lucide-react';
import { Badge } from '@/components/atoms/Badge';
import { Button } from '@/components/atoms/Button';
import { Spinner } from '@/components/atoms/Spinner';
import { Toast, type ToastTone } from '@/components/atoms/Toast';
import { DenseTable, type DenseTableColumn } from '@/components/molecules/DenseTable';
import { PageHeader } from '@/components/molecules/PageHeader';
import {
  deletePurchaseOrderMes,
  fetchPurchaseOrderMes,
  fetchPurchaseOrderOdooState,
  runPurchaseOrderMesAction,
  type PurchaseOrderMesAction,
} from '@/api/purchaseOrdersCrud';
import { useFeedback } from '@/app/app-runtime';
import { useApiClient } from '@/hooks/useApiClient';
import { cn } from '@/lib/cn';
import { displayDate, displayOrDash, isPoEditable, poDetailItems, poStateLabel } from '@/lib/purchase-order';
import { CARD } from '@/lib/tokens';
import type { PurchaseOrderMesLineRow } from '@/types/purchase-order';

/**
 * PurchaseOrderDetailPage - route `/purchase/orders/:id` (H2.2).
 *
 * Read-only + **aksi transisi** (§14) yang ditampilkan hanya kalau backend
 * mengizinkannya (`allowed_actions` pada respons detail):
 *
 *   * `confirm` → `DRAFT → CONFIRMED` + enqueue push `purchase.order` ke Odoo
 *     (create **draft**, `partner_ref` = nomor MES);
 *   * `done` → `CONFIRMED → DONE` (murni MES; Odoo `done` = *Locked* dari receipt);
 *   * `cancel` → `CANCELLED` + `action_cancel` Odoo bila sudah punya `odoo_id`;
 *   * **"Cek state Odoo"** → `POST …/sync-odoo-state/` (read-only): menampilkan
 *     `state`/`name` PO di Odoo supaya purchasing tahu apakah sudah perlu
 *     men-confirm PO di UI Odoo (syarat I3 `material_readiness`).
 */

interface ToastState {
  tone: ToastTone;
  title: string;
  description: string;
}

const LINE_COLUMNS: DenseTableColumn<PurchaseOrderMesLineRow>[] = [
  {
    key: 'product_code',
    label: 'Produk',
    render: (row) => <span className="font-mono">{displayOrDash(row.product_code)}</span>,
  },
  { key: 'product_name', label: 'Nama', render: (row) => displayOrDash(row.product_name) },
  {
    key: 'qty',
    label: 'Qty',
    align: 'right',
    render: (row) => <span className="tabular-nums">{row.qty}</span>,
  },
  {
    key: 'price_unit',
    label: 'Harga',
    align: 'right',
    render: (row) => <span className="tabular-nums">{row.price_unit}</span>,
  },
  {
    key: 'subtotal',
    label: 'Subtotal',
    align: 'right',
    render: (row) => <span className="tabular-nums">{row.subtotal}</span>,
  },
  { key: 'date_planned', label: 'Rencana', render: (row) => displayDate(row.date_planned) },
  {
    key: 'tax_ids',
    label: 'Pajak',
    render: (row) =>
      row.tax_ids.length === 0 ? (
        <span className="text-muted-foreground">-</span>
      ) : (
        <span className="tabular-nums">{row.tax_ids.join(', ')}</span>
      ),
  },
];

/** Label tombol transisi (Bahasa Indonesia). */
const ACTION_LABELS: Record<string, string> = {
  confirm: 'Konfirmasi & Push Odoo',
  done: 'Tandai Selesai',
  cancel: 'Batalkan PO',
};

/** Icon tombol per aksi transisi. */
function actionIcon(action: string) {
  if (action === 'cancel') return XCircle;

  return CheckCircle2;
}

/** Icon tombol per aksi transisi. */

export function PurchaseOrderDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const client = useApiClient();
  const queryClient = useQueryClient();
  const { trigger } = useFeedback();

  const parsedId = id === undefined ? null : Number(id);
  const poId = parsedId !== null && Number.isFinite(parsedId) ? parsedId : null;

  const [toast, setToast] = useState<ToastState | null>(null);
  const [odooState, setOdooState] = useState<string | null>(null);

  const { data: po, isLoading, error, refetch } = useQuery({
    queryKey: ['purchase-order-mes', poId],
    queryFn: () => fetchPurchaseOrderMes(client, poId ?? 0),
    enabled: poId !== null,
    staleTime: 15_000,
  });

  const action = useMutation({
    mutationFn: async (name: PurchaseOrderMesAction) =>
      runPurchaseOrderMesAction(client, poId ?? 0, name),
    onSuccess: (saved, name) => {
      trigger('success');
      setToast({
        tone: 'success',
        title: `PO ${poStateLabel(saved.state)}`,
        description: `${saved.code} — ${ACTION_LABELS[name] ?? name}.`,
      });
      void queryClient.invalidateQueries({ queryKey: ['purchase-orders-mes'] });
      void refetch();
    },
    onError: (caught) => {
      trigger('error');
      setToast({
        tone: 'error',
        title: 'Transisi ditolak',
        description: caught instanceof Error ? caught.message : 'Permintaan transisi gagal.',
      });
    },
  });

  const remove = useMutation({
    mutationFn: async () => deletePurchaseOrderMes(client, poId ?? 0),
    onSuccess: () => {
      trigger('success');
      setToast({
        tone: 'success',
        title: 'PO dihapus',
        description: 'PO DRAFT dihapus permanen (hard delete).',
      });
      void queryClient.invalidateQueries({ queryKey: ['purchase-orders-mes'] });
      navigate('/purchase/orders');
    },
    onError: (caught) => {
      trigger('error');
      setToast({
        tone: 'error',
        title: 'Gagal menghapus PO',
        description: caught instanceof Error ? caught.message : 'Permintaan hapus gagal.',
      });
    },
  });

  /** Baca state PO di Odoo (read-only) — memastikan purchasing sudah confirm di Odoo. */
  const checkOdoo = useMutation({
    mutationFn: async () => fetchPurchaseOrderOdooState(client, poId ?? 0),
    onSuccess: (info) => {
      trigger('success');
      setOdooState(info.odoo_state);
      setToast({
        tone: 'success',
        title: 'State Odoo dibaca',
        description: `${info.odoo_name ?? '-'} → ${info.odoo_state ?? '-'} (read-only, data MES tidak berubah).`,
      });
    },
    onError: (caught) => {
      trigger('error');
      setOdooState(null);
      setToast({
        tone: 'error',
        title: 'Gagal membaca state Odoo',
        description: caught instanceof Error ? caught.message : 'Permintaan gagal.',
      });
    },
  });

  const lines = po?.lines ?? [];
  const actions = po?.allowed_actions ?? [];
  const editable = po !== undefined && isPoEditable(po.state);

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <PageHeader
        title={po === undefined ? 'Detail PO' : po.code}
        subtitle="Purchase Order MES — push ke Odoo hanya saat CONFIRMED (create draft, tanpa action_confirm)"
        breadcrumb={[
          { label: 'Purchase', href: '/purchase/orders' },
          { label: 'Orders', href: '/purchase/orders' },
          { label: po === undefined ? 'Detail' : po.code },
        ]}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="secondary" icon={ArrowLeft} onClick={() => navigate('/purchase/orders')}>
              Kembali
            </Button>

            <Button
              icon={Pencil}
              disabled={!editable}
              onClick={() => navigate(`/purchase/orders/${String(poId)}/edit`)}
            >
              Edit
            </Button>

            {/* H3.2 — bonus: buat Vendor Bill untuk PO ini (auto-fill baris + vendor
                di form via `?po=`). Bill di-push ke Odoo (`in_invoice`) saat CONFIRMED. */}
            <Button
              icon={FileText}
              disabled={po === undefined}
              onClick={() => navigate(`/finance/vendor-bills/new?po=${String(poId)}`)}
            >
              Buat Bill
            </Button>

            <Button
              variant="secondary"
              icon={Trash2}
              disabled={!editable || remove.isPending}
              onClick={() => remove.mutate()}
            >
              Hapus
            </Button>
          </div>
        }
      />

      {isLoading ? (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Spinner size="sm" /> Memuat PO…
        </div>
      ) : null}

      {error !== null ? (
        <section className={cn(CARD, 'flex flex-col gap-2')}>
          <p role="alert" className="text-sm font-medium text-accent-coral">
            Gagal memuat PO (perlu login atau PO tidak ada).
          </p>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => {
              void refetch();
            }}
          >
            Coba Lagi
          </Button>
        </section>
      ) : null}

      {po !== undefined ? (
        <>
          <section className={cn(CARD, 'flex flex-wrap items-center gap-3')}>
            <Badge tone={po.state === 'CANCELLED' ? 'coral' : 'muted'}>{poStateLabel(po.state)}</Badge>
            <span className="text-sm text-muted-foreground">
              {actions.length === 0
                ? 'Tidak ada transisi tersedia'
                : `Aksi tersedia: ${actions.join(', ')}`}
            </span>
            <div className="flex flex-wrap items-center gap-2">
              {actions
                .filter((name): name is PurchaseOrderMesAction =>
                  (['confirm', 'done', 'cancel'] as readonly string[]).includes(name),
                )
                .map((name) => (
                  <Button
                    key={name}
                    variant={name === 'cancel' ? 'secondary' : 'primary'}
                    icon={actionIcon(name)}
                    loading={action.isPending && action.variables === name}
                    onClick={() => action.mutate(name)}
                  >
                    {ACTION_LABELS[name] ?? name}
                  </Button>
                ))}

              {/* Read-only: tidak memicu push, hanya membaca state PO di Odoo. */}
              <Button
                variant="secondary"
                icon={RefreshCw}
                disabled={po.odoo_id === null || checkOdoo.isPending}
                loading={checkOdoo.isPending}
                onClick={() => checkOdoo.mutate()}
              >
                Cek state Odoo
              </Button>
            </div>
            {odooState === null ? null : (
              <span className="text-sm text-muted-foreground">
                State di Odoo: <span className="font-mono">{odooState}</span>
              </span>
            )}
          </section>

          <section className={cn(CARD, 'grid grid-cols-1 gap-3 md:grid-cols-2')}>
            {poDetailItems(po).map((item) => (
              <div key={item.label} className="flex flex-col gap-0.5">
                <span className="text-xs uppercase tracking-wide text-muted-foreground">
                  {item.label}
                </span>
                <span className={cn('text-sm', item.mono === true ? 'font-mono tabular-nums' : '')}>
                  {item.value}
                </span>
              </div>
            ))}
            <div className="flex flex-col gap-0.5">
              <span className="text-xs uppercase tracking-wide text-muted-foreground">
                Status Sync
              </span>
              <span className="text-sm font-mono">{displayOrDash(po.odoo_sync_status)}</span>
            </div>
          </section>

          <section className={cn(CARD, 'p-0')}>
            <DenseTable
              columns={LINE_COLUMNS}
              rows={lines}
              emptyMessage="PO ini belum punya baris."
            />
          </section>
        </>
      ) : null}

      <Toast
        open={toast !== null}
        onOpenChange={() => setToast(null)}
        title={toast?.title ?? ''}
        {...(toast === null ? {} : { tone: toast.tone, description: toast.description })}
      />
    </div>
  );
}

