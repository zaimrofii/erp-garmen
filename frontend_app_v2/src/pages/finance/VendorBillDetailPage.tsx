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
  actVendorBill,
  deleteVendorBill,
  fetchVendorBill,
  type VendorBillAction,
} from '@/api/vendorBills';
import { useFeedback } from '@/app/app-runtime';
import { useApiClient } from '@/hooks/useApiClient';
import { cn } from '@/lib/cn';
import {
  BILL_ACTION_LABELS,
  BILL_STATE_TO_ACTION,
  billDetailItems,
  billStateLabel,
  billStateTone,
} from '@/lib/vendor-bill';
import { CARD } from '@/lib/tokens';

/**
 * VendorBillDetailPage - route `/finance/vendor-bills/:id` (H3.2, read-only + aksi).
 *
 * Menampilkan satu bill + barisnya + jejak sync (`odoo_sync_status`/`odoo_id`); tombol
 * aksi mengikuti `allowed_actions` dari backend:
 *
 *   * **DRAFT** → `confirm` (push draft `in_invoice` ke Odoo; butuh vendor/produk/pajak
 *     sudah punya `odoo_id` + qty > 0) atau `cancel`; bill hanya bisa di-**Edit/Hapus**
 *     selama DRAFT;
 *   * **CONFIRMED/SENT** → `done` (murni MES) atau `cancel` (`button_cancel` bila
 *     `odoo_id` ada); status push (`PENDING`/`FAILED`) terlihat pada badge sync —
 *     kegagalan push **tidak** mengubah state bill (bisa di-retry).
 *
 * Push ke Odoo asinkron (`erp_sync.push_vendor_bill`) — pantau di `/settings/sync`.
 */

interface ToastState {
  tone: ToastTone;
  title: string;
  description: string;
}

/** Ikon per aksi transisi (label dari `BILL_ACTION_LABELS`). */
const ACTION_ICONS = {
  confirm: Send,
  done: CheckCircle2,
  cancel: XCircle,
} as const;

export function VendorBillDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const client = useApiClient();
  const queryClient = useQueryClient();
  const { trigger } = useFeedback();

  const [toast, setToast] = useState<ToastState | null>(null);

  const parsedId = id === undefined ? null : Number(id);
  const billId = parsedId !== null && Number.isFinite(parsedId) ? parsedId : null;

  const { data: bill, isLoading, error, refetch } = useQuery({
    queryKey: ['vendor-bill', billId],
    queryFn: () => fetchVendorBill(client, billId ?? 0),
    enabled: billId !== null,
    staleTime: 15_000,
  });

  function afterChange(message: string): void {
    trigger('success');
    setToast({ tone: 'success', title: message, description: 'Perubahan tersimpan di MES.' });
    void queryClient.invalidateQueries({ queryKey: ['vendor-bills'] });
    void refetch();
  }

  const runAction = useMutation({
    mutationFn: async (action: VendorBillAction) => actVendorBill(client, billId ?? 0, action),
    onSuccess: (saved) => {
      afterChange(`${saved.code} → ${billStateLabel(saved.state)}`);
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
    mutationFn: async () => deleteVendorBill(client, billId ?? 0),
    onSuccess: () => {
      trigger('success');
      navigate('/finance/vendor-bills');
    },
    onError: (caught) => {
      trigger('error');
      setToast({
        tone: 'error',
        title: 'Gagal menghapus vendor bill',
        description: caught instanceof Error ? caught.message : 'Permintaan hapus gagal.',
      });
    },
  });

  const isDraft = bill?.state === 'DRAFT';
  const actions = bill?.allowed_actions ?? [];

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <PageHeader
        title={bill === undefined ? 'Detail Vendor Bill' : bill.code}
        subtitle="Vendor bill MES — draft in_invoice di Odoo, push saat CONFIRMED"
        breadcrumb={[
          { label: 'Finance', href: '/finance/vendor-bills' },
          { label: bill === undefined ? 'Detail' : bill.code },
        ]}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Button
              variant="secondary"
              icon={ArrowLeft}
              onClick={() => navigate('/finance/vendor-bills')}
            >
              Kembali
            </Button>

            <Button
              icon={Pencil}
              disabled={bill === undefined || !isDraft}
              onClick={() => navigate(`/finance/vendor-bills/${String(billId)}/edit`)}
            >
              Edit
            </Button>

            {/* H3.3 — bonus: catat pembayaran keluar untuk bill ini (amount
                disarankan dari sisa; push `account.payment` draft saat CONFIRMED). */}
            <Button
              icon={Banknote}
              disabled={bill === undefined || bill.state === 'CANCELLED'}
              onClick={() => navigate(`/finance/payments/new?bill=${String(billId)}`)}
            >
              Bayar
            </Button>

            {actions.map((target) => {
              const action = BILL_STATE_TO_ACTION[target];
              if (action === undefined) return null;

              return (
                <Button
                  key={target}
                  variant={action === 'cancel' ? 'secondary' : 'primary'}
                  icon={ACTION_ICONS[action]}
                  loading={runAction.isPending}
                  onClick={() => runAction.mutate(action)}
                >
                  {BILL_ACTION_LABELS[target]}
                </Button>
              );
            })}

            <Button
              variant="secondary"
              icon={Trash2}
              disabled={bill === undefined || !isDraft}
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
          <Spinner size="sm" /> Memuat vendor bill…
        </div>
      ) : null}

      {error !== null ? (
        <section className={cn(CARD, 'flex flex-col gap-2')}>
          <p role="alert" className="text-sm font-medium text-accent-coral">
            Gagal memuat vendor bill (perlu login atau bill tidak ada).
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

      {bill !== undefined ? (
        <>
          <section className={cn(CARD, 'flex flex-wrap items-center gap-3')}>
            <span className="font-mono text-sm font-semibold text-foreground">{bill.code}</span>
            <Badge tone={billStateTone(bill.state)}>{billStateLabel(bill.state)}</Badge>
            <Badge tone={bill.odoo_id === null ? 'coral' : 'blue'}>
              {bill.odoo_id === null ? 'Belum sync Odoo' : `Odoo #${String(bill.odoo_id)}`}
            </Badge>
            {bill.odoo_sync_status !== null ? (
              <Badge tone={bill.odoo_sync_status === 'FAILED' ? 'coral' : 'muted'}>
                {`Sync ${bill.odoo_sync_status}`}
              </Badge>
            ) : null}
          </section>

          {bill.odoo_sync_error !== null ? (
            <section className={cn(CARD, 'flex flex-col gap-1')}>
              <span className="text-xs font-medium text-muted-foreground">Error sync terakhir</span>
              <span className="text-sm text-accent-coral">{bill.odoo_sync_error}</span>
            </section>
          ) : null}

          <section className={cn(CARD, 'grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3')}>
            {billDetailItems(bill).map((item) => (
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

          <section className={cn(CARD, 'flex flex-col gap-3')}>
            <h2 className="text-sm font-semibold text-foreground">
              Baris Bill ({String(bill.lines.length)} baris)
            </h2>

            {bill.lines.map((line) => (
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

