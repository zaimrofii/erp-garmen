import { useMemo, useState, type FormEvent } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { useMutation, useQuery } from '@tanstack/react-query';
import { ArrowLeft, Plus, Save, Trash2 } from 'lucide-react';
import { Button } from '@/components/atoms/Button';
import { Input } from '@/components/atoms/Input';
import { Select } from '@/components/atoms/Select';
import { Spinner } from '@/components/atoms/Spinner';
import { Toast, type ToastTone } from '@/components/atoms/Toast';
import { PageHeader } from '@/components/molecules/PageHeader';
import {
  createCustomerInvoice,
  fetchCustomerInvoice,
  updateCustomerInvoice,
} from '@/api/customerInvoices';
import { fetchProducts, PRODUCTS_LIMIT_MAX } from '@/api/masterProducts';
import { fetchPartners, PARTNERS_LIMIT_MAX } from '@/api/masterPartners';
import { fetchTaxes, TAXES_LIMIT_MAX } from '@/api/masterTaxes';
import { fetchOrder, fetchOrders } from '@/api/salesOrders';
import { useFeedback } from '@/app/app-runtime';
import { useApiClient } from '@/hooks/useApiClient';
import { cn } from '@/lib/cn';
import {
  addInvoiceLine,
  EMPTY_INVOICE_FORM,
  invoiceFormFromDetail,
  invoiceFormFromOrderDetail,
  invoiceFormTotal,
  invoiceInputFromForm,
  isInvoiceFormValid,
  lineSubtotal,
  NO_CUSTOMER_OPTION,
  NO_ORDER_OPTION,
  NO_TAX_OPTION,
  removeInvoiceLine,
  updateInvoiceLine,
  validateInvoiceForm,
  type InvoiceFormValues,
} from '@/lib/customer-invoice';
import { taxOptionLabel } from '@/lib/master-tax';
import { CARD } from '@/lib/tokens';

