import { useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, CheckCircle2, Pencil, Send, Trash2, XCircle } from 'lucide-react';
import { Badge } from '@/components/atoms/Badge';
import { Button } from '@/components/atoms/Button';
import { Spinner } from '@/components/atoms/Spinner';
import { Toast, type ToastTone } from '@/components/atoms/Toast';
import { PageHeader } from '@/components/molecules/PageHeader';
import { actPayment, deletePayment, fetchPayment, type PaymentAction } from '@/api/payments';
import { useFeedback } from '@/app/app-runtime';
import { useApiClient } from '@/hooks/useApiClient';
import { cn } from '@/lib/cn';
import {
  paymentDetailItems,
  paymentStateLabel,
  paymentStateTone,
  paymentTypeLabel,
  paymentTypeTone,
  PAYMENT_ACTION_LABELS,
  PAYMENT_STATE_TO_ACTION,
} from '@/lib/payment';
import { CARD } from '@/lib/tokens';

/**
 * PaymentDetailPage - route `/finance/payments/:id` (H3.3, read-only + aksi).
 *
 * Menampilkan satu payment + dokumen sumbernya + jejak sync
 * (`odoo_sync_status`/`odoo_id`); tombol aksi mengikuti `allowed_actions` backend:
 *
 *   * **DRAFT** → `confirm` (push draft `account.payment` ke Odoo; butuh partner punya
 *     `odoo_id`, jumlah > 0, dan lolos guard anti-overpay) atau `cancel`; payment hanya
 *     bisa di-**Edit/Hapus** selama DRAFT;
 *   * **CONFIRMED/SENT** → `done` (murni MES) atau `cancel` (`action_cancel` bila
 *     `odoo_id` ada).
 *
 * **Rekonsiliasi bukan di MES**: posting & rekonsiliasi invoice/bill dilakukan akuntan
 * di Odoo — status bayar Odoo (`payment_state`) tidak ditarik ke MES pada modul ini.
 */

interface ToastState {
  tone: ToastTone;
  title: string;
  description: string;
}

/** Ikon per aksi transisi (label dari `PAYMENT_ACTION_LABELS`). */
const ACTION_ICONS = {
  confirm: Send,
  done: CheckCircle2,
  cancel: XCircle,
} as const;

