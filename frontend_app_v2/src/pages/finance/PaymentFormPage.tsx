import { useMemo, useState, type FormEvent } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { useMutation, useQuery } from '@tanstack/react-query';
import { ArrowLeft, Save } from 'lucide-react';
import { Button } from '@/components/atoms/Button';
import { Input } from '@/components/atoms/Input';
import { Select } from '@/components/atoms/Select';
import { Spinner } from '@/components/atoms/Spinner';
import { Toast, type ToastTone } from '@/components/atoms/Toast';
import { PageHeader } from '@/components/molecules/PageHeader';
import {
  createPayment,
  fetchPayment,
  fetchPayments,
  updatePayment,
  PAYMENTS_LIMIT_MAX,
} from '@/api/payments';
import {
  fetchCustomerInvoice,
  fetchCustomerInvoices,
  INVOICES_LIMIT_MAX,
} from '@/api/customerInvoices';
import { fetchVendorBill, fetchVendorBills, VENDOR_BILLS_LIMIT_MAX } from '@/api/vendorBills';
import { useFeedback } from '@/app/app-runtime';
import { useApiClient } from '@/hooks/useApiClient';
import { cn } from '@/lib/cn';
import {
  billOptionLabel,
  EMPTY_PAYMENT_FORM,
  invoiceOptionLabel,
  isPaymentFormValid,
  NO_BILL_OPTION,
  NO_INVOICE_OPTION,
  paymentFormFromDetail,
  paymentInputFromForm,
  PAYMENT_METHOD_OPTIONS,
  PAYMENT_TYPE_OPTIONS,
  remainingForSource,
  switchPaymentType,
  suggestedAmount,
  validatePaymentForm,
  type PaymentFormValues,
} from '@/lib/payment';
import { CARD } from '@/lib/tokens';
import type { PaymentType } from '@/types/payment';

/**
 * PaymentFormPage - route `/finance/payments/new` + `…/:id/edit` (H3.3).
 *
 * **Satu form, dua arah** (keputusan STEP 0: `payment_type` sebagai field, bukan
 * resource/stage terpisah):
 *
 *   * **INBOUND** → pilih **customer invoice** (H3.1); partner diturunkan dari invoice;
 *   * **OUTBOUND** → pilih **vendor bill** (H3.2); partner diturunkan dari bill;
 *   * jumlah bayar **disarankan** dari sisa dokumen (`amount_total` − Σ payment aktif,
 *     dihitung client-side lewat `?customer_invoice_id=`/`?vendor_bill_id=`), tetap
 *     bisa diubah — backend menegakkan guard anti-overpay (400 bila melebihi sisa);
 *   * prefill dari halaman lain: `/finance/payments/new?invoice=<id>` (dari detail
 *     invoice H3.1) atau `?bill=<id>` (dari detail bill H3.2);
 *   * create → `POST /api/v1/finance/payments/`; edit → `PUT …/<id>/` (DRAFT-only);
 *   * push ke Odoo (`account.payment` **draft**) terjadi saat `CONFIRMED` di halaman
 *     detail; **rekonsiliasi tetap di Odoo** (MES tidak merekonsiliasi).
 */

interface ToastState {
  tone: ToastTone;
  title: string;
  description: string;
}

/** PURE — tanggal hari ini (`YYYY-MM-DD`) untuk nilai awal form. */
function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

