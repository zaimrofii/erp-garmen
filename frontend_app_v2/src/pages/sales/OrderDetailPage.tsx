import { useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, CheckCircle2, Factory, Pencil, Receipt, Trash2, XCircle } from 'lucide-react';
import { Badge } from '@/components/atoms/Badge';
import { Button } from '@/components/atoms/Button';
import { Spinner } from '@/components/atoms/Spinner';
import { Toast, type ToastTone } from '@/components/atoms/Toast';
import { DenseTable, type DenseTableColumn } from '@/components/molecules/DenseTable';
import { PageHeader } from '@/components/molecules/PageHeader';
import {
  deleteOrder,
  fetchOrder,
  runOrderAction,
  type SalesOrderAction,
} from '@/api/salesOrders';
import { useFeedback } from '@/app/app-runtime';
import { useApiClient } from '@/hooks/useApiClient';
import { generateWorkOrdersForOrder } from '@/api/workOrdersCrud';
import { cn } from '@/lib/cn';
import {
  displayOrDash,
  isOrderEditable,
  orderDetailItems,
  orderStateLabel,
} from '@/lib/sales-order';
import { CARD } from '@/lib/tokens';
import type { SalesOrderLineRow } from '@/types/sales-order';

/**
 * OrderDetailPage - route `/sales/orders/:id` (H2.1).
 *
 * Read-only + **aksi transisi** (§14) yang ditampilkan hanya kalau backend
 * mengizinkannya (`allowed_actions` pada respons detail — mirror
 * `order_services.ALLOWED_TRANSITIONS`):
 *
 *   * `confirm` → `DRAFT → CONFIRMED` + enqueue push `sale.order` ke Odoo
 *     (create **draft** di Odoo, nomor MES dikirim sebagai `client_order_ref`);
 *   * `done` → `CONFIRMED → DONE` (murni MES; Odoo 17 tak punya state `done`);
 *   * `cancel` → `CANCELLED` + `action_cancel` Odoo bila order sudah punya `odoo_id`;
 *   * Edit hanya saat DRAFT; Hapus (hard delete) hanya saat DRAFT.
 */

interface ToastState {
  tone: ToastTone;
  title: string;
  description: string;
}

const LINE_COLUMNS: DenseTableColumn<SalesOrderLineRow>[] = [
  {
    key: 'product_code',
    label: 'Produk',
    render: (row) => <span className="font-mono">{displayOrDash(row.product_code)}</span>,
  },
  { key: 'product_name', label: 'Nama', render: (row) => displayOrDash(row.product_name) },
  { key: 'qty', label: 'Qty', align: 'right', render: (row) => <span className="tabular-nums">{row.qty}</span> },
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
  { key: 'tag', label: 'Tag', render: (row) => displayOrDash(row.tag) },
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
  cancel: 'Batalkan Order',
};

/** Icon tombol per aksi transisi. */
function actionIcon(action: string) {
  if (action === 'cancel') return XCircle;

  return CheckCircle2;
}