export function PaymentDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const client = useApiClient();
  const queryClient = useQueryClient();
  const { trigger } = useFeedback();

  const [toast, setToast] = useState<ToastState | null>(null);

  const parsedId = id === undefined ? null : Number(id);
  const paymentId = parsedId !== null && Number.isFinite(parsedId) ? parsedId : null;

  const { data: payment, isLoading, error, refetch } = useQuery({
    queryKey: ['payment', paymentId],
    queryFn: () => fetchPayment(client, paymentId ?? 0),
    enabled: paymentId !== null,
    staleTime: 15_000,
  });

  function afterChange(message: string): void {
    trigger('success');
    setToast({ tone: 'success', title: message, description: 'Perubahan tersimpan di MES.' });
    void queryClient.invalidateQueries({ queryKey: ['payments'] });
    void refetch();
  }

  const runAction = useMutation({
    mutationFn: async (action: PaymentAction) => actPayment(client, paymentId ?? 0, action),
    onSuccess: (saved) => {
      afterChange(`${saved.code} → ${paymentStateLabel(saved.state)}`);
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
    mutationFn: async () => deletePayment(client, paymentId ?? 0),
    onSuccess: () => {
      trigger('success');
      navigate('/finance/payments');
    },
    onError: (caught) => {
      trigger('error');
      setToast({
        tone: 'error',
        title: 'Gagal menghapus payment',
        description: caught instanceof Error ? caught.message : 'Permintaan hapus gagal.',
      });
    },
  });

  const isDraft = payment?.state === 'DRAFT';
  const actions = payment?.allowed_actions ?? [];

  /** Tautan balik ke dokumen sumber (invoice H3.1 / bill H3.2). */
  const sourceHref =
    payment === undefined
      ? '/finance/payments'
      : payment.customer_invoice_id !== null
        ? `/finance/customer-invoices/${String(payment.customer_invoice_id)}`
        : `/finance/vendor-bills/${String(payment.vendor_bill_id ?? 0)}`;

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <PageHeader
        title={payment === undefined ? 'Detail Payment' : payment.code}
        subtitle="Payment MES — draft account.payment di Odoo, push saat CONFIRMED"
        breadcrumb={[
          { label: 'Finance', href: '/finance/payments' },
          { label: payment === undefined ? 'Detail' : payment.code },
        ]}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Button
              variant="secondary"
              icon={ArrowLeft}
              onClick={() => navigate('/finance/payments')}
            >
              Kembali
            </Button>

            <Button
              variant="secondary"
              disabled={payment === undefined}
              onClick={() => navigate(sourceHref)}
            >
              Lihat Dokumen
            </Button>

            <Button
              icon={Pencil}
              disabled={payment === undefined || !isDraft}
              onClick={() => navigate(`/finance/payments/${String(paymentId)}/edit`)}
            >
              Edit
            </Button>

            {actions.map((target) => {
              const action = PAYMENT_STATE_TO_ACTION[target];
              if (action === undefined) return null;

              return (
                <Button
                  key={target}
                  variant={action === 'cancel' ? 'secondary' : 'primary'}
                  icon={ACTION_ICONS[action]}
                  loading={runAction.isPending}
                  onClick={() => runAction.mutate(action)}
                >
                  {PAYMENT_ACTION_LABELS[target]}
                </Button>
              );
            })}

            <Button
              variant="secondary"
              icon={Trash2}
              disabled={payment === undefined || !isDraft}
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
          <Spinner size="sm" /> Memuat payment…
        </div>
      ) : null}

      {error !== null ? (
        <section className={cn(CARD, 'flex flex-col gap-2')}>
          <p role="alert" className="text-sm font-medium text-accent-coral">
            Gagal memuat payment (perlu login atau payment tidak ada).
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

      {payment !== undefined ? (
        <>
          <section className={cn(CARD, 'flex flex-wrap items-center gap-3')}>
            <span className="font-mono text-sm font-semibold text-foreground">{payment.code}</span>
            <Badge tone={paymentTypeTone(payment.payment_type)}>
              {paymentTypeLabel(payment.payment_type)}
            </Badge>
            <Badge tone={paymentStateTone(payment.state)}>{paymentStateLabel(payment.state)}</Badge>
            <Badge tone={payment.odoo_id === null ? 'coral' : 'blue'}>
              {payment.odoo_id === null ? 'Belum sync Odoo' : `Odoo #${String(payment.odoo_id)}`}
            </Badge>
            {payment.odoo_sync_status !== null ? (
              <Badge tone={payment.odoo_sync_status === 'FAILED' ? 'coral' : 'muted'}>
                {`Sync ${payment.odoo_sync_status}`}
              </Badge>
            ) : null}
          </section>

          {payment.odoo_sync_error !== null ? (
            <section className={cn(CARD, 'flex flex-col gap-1')}>
              <span className="text-xs font-medium text-muted-foreground">Error sync terakhir</span>
              <span className="text-sm text-accent-coral">{payment.odoo_sync_error}</span>
            </section>
          ) : null}

          <section className={cn(CARD, 'grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3')}>
            {paymentDetailItems(payment).map((item) => (
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

          {payment.source_amount_total !== null ? (
            <section className={cn(CARD, 'flex flex-wrap items-center gap-3 text-sm')}>
              <span className="text-muted-foreground">
                Total dokumen:{' '}
                <span className="font-mono tabular-nums text-foreground">
                  {payment.source_amount_total}
                </span>
              </span>
              <span className="text-muted-foreground">
                Sisa setelah payment ini:{' '}
                <span className="font-mono tabular-nums text-foreground">
                  {payment.source_remaining_amount ?? '-'}
                </span>
              </span>
            </section>
          ) : null}

          {payment.memo !== '' ? (
            <section className={cn(CARD, 'flex flex-col gap-1')}>
              <span className="text-xs font-medium text-muted-foreground">Catatan</span>
              <span className="text-sm text-foreground">{payment.memo}</span>
            </section>
          ) : null}
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