export function PaymentFormPage() {
  const { id } = useParams<{ id: string }>();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const client = useApiClient();
  const { trigger } = useFeedback();

  const parsedId = id === undefined ? null : Number(id);
  const paymentId = parsedId !== null && Number.isFinite(parsedId) ? parsedId : null;
  const isEdit = paymentId !== null;

  const seededInvoice = params.get('invoice') ?? '';
  const seededBill = params.get('bill') ?? '';
  const seededType: PaymentType = seededBill !== '' ? 'OUTBOUND' : 'INBOUND';

  const [draft, setDraft] = useState<PaymentFormValues | null>(null);
  const [submitted, setSubmitted] = useState(false);
  const [toast, setToast] = useState<ToastState | null>(null);

  const detail = useQuery({
    queryKey: ['payment', paymentId],
    queryFn: () => fetchPayment(client, paymentId ?? 0),
    enabled: isEdit,
    staleTime: 15_000,
  });

  const invoices = useQuery({
    queryKey: ['payment-source-invoices'],
    queryFn: () => fetchCustomerInvoices(client, { limit: INVOICES_LIMIT_MAX }),
    staleTime: 60_000,
  });

  const bills = useQuery({
    queryKey: ['payment-source-bills'],
    queryFn: () => fetchVendorBills(client, { limit: VENDOR_BILLS_LIMIT_MAX }),
    staleTime: 60_000,
  });

  const values = useMemo<PaymentFormValues | null>(() => {
    if (draft !== null) return draft;
    if (isEdit) {
      return detail.data === undefined ? null : paymentFormFromDetail(detail.data);
    }

    return {
      ...EMPTY_PAYMENT_FORM,
      payment_type: seededType,
      customer_invoice_id: seededType === 'INBOUND' ? seededInvoice : '',
      vendor_bill_id: seededType === 'OUTBOUND' ? seededBill : '',
      payment_date: todayIso(),
    };
  }, [draft, detail.data, isEdit, seededBill, seededInvoice, seededType]);

  const current = values ?? EMPTY_PAYMENT_FORM;
  const errors = useMemo(() => validatePaymentForm(current), [current]);
  const valid = values !== null && isPaymentFormValid(errors);

  /** Info dokumen sumber (diisi saat operator memilih sumber / dari detail saat edit). */
  const [sourceInfo, setSourceInfo] = useState<{
    amountTotal: string;
    remaining: string;
    partnerName: string | null;
  } | null>(null);

  const sourcePanel = useMemo(() => {
    if (sourceInfo !== null) return sourceInfo;
    const data = detail.data;
    if (data === undefined) return null;

    return {
      amountTotal: data.source_amount_total ?? '0.00',
      remaining: data.source_remaining_amount ?? '0.00',
      partnerName: data.partner_name,
    };
  }, [detail.data, sourceInfo]);

  const invoiceOptions = useMemo<{ value: string; label: string }[]>(() => {
    const rows = invoices.data?.rows ?? [];

    return [
      NO_INVOICE_OPTION,
      ...rows.map((row) => ({ value: String(row.id), label: invoiceOptionLabel(row) })),
    ];
  }, [invoices.data]);

  const billOptions = useMemo<{ value: string; label: string }[]>(() => {
    const rows = bills.data?.rows ?? [];

    return [
      NO_BILL_OPTION,
      ...rows.map((row) => ({ value: String(row.id), label: billOptionLabel(row) })),
    ];
  }, [bills.data]);

  function setField<K extends keyof PaymentFormValues>(
    field: K,
    value: PaymentFormValues[K],
  ): void {
    setDraft({ ...current, [field]: value });
  }

  /**
   * Ganti dokumen sumber → muat detail + payment aktifnya, lalu **sarankan** jumlah
   * bayar = sisa dokumen (hanya bila operator belum mengetik jumlahnya).
   */
  async function handleSourceChange(next: string): Promise<void> {
    const inbound = current.payment_type === 'INBOUND';
    const base = inbound
      ? { ...current, customer_invoice_id: next, amount: '' }
      : { ...current, vendor_bill_id: next, amount: '' };
    setDraft(base);
    setSourceInfo(null);
    if (next === '') return;

    try {
      const source = inbound
        ? await fetchCustomerInvoice(client, Number(next))
        : await fetchVendorBill(client, Number(next));
      const payments = await fetchPayments(
        client,
        inbound
          ? { customer_invoice_id: Number(next), limit: PAYMENTS_LIMIT_MAX }
          : { vendor_bill_id: Number(next), limit: PAYMENTS_LIMIT_MAX },
      );
      const suggestion = suggestedAmount(source.amount_total, payments.rows);
      const partnerName = 'customer_name' in source ? source.customer_name : source.vendor_name;

      setSourceInfo({
        amountTotal: source.amount_total,
        remaining: remainingForSource(source.amount_total, payments.rows).toFixed(2),
        partnerName,
      });
      setDraft((existing) =>
        existing === null
          ? existing
          : { ...existing, amount: existing.amount.trim() === '' ? suggestion : existing.amount },
      );
    } catch {
      //: Dokumen gagal dimuat → biarkan form apa adanya (jumlah bisa diisi manual).
    }
  }

  /** Ganti arah bayar: sumber lawan dikosongkan + jumlah & info direset. */
  function handleTypeChange(next: PaymentType): void {
    setDraft({ ...switchPaymentType(current, next), amount: '' });
    setSourceInfo(null);
  }


  const save = useMutation({
    mutationFn: async () => {
      const input = paymentInputFromForm(current);

      return isEdit ? updatePayment(client, paymentId ?? 0, input) : createPayment(client, input);
    },
    onSuccess: (saved) => {
      trigger('success');
      setToast({
        tone: 'success',
        title: isEdit ? 'Payment diperbarui' : 'Payment dibuat',
        description: `${saved.code} — ${saved.amount} ${saved.currency} untuk ${saved.source_label}.`,
      });
      navigate(`/finance/payments/${String(saved.id)}`);
    },
    onError: (caught) => {
      trigger('error');
      setToast({
        tone: 'error',
        title: 'Gagal menyimpan payment',
        description: caught instanceof Error ? caught.message : 'Permintaan simpan gagal.',
      });
    },
  });

  function handleSubmit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    setSubmitted(true);

    if (!valid || save.isPending) return;

    save.mutate();
  }

  const showErrors = submitted;
  const isInbound = current.payment_type === 'INBOUND';

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <PageHeader
        title={isEdit ? 'Edit Payment' : 'Payment Baru'}
        subtitle="Pembayaran MES — draft account.payment dikirim ke Odoo saat CONFIRMED"
        breadcrumb={[
          { label: 'Finance', href: '/finance/payments' },
          { label: isEdit ? 'Edit' : 'Baru' },
        ]}
        actions={
          <Button variant="ghost" icon={ArrowLeft} onClick={() => navigate('/finance/payments')}>
            Kembali
          </Button>
        }
      />

      {isEdit && detail.isLoading ? (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Spinner size="sm" /> Memuat payment…
        </div>
      ) : null}

      {isEdit && detail.error !== null ? (
        <section className={cn(CARD, 'flex flex-col gap-2')}>
          <p role="alert" className="text-sm font-medium text-accent-coral">
            Gagal memuat payment (perlu login atau payment tidak ada).
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

      <form className="flex flex-col gap-4" onSubmit={handleSubmit}>
        <section className={cn(CARD, 'flex flex-col gap-3')}>
          <h2 className="text-sm font-semibold text-foreground">Arah Pembayaran</h2>
          <div className="flex flex-wrap items-center gap-2">
            {PAYMENT_TYPE_OPTIONS.map((option) => (
              <Button
                key={option.id}
                type="button"
                variant={current.payment_type === option.id ? 'primary' : 'secondary'}
                onClick={() => handleTypeChange(option.id)}
              >
                {option.label}
              </Button>
            ))}
          </div>
          <p className="text-xs text-muted-foreground">
            {PAYMENT_TYPE_OPTIONS.find((option) => option.id === current.payment_type)?.description ??
              ''}
          </p>
        </section>

        <section className={cn(CARD, 'grid grid-cols-1 gap-4 md:grid-cols-2')}>
          {isInbound ? (
            <Select
              label="Customer Invoice *"
              options={invoiceOptions}
              value={current.customer_invoice_id}
              onChange={(event) => {
                void handleSourceChange(event.target.value);
              }}
              {...(showErrors && errors.source !== undefined ? { error: errors.source } : {})}
            />
          ) : (
            <Select
              label="Vendor Bill *"
              options={billOptions}
              value={current.vendor_bill_id}
              onChange={(event) => {
                void handleSourceChange(event.target.value);
              }}
              {...(showErrors && errors.source !== undefined ? { error: errors.source } : {})}
            />
          )}

          <Input
            label="Jumlah bayar *"
            type="number"
            min="0"
            step="0.01"
            value={current.amount}
            placeholder={isInbound ? 'mis. 20000.00' : 'mis. 15000.00'}
            onChange={(event) => setField('amount', event.target.value)}
            {...(showErrors && errors.amount !== undefined ? { error: errors.amount } : {})}
          />

          <Input
            label="Tanggal bayar *"
            type="date"
            value={current.payment_date}
            onChange={(event) => setField('payment_date', event.target.value)}
            {...(showErrors && errors.payment_date !== undefined
              ? { error: errors.payment_date }
              : {})}
          />

          <Select
            label="Cara bayar"
            options={PAYMENT_METHOD_OPTIONS}
            value={current.payment_method}
            onChange={(event) =>
              setField('payment_method', event.target.value as PaymentFormValues['payment_method'])
            }
          />

          <Input
            label="Referensi bank"
            value={current.reference}
            placeholder="mis. TRF-20261013-001 (boleh kosong)"
            onChange={(event) => setField('reference', event.target.value)}
            {...(showErrors && errors.reference !== undefined
              ? { error: errors.reference }
              : {})}
          />

          <Input
            label="Catatan"
            value={current.memo}
            placeholder="mis. pembayaran termin 1"
            onChange={(event) => setField('memo', event.target.value)}
          />
        </section>

        {sourcePanel !== null ? (
          <section className={cn(CARD, 'flex flex-col gap-2')}>
            <h2 className="text-sm font-semibold text-foreground">Dokumen sumber</h2>
            <div className="flex flex-wrap items-center gap-3 text-sm">
              <span className="text-muted-foreground">
                Partner:{' '}
                <span className="text-foreground">{sourcePanel.partnerName ?? '-'}</span>
              </span>
              <span className="text-muted-foreground">
                Total dokumen:{' '}
                <span className="font-mono tabular-nums text-foreground">
                  {sourcePanel.amountTotal}
                </span>
              </span>
              <span className="text-muted-foreground">
                Sisa setelah payment ini:{' '}
                <span className="font-mono tabular-nums text-foreground">
                  {sourcePanel.remaining}
                </span>
              </span>
            </div>
            <p className="text-xs text-muted-foreground">
              Sisa dihitung MES (total dokumen − Σ payment aktif). Backend tetap menolak bila
              jumlah melebihi sisa (guard anti-overpay).
            </p>
          </section>
        ) : null}

        <section className={cn(CARD, 'flex flex-wrap items-center justify-between gap-3')}>
          <div className="flex flex-col gap-1">
            <p className="text-sm font-semibold text-foreground">
              Jumlah: <span className="font-mono tabular-nums">{current.amount || '0.00'}</span>{' '}
              {current.currency}
            </p>
            <p className="text-xs text-muted-foreground">
              Payment lahir DRAFT (MES-only). Push ke Odoo (draft `account.payment`) terjadi saat
              CONFIRMED; posting &amp; rekonsiliasi dilakukan akuntan di Odoo.
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <Button type="submit" icon={Save} loading={save.isPending}>
              {isEdit ? 'Simpan Perubahan' : 'Simpan Payment'}
            </Button>
            <Button
              type="button"
              variant="secondary"
              onClick={() => navigate('/finance/payments')}
            >
              Batal
            </Button>
          </div>
        </section>
      </form>

      <Toast
        open={toast !== null}
        onOpenChange={() => setToast(null)}
        title={toast?.title ?? ''}
        {...(toast === null ? {} : { tone: toast.tone, description: toast.description })}
      />
    </div>
  );
}