export function OrderDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const client = useApiClient();
  const queryClient = useQueryClient();
  const { trigger } = useFeedback();

  const parsedId = id === undefined ? null : Number(id);
  const orderId = parsedId !== null && Number.isFinite(parsedId) ? parsedId : null;

  const [toast, setToast] = useState<ToastState | null>(null);

  const { data: order, isLoading, error, refetch } = useQuery({
    queryKey: ['sales-order', orderId],
    queryFn: () => fetchOrder(client, orderId ?? 0),
    enabled: orderId !== null,
    staleTime: 15_000,
  });

  const action = useMutation({
    mutationFn: async (name: SalesOrderAction) => runOrderAction(client, orderId ?? 0, name),
    onSuccess: (saved, name) => {
      trigger('success');
      setToast({
        tone: 'success',
        title: `Order ${orderStateLabel(saved.state)}`,
        description: `${saved.code} — ${ACTION_LABELS[name] ?? name}.`,
      });
      void queryClient.invalidateQueries({ queryKey: ['sales-orders'] });
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
    mutationFn: async () => deleteOrder(client, orderId ?? 0),
    onSuccess: () => {
      trigger('success');
      setToast({
        tone: 'success',
        title: 'Order dihapus',
        description: 'Order DRAFT dihapus permanen (hard delete).',
      });
      void queryClient.invalidateQueries({ queryKey: ['sales-orders'] });
      navigate('/sales/orders');
    },
    onError: (caught) => {
      trigger('error');
      setToast({
        tone: 'error',
        title: 'Gagal menghapus order',
        description: caught instanceof Error ? caught.message : 'Permintaan hapus gagal.',
      });
    },
  });

  const lines = order?.lines ?? [];
  const actions = order?.allowed_actions ?? [];
  const editable = order !== undefined && isOrderEditable(order.state);

  /** H2.3 — batch generate Work Order dari order ini (idempoten; DRAFT/LINE apa pun). */
  const generateWo = useMutation({
    mutationFn: async () => generateWorkOrdersForOrder(client, orderId ?? 0),
    onSuccess: (result) => {
      trigger('success');
      setToast({
        tone: 'success',
        title: 'Generate Work Order',
        description: `${String(result.summary.created)} WO baru, ${String(
          result.summary.skipped,
        )} baris dilewati (sudah punya WO).`,
      });
      void queryClient.invalidateQueries({ queryKey: ['sales-order', orderId] });
      void queryClient.invalidateQueries({ queryKey: ['work-orders'] });
    },
    onError: (caught) => {
      trigger('error');
      setToast({
        tone: 'error',
        title: 'Gagal generate Work Order',
        description: caught instanceof Error ? caught.message : 'Permintaan generate gagal.',
      });
    },
  });

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <PageHeader
        title={order === undefined ? 'Detail Order' : order.code}
        subtitle="Sales Order MES — push ke Odoo hanya saat CONFIRMED (create draft, tanpa action_confirm)"
        breadcrumb={[
          { label: 'Sales', href: '/sales/orders' },
          { label: 'Order', href: '/sales/orders' },
          { label: order === undefined ? 'Detail' : order.code },
        ]}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="secondary" icon={ArrowLeft} onClick={() => navigate('/sales/orders')}>
              Kembali
            </Button>

            {/* H3.1 — buat Customer Invoice MES dari order ini (baris terisi otomatis
                di halaman form: `?order=<id>`). Route-nya guard FINANCE_ROLES
                (admin/owner) — tombol sengaja selalu tampil, guard yang menjaga. */}
            <Button
              variant="secondary"
              icon={Receipt}
              onClick={() => navigate(`/finance/invoices/new?order=${String(orderId)}`)}
            >
              Buat Invoice
            </Button>

            <Button
              icon={Pencil}
              disabled={!editable}
              onClick={() => navigate(`/sales/orders/${String(orderId)}/edit`)}
            >
              Edit
            </Button>

            <Button
              variant="secondary"
              icon={Trash2}
              disabled={!editable || remove.isPending}
              onClick={() => remove.mutate()}
            >
              Hapus
            </Button>

            {/* H2.3 — buat WO untuk semua OrderLine yang belum punya WO (idempoten). */}
            {order !== undefined ? (
              <Button
                variant="secondary"
                icon={Factory}
                disabled={generateWo.isPending}
                onClick={() => generateWo.mutate()}
              >
                Generate WO
              </Button>
            ) : null}
          </div>
        }
      />

      {isLoading ? (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Spinner size="sm" /> Memuat order…
        </div>
      ) : null}

      {error !== null ? (
        <section className={cn(CARD, 'flex flex-col gap-2')}>
          <p role="alert" className="text-sm font-medium text-accent-coral">
            Gagal memuat order (perlu login atau order tidak ada).
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

      {order !== undefined ? (
        <>
          <section className={cn(CARD, 'flex flex-wrap items-center gap-3')}>
            <Badge tone={order.state === 'CANCELLED' ? 'coral' : 'muted'}>
              {orderStateLabel(order.state)}
            </Badge>
            <span className="text-sm text-muted-foreground">
              {actions.length === 0
                ? 'Tidak ada transisi tersedia'
                : `Aksi tersedia: ${actions.join(', ')}`}
            </span>
            <div className="flex flex-wrap items-center gap-2">
              {actions
                .filter((name): name is SalesOrderAction =>
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
            </div>
          </section>

          <section className={cn(CARD, 'grid grid-cols-1 gap-3 md:grid-cols-2')}>
            {orderDetailItems(order).map((item) => (
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
                WorkOrder
              </span>
              <span className="text-sm tabular-nums">{order.work_orders_count}</span>
            </div>
            <div className="flex flex-col gap-0.5">
              <span className="text-xs uppercase tracking-wide text-muted-foreground">
                Status Sync
              </span>
              <span className="text-sm font-mono">{displayOrDash(order.odoo_sync_status)}</span>
            </div>
          </section>

          <section className={cn(CARD, 'p-0')}>
            <DenseTable
              columns={LINE_COLUMNS}
              rows={lines}
              emptyMessage="Order ini belum punya baris."
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

