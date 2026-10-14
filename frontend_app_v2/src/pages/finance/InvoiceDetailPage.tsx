import { useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, Banknote, CheckCircle2, Pencil, Send, Trash2, XCircle } from 'lucide-react';
import { Badge } from '@/components/atoms/Badge';
import { Button } from '@/components/atoms/Button';
import { Spinner } from '@/components/atoms/Spinner';
import { Toast, type ToastTone } from '@/components/atoms/Toast';
import { PageHeader } from '@/components/molecules/PageHeader';
import {
  actCustomerInvoice,
  deleteCustomerInvoice,
  fetchCustomerInvoice,
  type CustomerInvoiceAction,
} from '@/api/customerInvoices';
import { useFeedback } from '@/app/app-runtime';
import { useApiClient } from '@/hooks/useApiClient';
import { cn } from '@/lib/cn';
import {
  INVOICE_ACTION_LABELS,
  INVOICE_STATE_TO_ACTION,
  invoiceDetailItems,
  invoiceStateLabel,
  invoiceStateTone,
} from '@/lib/customer-invoice';
import { CARD } from '@/lib/tokens';

/**
 * InvoiceDetailPage - route `/finance/invoices/:id` (H3.1, read-only + aksi transisi).
 *
 * Menampilkan satu invoice + barisnya + jejak sync (`odoo_sync_status`/`odoo_id`);
 * tombol aksi mengikuti `allowed_actions` dari backend:
 *
 *   * **DRAFT** → `confirm` (push draft ke Odoo; butuh harga > 0 & master tersinkron)
 *     atau `cancel`; invoice hanya bisa di-**Edit/Hapus** selama DRAFT;
 *   * **CONFIRMED/SENT** → `done` (murni MES) atau `cancel` (`button_cancel` bila
 *     `odoo_id` ada); status push (`PENDING`/`FAILED`) terlihat pada badge sync.
 *
 * Push ke Odoo asinkron (`erp_sync.push_customer_invoice`) — pantau di `/settings/sync`.
 */

interface ToastState {
  tone: ToastTone;
  title: string;
  description: string;
}

/** Ikon per aksi transisi (label dari `INVOICE_ACTION_LABELS`). */
const ACTION_ICONS = {
  confirm: Send,
  done: CheckCircle2,
  cancel: XCircle,
} as const;