/**
 * InvoiceFormPage - route `/finance/invoices/new` + `/finance/invoices/:id/edit` (H3.1).
 *
 * Header (order, customer, tanggal invoice, jatuh tempo, catatan) + **editor baris
 * INLINE** (produk, qty, harga, pajak, subtotal):
 *
 *   * **auto-fill dari OrderLine** (H2.1): memilih order — atau membuka
 *     `/finance/invoices/new?order=<id>` dari tombol "Buat Invoice" di detail order —
 *     mengisi baris qty × harga + pajak secara otomatis (tetap editable);
 *   * `lines` selalu dikirim → backend memakai baris apa adanya (tanpa auto-fill ganda);
 *   * create → `POST /api/v1/finance/customer-invoices/`; edit → `PUT …/<id>/`
 *     (DRAFT-only; backend menolak 400 setelah CONFIRMED);
 *   * sukses create → Toast (termasuk `duplicate_warning` = order sudah punya invoice
 *     aktif → termin/DP, **bukan** error) → pindah ke detail;
 *   * push ke Odoo terjadi **saat CONFIRMED** (aksi di halaman detail), bukan di sini.
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

export function InvoiceFormPage() {
  const { id } = useParams<{ id: string }>();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const client = useApiClient();
  const { trigger } = useFeedback();

  const parsedId = id === undefined ? null : Number(id);
  const invoiceId = parsedId !== null && Number.isFinite(parsedId) ? parsedId : null;
  const isEdit = invoiceId !== null;

  const seededOrder = params.get('order') ?? '';
  const [draft, setDraft] = useState<InvoiceFormValues | null>(null);
  const [submitted, setSubmitted] = useState(false);
  const [toast, setToast] = useState<ToastState | null>(null);

  const detail = useQuery({
    queryKey: ['customer-invoice', invoiceId],
    queryFn: () => fetchCustomerInvoice(client, invoiceId ?? 0),
    enabled: isEdit,
    staleTime: 15_000,
  });

  /** Order (pilihan) + master data untuk dropdown baris. */
  const orders = useQuery({
    queryKey: ['sales-orders', 'invoice-options'],
    queryFn: () => fetchOrders(client, { limit: 200 }),
    staleTime: 60_000,
  });

  const partners = useQuery({
    queryKey: ['master-partners', 'invoice-options'],
    queryFn: () => fetchPartners(client, { limit: PARTNERS_LIMIT_MAX }),
    staleTime: 60_000,
  });

  const products = useQuery({
    queryKey: ['master-products', 'invoice-options'],
    queryFn: () => fetchProducts(client, { limit: PRODUCTS_LIMIT_MAX, active: true }),
    staleTime: 60_000,
  });

  const taxes = useQuery({
    queryKey: ['master-taxes', 'invoice-options'],
    queryFn: () =>
      fetchTaxes(client, { type_tax_use: 'sale', active: true, limit: TAXES_LIMIT_MAX }),
    staleTime: 60_000,
  });

  /** Prefill dari `?order=` (tombol "Buat Invoice" di detail order H2.1). */
  const prefill = useQuery({
    queryKey: ['sales-order', seededOrder, 'invoice-prefill'],
    queryFn: () => fetchOrder(client, Number(seededOrder)),
    enabled: !isEdit && seededOrder !== '' && draft === null,
    staleTime: 15_000,
  });

  /**
   * Nilai form = draft pengguna → data GET (edit) → prefill `?order=` → form kosong.
   * Semuanya **derived** (tanpa `useEffect`) supaya tidak ada setState saat render.
   */
  const values: InvoiceFormValues = (() => {
    if (draft !== null) return draft;
    if (isEdit) {
      return detail.data === undefined ? EMPTY_INVOICE_FORM : invoiceFormFromDetail(detail.data);
    }
    if (seededOrder !== '' && prefill.data !== undefined) {
      return {
        ...invoiceFormFromOrderDetail(prefill.data),
        order_id: seededOrder,
        invoice_date: todayIso(),
      };
    }

    return { ...EMPTY_INVOICE_FORM, order_id: seededOrder, invoice_date: todayIso() };
  })();

  const errors = useMemo(() => validateInvoiceForm(values), [values]);
  const valid = isInvoiceFormValid(errors);
  const total = invoiceFormTotal(values);

  const orderOptions = useMemo<{ value: string; label: string }[]>(() => {
    const rows = orders.data?.rows ?? [];

    return [
      NO_ORDER_OPTION,
      ...rows.map((row) => ({
        value: String(row.id),
        label: `${row.code} — ${row.customer_name ?? '-'}`,
      })),
    ];
  }, [orders.data]);

  const customerOptions = useMemo<{ value: string; label: string }[]>(() => {
    const rows = partners.data?.rows ?? [];

    return [
      NO_CUSTOMER_OPTION,
      ...rows.map((row) => ({ value: String(row.id), label: `${row.code} - ${row.name}` })),
    ];
  }, [partners.data]);

  const productOptions = useMemo<{ value: string; label: string }[]>(() => {
    const rows = products.data?.rows ?? [];

    return [
      { value: '', label: '— Pilih produk —' },
      ...rows.map((row) => ({ value: String(row.id), label: `${row.code} - ${row.name}` })),
    ];
  }, [products.data]);

  const taxOptions = useMemo<{ value: string; label: string }[]>(() => {
    const rows = taxes.data?.rows ?? [];

    return [
      NO_TAX_OPTION,
      ...rows.map((row) => ({ value: String(row.id), label: taxOptionLabel(row) })),
    ];
  }, [taxes.data]);

  /** Ganti order → ambil barisnya (auto-fill); customer mengikuti order tersebut. */
  async function handleOrderChange(next: string): Promise<void> {
    const base = { ...values, order_id: next };
    setDraft(base);
    if (next === '') return;

    try {
      const orderDetail = await fetchOrder(client, Number(next));
      setDraft((current) => {
        const origin = current ?? base;
        const filled = invoiceFormFromOrderDetail(orderDetail);

        return { ...origin, customer_id: filled.customer_id, lines: filled.lines };
      });
    } catch {
      // Order gagal dimuat → biarkan form apa adanya (baris bisa diisi manual).
    }
  }

  function setField<K extends keyof InvoiceFormValues>(
    field: K,
    value: InvoiceFormValues[K],
  ): void {
    setDraft({ ...values, [field]: value });
  }

  const save = useMutation({
    mutationFn: async () => {
      const input = invoiceInputFromForm(values);

      return isEdit
        ? updateCustomerInvoice(client, invoiceId, input)
        : createCustomerInvoice(client, input);
    },
    onSuccess: (saved) => {
      trigger('success');
      setToast({
        tone: 'success',
        title: isEdit ? 'Invoice diperbarui' : 'Invoice dibuat',
        description:
          `${saved.code} — ${String(saved.lines_count)} baris, total ${saved.amount_total}.` +
          (saved.duplicate_warning ? ` ${saved.duplicate_warning}` : ''),
      });
      navigate(`/finance/invoices/${String(saved.id)}`);
    },
    onError: (caught) => {
      trigger('error');
      setToast({
        tone: 'error',
        title: 'Gagal menyimpan invoice',
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

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <PageHeader
        title={isEdit ? 'Edit Invoice' : 'Invoice Baru'}
        subtitle="Customer invoice MES — draft dikirim ke Odoo saat CONFIRMED"
        breadcrumb={[
          { label: 'Finance', href: '/finance/invoices' },
          { label: 'Customer Invoice', href: '/finance/customer-invoices' },
          { label: isEdit ? 'Edit' : 'Baru' },
        ]}
        actions={
          <Button
            variant="ghost"
            icon={ArrowLeft}
            onClick={() => navigate('/finance/customer-invoices')}
          >
            Kembali
          </Button>
        }
      />

      {isEdit && detail.isLoading ? (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Spinner size="sm" /> Memuat invoice…
        </div>
      ) : null}

      {isEdit && detail.error !== null ? (
        <section className={cn(CARD, 'flex flex-col gap-2')}>
          <p role="alert" className="text-sm font-medium text-accent-coral">
            Gagal memuat invoice (perlu login atau invoice tidak ada).
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
        <section className={cn(CARD, 'grid grid-cols-1 gap-4 md:grid-cols-2')}>
          <Select
            label="Order *"
            options={orderOptions}
            value={values.order_id}
            onChange={(event) => {
              void handleOrderChange(event.target.value);
            }}
            {...(showErrors && errors.order_id !== undefined ? { error: errors.order_id } : {})}
          />
          <Select
            label="Customer"
            options={customerOptions}
            value={values.customer_id}
            onChange={(event) => setField('customer_id', event.target.value)}
          />
          <Input
            label="Tanggal invoice *"
            type="date"
            value={values.invoice_date}
            onChange={(event) => setField('invoice_date', event.target.value)}
            {...(showErrors && errors.invoice_date !== undefined
              ? { error: errors.invoice_date }
              : {})}
          />
          <Input
            label="Jatuh tempo"
            type="date"
            value={values.due_date}
            onChange={(event) => setField('due_date', event.target.value)}
          />
          <Input
            label="Catatan"
            value={values.notes}
            placeholder="mis. termin 1 dari 3"
            onChange={(event) => setField('notes', event.target.value)}
          />
        </section>

        <section className={cn(CARD, 'flex flex-col gap-3')}>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-sm font-semibold text-foreground">
              Baris Invoice ({String(values.lines.length)} baris)
            </h2>
            <Button
              type="button"
              variant="secondary"
              size="sm"
              icon={Plus}
              onClick={() => setDraft(addInvoiceLine(values))}
            >
              Tambah Baris
            </Button>
          </div>

          <p className="text-xs text-muted-foreground">
            Baris terisi otomatis dari baris order (qty × harga + pajak) saat order dipilih —
            bisa diubah sebelum CONFIRMED. Harga wajib &gt; 0 saat konfirmasi (guard §5).
          </p>


          {values.lines.map((line, index) => {
            const lineError = showErrors ? errors.lines?.[index] : undefined;

            return (
              <div
                key={`${String(line.id ?? 'baru')}-${String(index)}`}
                className="grid grid-cols-1 items-end gap-3 border-t border-border pt-3 md:grid-cols-12"
              >
                <div className="md:col-span-4">
                  <Select
                    label={`Produk ${String(index + 1)} *`}
                    options={productOptions}
                    value={line.product_id}
                    onChange={(event) =>
                      setDraft(updateInvoiceLine(values, index, { product_id: event.target.value }))
                    }
                    {...(lineError?.product_id !== undefined
                      ? { error: lineError.product_id }
                      : {})}
                  />
                </div>
                <div className="md:col-span-1">
                  <Input
                    label="Qty *"
                    type="number"
                    min="0"
                    step="0.01"
                    value={line.qty}
                    onChange={(event) =>
                      setDraft(updateInvoiceLine(values, index, { qty: event.target.value }))
                    }
                    {...(lineError?.qty !== undefined ? { error: lineError.qty } : {})}
                  />
                </div>
                <div className="md:col-span-2">
                  <Input
                    label="Harga *"
                    type="number"
                    min="0"
                    step="0.01"
                    value={line.price_unit}
                    onChange={(event) =>
                      setDraft(updateInvoiceLine(values, index, { price_unit: event.target.value }))
                    }
                    {...(lineError?.price_unit !== undefined
                      ? { error: lineError.price_unit }
                      : {})}
                  />
                </div>
                <div className="md:col-span-2">
                  <Select
                    label={`Pajak ${String(index + 1)}`}
                    options={taxOptions}
                    value={line.tax_ids[0] === undefined ? '' : String(line.tax_ids[0])}
                    onChange={(event) => {
                      const next = event.target.value;
                      setDraft(
                        updateInvoiceLine(values, index, {
                          tax_ids: next === '' ? [] : [Number(next)],
                        }),
                      );
                    }}
                  />
                </div>
                <div className="md:col-span-2">
                  <p className="text-xs text-muted-foreground">Subtotal</p>
                  <p className="font-mono text-sm tabular-nums">
                    {lineSubtotal(line.qty, line.price_unit)}
                  </p>
                </div>
                <div className="md:col-span-1">
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    icon={Trash2}
                    aria-label={`Hapus baris ${String(index + 1)}`}
                    onClick={() => setDraft(removeInvoiceLine(values, index))}
                  >
                    Hapus
                  </Button>
                </div>
              </div>
            );
          })}
        </section>

        <section className={cn(CARD, 'flex flex-wrap items-center justify-between gap-3')}>
          <div className="flex flex-col gap-1">
            <p className="text-sm font-semibold text-foreground">
              Total: <span className="font-mono tabular-nums">{total.toFixed(2)}</span>
            </p>
            <p className="text-xs text-muted-foreground">
              Invoice lahir DRAFT (MES-only). Push ke Odoo (draft, harga &amp; pajak nyata)
              terjadi saat CONFIRMED di halaman detail.
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <Button type="submit" icon={Save} loading={save.isPending}>
              {isEdit ? 'Simpan Perubahan' : 'Simpan Invoice'}
            </Button>
            <Button
              type="button"
              variant="secondary"
              onClick={() => navigate('/finance/customer-invoices')}
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

