import { useMemo, useState, type FormEvent } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useMutation, useQuery } from '@tanstack/react-query';
import { ArrowLeft, Plus, Save, Trash2 } from 'lucide-react';
import { Button } from '@/components/atoms/Button';
import { Input } from '@/components/atoms/Input';
import { Select } from '@/components/atoms/Select';
import { Spinner } from '@/components/atoms/Spinner';
import { Toast, type ToastTone } from '@/components/atoms/Toast';
import { PageHeader } from '@/components/molecules/PageHeader';
import { fetchPartners, PARTNERS_LIMIT_MAX } from '@/api/masterPartners';
import { fetchProducts, PRODUCTS_LIMIT_MAX } from '@/api/masterProducts';
import { fetchTaxes, TAXES_LIMIT_MAX } from '@/api/masterTaxes';
import { createOrder, fetchOrder, updateOrder } from '@/api/salesOrders';
import { useFeedback } from '@/app/app-runtime';
import { useApiClient } from '@/hooks/useApiClient';
import { cn } from '@/lib/cn';
import {
  addOrderLine,
  EMPTY_ORDER_FORM,
  isOrderEditable,
  isOrderFormValid,
  lineSubtotal,
  orderFormFromDetail,
  orderFormTotal,
  orderInputFromForm,
  orderOptionLabel,
  ORDER_TYPE_OPTIONS,
  removeOrderLine,
  updateOrderLine,
  validateOrderForm,
  type OrderFormValues,
} from '@/lib/sales-order';
import { taxOptionLabel } from '@/lib/master-tax';
import { CARD } from '@/lib/tokens';

/**
 * OrderFormPage - route `/sales/orders/new` + `/sales/orders/:id/edit` (H2.1).
 *
 * Header (customer, tipe order, prioritas, deadline) + **editor baris INLINE**
 * (produk, qty, harga satuan, pajak, tag, subtotal):
 *
 *   * simpan SEKALI → `createOrder`/`updateOrder` mengirim `lines[]`; backend
 *     menulis header + baris dalam satu transaksi (pola BOMLine H1.5);
 *   * nomor order TIDAK diisi di form: backend membangkitkan `SO-<TAHUN>-<SEQ>`
 *     (Sprint C `next_number('SO')`) dan menyimpannya juga sebagai
 *     `client_order_ref` (nomor yang dikirim ke Odoo saat CONFIRMED);
 *   * **pemilih pajak per baris (H3.6)**: dropdown diambil dari
 *     `GET /master/taxes/?type_tax_use=sale&active=true` (`api/masterTaxes.ts`) —
 *     satu pajak penjualan per baris (payload `tax_ids: [id]`); pilihan kosong =
 *     tanpa pajak. Sebelum H3.6 form sengaja tanpa pemilih karena endpoint daftar
 *     pajak belum ada;
 *   * edit hanya untuk `DRAFT` (backend menolak 400 setelah CONFIRMED);
 *   * izin tulis ADMIN/OWNER (backend `api/orders.py`).
 */

interface ToastState {
  tone: ToastTone;
  title: string;
  description: string;
}

/** Opsi "kosong" untuk `<select>` (mengirim `null` ke backend). */
const NO_CUSTOMER_OPTION = { value: '', label: '— Pilih customer —' };
const NO_PRODUCT_OPTION = { value: '', label: '— Pilih produk —' };
//: H3.6 — baris tanpa pajak (`tax_ids: []`).
const NO_TAX_OPTION = { value: '', label: '— Tanpa pajak —' };