export function InvoiceDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const client = useApiClient();
  const queryClient = useQueryClient();
  const { trigger } = useFeedback();

  const [toast, setToast] = useState<ToastState | null>(null);

  const parsedId = id === undefined ? null : Number(id);
  const invoiceId = parsedId !== null && Number.isFinite(parsedId) ? parsedId : null;

  const { data: invoice, isLoading, error, refetch } = useQuery({
    queryKey: ['customer-invoice', invoiceId],
    queryFn: () => fetchCustomerInvoice(client, invoiceId ?? 0),
    enabled: invoiceId !== null,
    staleTime: 15_000,
  });

  function afterChange(message: string): void {
    trigger('success');
    setToast({ tone: 'success', title: message, description: 'Perubahan tersimpan di MES.' });
    void queryClient.invalidateQueries({ queryKey: ['customer-invoices'] });
    void refetch();
  }

  const runAction = useMutation({
    mutationFn: async (action: CustomerInvoiceAction) =>
      actCustomerInvoice(client, invoiceId ?? 0, action),
    onSuccess: (saved) => {
      afterChange(`${saved.code} → ${invoiceStateLabel(saved.state)}`);
    },
    onError: (caught) => {
      trigger('error');
      setToast({
        tone: 'error',
        title: 'Aksi gagal',
        description: caught instanceof Error ? caught.message : 'Permintaan aksi gagal.',
      });
    },
  });

  const remove = useMutation({
    mutationFn: async () => deleteCustomerInvoice(client, invoiceId ?? 0),
    onSuccess: () => {
      trigger('success');
      navigate('/finance/customer-invoices');
    },
    onError: (caught) => {
      trigger('error');
      setToast({
        tone: 'error',
        title: 'Gagal menghapus invoice',
        description: caught instanceof Error ? caught.message : 'Permintaan hapus gagal.',
      });
    },
  });

  const isDraft = invoice?.state === 'DRAFT';
  const actions = invoice?.allowed_actions ?? [];

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <PageHeader
        title={invoice === undefined ? 'Detail Invoice' : invoice.code}
        subtitle="Customer invoice MES — draft di Odoo, push saat CONFIRMED"
        breadcrumb={[
          { label: 'Finance', href: '/finance/invoices' },
          { label: 'Customer Invoice', href: '/finance/customer-invoices' },
          { label: invoice === undefined ? 'Detail' : invoice.code },
        ]}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Button
              variant="secondary"
              icon={ArrowLeft}
              onClick={() => navigate('/finance/customer-invoices')}
            >
              Kembali
            </Button>

            <Button
              icon={Pencil}
              disabled={invoice === undefined || !isDraft}
              onClick={() => navigate(`/finance/invoices/${String(invoiceId)}/edit`)}
            >
              Edit
            </Button>

            {/* H3.3 — bonus: catat pembayaran masuk untuk invoice ini (amount
                disarankan dari sisa; push `account.payment` draft saat CONFIRMED). */}
            <Button
              icon={Banknote}
              disabled={invoice === undefined || invoice.state === 'CANCELLED'}
              onClick={() => navigate(`/finance/payments/new?invoice=${String(invoiceId)}`)}
            >
              Bayar
            </Button>

            {actions.map((target) => {
              const action = INVOICE_STATE_TO_ACTION[target];
              if (action === undefined) return null;

              return (
                <Button
                  key={target}
                  variant={action === 'cancel' ? 'secondary' : 'primary'}
                  icon={ACTION_ICONS[action]}
                  loading={runAction.isPending}
                  onClick={() => runAction.mutate(action)}
                >
                  {INVOICE_ACTION_LABELS[target]}
                </Button>
              );
            })}

            <Button
              variant="secondary"
              icon={Trash2}
              disabled={invoice === undefined || !isDraft}
              loading={remove.isPending}
              onClick={() => remove.mutate()}
            >
              Hapus
            </Button>
          </div>
        }
      />

      {isLoading ? (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Spinner size="sm" /> Memuat invoice…
        </div>
      ) : null}

      {error !== null ? (
        <section className={cn(CARD, 'flex flex-col gap-2')}>
          <p role="alert" className="text-sm font-medium text-accent-coral">
            Gagal memuat invoice (perlu login atau invoice tidak ada).
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

      {invoice !== undefined ? (
        <>
          <section className={cn(CARD, 'flex flex-wrap items-center gap-3')}>
            <span className="font-mono text-sm font-semibold text-foreground">{invoice.code}</span>
            <Badge tone={invoiceStateTone(invoice.state)}>
              {invoiceStateLabel(invoice.state)}
            </Badge>
            <Badge tone={invoice.odoo_id === null ? 'coral' : 'blue'}>
              {invoice.odoo_id === null ? 'Belum sync Odoo' : `Odoo #${String(invoice.odoo_id)}`}
            </Badge>
            {invoice.odoo_sync_status !== null ? (
              <Badge tone={invoice.odoo_sync_status === 'FAILED' ? 'coral' : 'muted'}>
                {`Sync ${invoice.odoo_sync_status}`}
              </Badge>
            ) : null}
          </section>

          {invoice.odoo_sync_error !== null ? (
            <section className={cn(CARD, 'flex flex-col gap-1')}>
              <span className="text-xs font-medium text-muted-foreground">Error sync terakhir</span>
              <span className="text-sm text-accent-coral">{invoice.odoo_sync_error}</span>
            </section>
          ) : null}

          <section className={cn(CARD, 'grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3')}>
            {invoiceDetailItems(invoice).map((item) => (
              <div key={item.label} className="flex flex-col gap-1">
                <span className="text-xs font-medium text-muted-foreground">{item.label}</span>
                <span
                  className={cn(
                    'text-sm text-foreground',
                    item.mono === true ? 'font-mono' : undefined,
                  )}
                >
                  {item.value}
                </span>
              </div>
            ))}
          </section>

  const isDraft = invoice?.state === 'DRAFT';
  const actions = invoice?.allowed_actions ?? [];

          <section className={cn(CARD, 'flex flex-col gap-3')}>
            <h2 className="text-sm font-semibold text-foreground">
              Baris Invoice ({String(invoice.lines.length)} baris)
            </h2>

            {invoice.lines.map((line) => (
              <div
                key={line.id}
                className="grid grid-cols-1 items-center gap-3 border-t border-border pt-3 md:grid-cols-12"
              >
                <div className="flex flex-col gap-1 md:col-span-4">
                  <span className="text-xs font-medium text-muted-foreground">
                    {line.product_code ?? '-'}
                  </span>
                  <span className="text-sm text-foreground">{line.product_name ?? '-'}</span>
                </div>
                <div className="flex flex-col gap-1 md:col-span-2">
                  <span className="text-xs font-medium text-muted-foreground">Qty</span>
                  <span className="font-mono text-sm tabular-nums">{line.qty}</span>
                </div>
                <div className="flex flex-col gap-1 md:col-span-2">
                  <span className="text-xs font-medium text-muted-foreground">Harga</span>
                  <span className="font-mono text-sm tabular-nums">{line.price_unit}</span>
                </div>
                <div className="flex flex-col gap-1 md:col-span-4">
                  <span className="text-xs font-medium text-muted-foreground">Subtotal</span>
                  <span className="font-mono text-sm tabular-nums">{line.subtotal}</span>
                </div>
              </div>
            ))}
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