export function OrderFormPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const client = useApiClient();
  const { trigger } = useFeedback();

  const parsedId = id === undefined ? null : Number(id);
  const orderId = parsedId !== null && Number.isFinite(parsedId) ? parsedId : null;
  const isEdit = orderId !== null;

  const [draft, setDraft] = useState<OrderFormValues | null>(null);
  const [submitted, setSubmitted] = useState(false);
  const [toast, setToast] = useState<ToastState | null>(null);

  const detail = useQuery({
    queryKey: ['sales-order', orderId],
    queryFn: () => fetchOrder(client, orderId ?? 0),
    enabled: isEdit,
    staleTime: 15_000,
  });

  /** Master customer (dropdown header) — `master.Partner` (H1.6). */
  const partners = useQuery({
    queryKey: ['master-partners', 'order-options'],
    queryFn: () => fetchPartners(client, { limit: PARTNERS_LIMIT_MAX }),
    staleTime: 60_000,
  });

  /** Master produk (dropdown baris) — `master.Product` (H1.1). */
  const products = useQuery({
    queryKey: ['master-products', 'order-options'],
    queryFn: () => fetchProducts(client, { limit: PRODUCTS_LIMIT_MAX, active: true }),
    staleTime: 60_000,
  });

  /**
   * Master pajak penjualan (dropdown pajak per baris, H3.6) — `master.Tax`.
   *
   * `OrderLine.tax_ids` (H2.1) sudah M2M ke `master.Tax`; H3.6 menambah endpoint
   * daftar pajak sehingga form AKHIRNYA bisa memilih (tanpa mengarang pilihan).
   */
  const taxes = useQuery({
    queryKey: ['master-taxes', 'order-options'],
    queryFn: () =>
      fetchTaxes(client, { type_tax_use: 'sale', active: true, limit: TAXES_LIMIT_MAX }),
    staleTime: 60_000,
  });

  /** Nilai form = draft pengguna → data GET (mode edit) → form kosong. */
  const values: OrderFormValues =
    draft ?? (detail.data === undefined ? EMPTY_ORDER_FORM : orderFormFromDetail(detail.data));

  const errors = useMemo(() => validateOrderForm(values), [values]);
  const valid = isOrderFormValid(errors);
  const total = orderFormTotal(values);

  const customerOptions = useMemo<{ value: string; label: string }[]>(() => {
    const rows = partners.data?.rows ?? [];

    return [
      NO_CUSTOMER_OPTION,
      ...rows.map((row) => ({ value: String(row.id), label: orderOptionLabel(row) })),
    ];
  }, [partners.data]);

  const productOptions = useMemo<{ value: string; label: string }[]>(() => {
    const rows = products.data?.rows ?? [];

    return [
      NO_PRODUCT_OPTION,
      ...rows.map((row) => ({ value: String(row.id), label: orderOptionLabel(row) })),
    ];
  }, [products.data]);

  /** Opsi pajak baris: `''` = tanpa pajak, selain itu id `master.Tax` (single). */
  const taxOptions = useMemo<{ value: string; label: string }[]>(() => {
    const rows = taxes.data?.rows ?? [];

    return [
      NO_TAX_OPTION,
      ...rows.map((row) => ({ value: String(row.id), label: taxOptionLabel(row) })),
    ];
  }, [taxes.data]);

  const save = useMutation({
    mutationFn: async () => {
      const input = orderInputFromForm(values);

      return isEdit ? updateOrder(client, orderId, input) : createOrder(client, input);
    },
    onSuccess: (saved) => {
      trigger('success');
      setToast({
        tone: 'success',
        title: isEdit ? 'Order diperbarui' : 'Order dibuat',
        description: `${saved.code} — ${String(saved.lines.length)} baris, total ${saved.amount_total}.`,
      });
      navigate(`/sales/orders/${String(saved.id)}`);
    },
    onError: (caught) => {
      trigger('error');
      setToast({
        tone: 'error',
        title: 'Gagal menyimpan order',
        description: caught instanceof Error ? caught.message : 'Permintaan simpan gagal.',
      });
    },
  });

  const formLocked = isEdit && detail.data !== undefined && !isOrderEditable(detail.data.state);
  const showErrors = submitted;

  function setField<K extends keyof OrderFormValues>(field: K, value: OrderFormValues[K]): void {
    setDraft({ ...values, [field]: value });
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    setSubmitted(true);

    if (!valid || save.isPending || formLocked) return;

    save.mutate();
  }

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <PageHeader
        title={isEdit ? 'Edit Order' : 'Order Baru'}
        subtitle="Sales Order MES — nomor otomatis SO-<TAHUN>-<SEQ>, dikirim ke Odoo saat dikonfirmasi"
        breadcrumb={[
          { label: 'Sales', href: '/sales/orders' },
          { label: 'Order', href: '/sales/orders' },
          { label: isEdit ? 'Edit' : 'Baru' },
        ]}
        actions={
          <Button variant="ghost" icon={ArrowLeft} onClick={() => navigate('/sales/orders')}>
            Kembali
          </Button>
        }
      />

      {isEdit && detail.isLoading ? (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Spinner size="sm" /> Memuat order…
        </div>
      ) : null}

      {isEdit && detail.error !== null ? (
        <section className={cn(CARD, 'flex flex-col gap-2')}>
          <p role="alert" className="text-sm font-medium text-accent-coral">
            Gagal memuat order (perlu login atau order tidak ada).
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

      {formLocked ? (
        <section className={cn(CARD, 'flex flex-col gap-2')}>
          <p role="alert" className="text-sm font-medium text-accent-amber">
            Order berstate {detail.data?.state} tidak dapat diubah; hanya DRAFT yang boleh diedit.
          </p>
        </section>
      ) : null}

      <form className="flex flex-col gap-4" onSubmit={handleSubmit}>
        <section className={cn(CARD, 'grid grid-cols-1 gap-4 md:grid-cols-2')}>
          <Select
            label="Customer *"
            options={customerOptions}
            value={values.customer_id}
            onChange={(event) => setField('customer_id', event.target.value)}
            {...(showErrors && errors.customer_id !== undefined ? { error: errors.customer_id } : {})}
          />
          <Select
            label="Tipe Order"
            options={ORDER_TYPE_OPTIONS.map((value) => ({ value, label: value }))}
            value={values.order_type}
            onChange={(event) => setField('order_type', event.target.value)}
          />
          <Input
            label="Prioritas"
            type="number"
            min="0"
            value={values.priority}
            onChange={(event) => setField('priority', event.target.value)}
            {...(showErrors && errors.priority !== undefined ? { error: errors.priority } : {})}
          />
          <Input
            label="Deadline"
            type="date"
            value={values.deadline}
            onChange={(event) => setField('deadline', event.target.value)}
            {...(showErrors && errors.deadline !== undefined ? { error: errors.deadline } : {})}
          />
        </section>

        <section className={cn(CARD, 'flex flex-col gap-3')}>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-sm font-semibold text-foreground">
              Baris Order ({String(values.lines.length)} baris)
            </h2>
            <Button
              type="button"
              variant="secondary"
              size="sm"
              icon={Plus}
              onClick={() => setDraft(addOrderLine(values))}
            >
              Tambah Baris
            </Button>
          </div>

          {values.lines.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              Belum ada baris. Tambahkan baris untuk memilih produk.
            </p>
          ) : null}

          {values.lines.map((line, index) => {
            const lineError = showErrors ? errors.lines?.[index] : undefined;

            return (
              <div
                key={`${String(line.id ?? 'baru')}-${String(index)}`}
                className="grid grid-cols-1 items-end gap-3 border-t border-border pt-3 md:grid-cols-12"
              >
                <div className="md:col-span-3">
                  <Select
                    label={`Produk ${String(index + 1)} *`}
                    options={productOptions}
                    value={line.product_id}
                    onChange={(event) =>
                      setDraft(updateOrderLine(values, index, { product_id: event.target.value }))
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
                    min="1"
                    step="1"
                    value={line.qty}
                    onChange={(event) =>
                      setDraft(updateOrderLine(values, index, { qty: event.target.value }))
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
                      setDraft(updateOrderLine(values, index, { price_unit: event.target.value }))
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
                        updateOrderLine(values, index, {
                          tax_ids: next === '' ? [] : [Number(next)],
                        }),
                      );
                    }}
                  />
                </div>
                <div className="md:col-span-2">
                  <Input
                    label="Tag"
                    value={line.tag}
                    placeholder="EXPORT / FAST_TRACK"
                    onChange={(event) =>
                      setDraft(updateOrderLine(values, index, { tag: event.target.value }))
                    }
                  />
                </div>
                <div className="md:col-span-1">
                  <p className="text-xs text-muted-foreground">Subtotal</p>
                  <p className="font-mono text-sm tabular-nums">
                    {(lineSubtotal(line.qty, line.price_unit)).toFixed(2)}
                  </p>
                </div>
                <div className="md:col-span-1">
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    icon={Trash2}
                    aria-label={`Hapus baris ${String(index + 1)}`}
                    onClick={() => setDraft(removeOrderLine(values, index))}
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
              Order lahir DRAFT (MES-only). Push ke Odoo terjadi saat state → CONFIRMED
              (halaman detail), dan setiap baris wajib berharga &gt; 0 sebelum dikonfirmasi.
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <Button type="submit" icon={Save} loading={save.isPending} disabled={formLocked}>
              {isEdit ? 'Simpan Perubahan' : 'Simpan Order'}
            </Button>
            <Button type="button" variant="secondary" onClick={() => navigate('/sales/orders')}>
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

