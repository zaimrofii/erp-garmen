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
import { createPurchaseOrderMes, fetchPurchaseOrderMes, updatePurchaseOrderMes } from '@/api/purchaseOrdersCrud';
import { useFeedback } from '@/app/app-runtime';
import { useApiClient } from '@/hooks/useApiClient';
import { cn } from '@/lib/cn';
import {
  addPoLine,
  EMPTY_PO_FORM,
  isPoEditable,
  isPoFormValid,
  poFormFromDetail,
  poFormTotal,
  poInputFromForm,
  poLineSubtotal,
  poOptionLabel,
  removePoLine,
  updatePoLine,
  validatePoForm,
  type PoFormValues,
} from '@/lib/purchase-order';
import { taxOptionLabel } from '@/lib/master-tax';
import { CARD } from '@/lib/tokens';

/**
 * PurchaseOrderFormPage - route `/purchase/orders/new` + `/purchase/orders/:id/edit` (H2.2).
 *
 * Header (vendor, tanggal diharapkan, catatan) + **editor baris INLINE**
 * (produk, qty Desimal, harga satuan, tanggal rencana, pajak, subtotal):
 *
 *   * simpan SEKALI → `createPurchaseOrderMes`/`updatePurchaseOrderMes` mengirim
 *     `lines[]`; backend menulis header + baris dalam satu transaksi (pola H1.5/H2.1);
 *   * nomor PO TIDAK diisi di form: backend membangkitkan `PO-<TAHUN>-<SEQ>` (Sprint C
 *     `next_number('PO')`) dan menyimpannya juga sebagai `partner_ref` (nomor yang
 *     dikirim ke Odoo saat CONFIRMED);
 *   * **pemilih pajak per baris (H3.6)**: dropdown dari
 *     `GET /master/taxes/?type_tax_use=purchase&active=true` (`api/masterTaxes.ts`) —
 *     satu pajak pembelian per baris (payload `tax_ids: [id]`); kosong = tanpa pajak;
 *   * edit hanya untuk `DRAFT`; izin tulis PURCHASING/ADMIN/OWNER (backend).
 */

interface ToastState {
  tone: ToastTone;
  title: string;
  description: string;
}

/** Opsi "kosong" untuk `<select>` (mengirim `null` ke backend). */
const NO_VENDOR_OPTION = { value: '', label: '— Pilih vendor —' };
const NO_PRODUCT_OPTION = { value: '', label: '— Pilih produk —' };
//: H3.6 — baris tanpa pajak (`tax_ids: []`).
const NO_TAX_OPTION = { value: '', label: '— Tanpa pajak —' };

export function PurchaseOrderFormPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const client = useApiClient();
  const { trigger } = useFeedback();

  const parsedId = id === undefined ? null : Number(id);
  const poId = parsedId !== null && Number.isFinite(parsedId) ? parsedId : null;
  const isEdit = poId !== null;

  const [draft, setDraft] = useState<PoFormValues | null>(null);
  const [submitted, setSubmitted] = useState(false);
  const [toast, setToast] = useState<ToastState | null>(null);

  const detail = useQuery({
    queryKey: ['purchase-order-mes', poId],
    queryFn: () => fetchPurchaseOrderMes(client, poId ?? 0),
    enabled: isEdit,
    staleTime: 15_000,
  });

  /** Master partner (dropdown vendor) — `master.Partner` (H1.6). */
  const partners = useQuery({
    queryKey: ['master-partners', 'po-options'],
    queryFn: () => fetchPartners(client, { limit: PARTNERS_LIMIT_MAX }),
    staleTime: 60_000,
  });

  /** Master produk (dropdown baris) — `master.Product` (H1.1). */
  const products = useQuery({
    queryKey: ['master-products', 'po-options'],
    queryFn: () => fetchProducts(client, { limit: PRODUCTS_LIMIT_MAX, active: true }),
    staleTime: 60_000,
  });

  /**
   * Master pajak pembelian (dropdown pajak per baris, H3.6) — `master.Tax`.
   *
   * `PurchaseOrderLine.tax_ids` (H2.2) sudah M2M ke `master.Tax`; H3.6 menambah
   * endpoint daftar pajak sehingga form AKHIRNYA bisa memilih (tanpa mengarang).
   */
  const taxes = useQuery({
    queryKey: ['master-taxes', 'po-options'],
    queryFn: () =>
      fetchTaxes(client, { type_tax_use: 'purchase', active: true, limit: TAXES_LIMIT_MAX }),
    staleTime: 60_000,
  });

  /** Nilai form = draft pengguna → data GET (mode edit) → form kosong. */
  const values: PoFormValues =
    draft ?? (detail.data === undefined ? EMPTY_PO_FORM : poFormFromDetail(detail.data));

  const errors = useMemo(() => validatePoForm(values), [values]);
  const valid = isPoFormValid(errors);
  const total = poFormTotal(values);

  const vendorOptions = useMemo<{ value: string; label: string }[]>(() => {
    const rows = partners.data?.rows ?? [];

    return [NO_VENDOR_OPTION, ...rows.map((row) => ({ value: String(row.id), label: poOptionLabel(row) }))];
  }, [partners.data]);

  const productOptions = useMemo<{ value: string; label: string }[]>(() => {
    const rows = products.data?.rows ?? [];

    return [NO_PRODUCT_OPTION, ...rows.map((row) => ({ value: String(row.id), label: poOptionLabel(row) }))];
  }, [products.data]);

  /** Opsi pajak baris: `''` = tanpa pajak, selain itu id `master.Tax` (single). */
  const taxOptions = useMemo<{ value: string; label: string }[]>(() => {
    const rows = taxes.data?.rows ?? [];

    return [NO_TAX_OPTION, ...rows.map((row) => ({ value: String(row.id), label: taxOptionLabel(row) }))];
  }, [taxes.data]);

  const save = useMutation({
    mutationFn: async () => {
      const input = poInputFromForm(values);

      return isEdit ? updatePurchaseOrderMes(client, poId, input) : createPurchaseOrderMes(client, input);
    },
    onSuccess: (saved) => {
      trigger('success');
      setToast({
        tone: 'success',
        title: isEdit ? 'PO diperbarui' : 'PO dibuat',
        description: `${saved.code} — ${String(saved.lines.length)} baris, total ${saved.amount_total}.`,
      });
      navigate(`/purchase/orders/${String(saved.id)}`);
    },
    onError: (caught) => {
      trigger('error');
      setToast({
        tone: 'error',
        title: 'Gagal menyimpan PO',
        description: caught instanceof Error ? caught.message : 'Permintaan simpan gagal.',
      });
    },
  });

  const formLocked = isEdit && detail.data !== undefined && !isPoEditable(detail.data.state);
  const showErrors = submitted;

  function setField<K extends keyof PoFormValues>(field: K, value: PoFormValues[K]): void {
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
        title={isEdit ? 'Edit PO' : 'PO Baru'}
        subtitle="Purchase Order MES — nomor otomatis PO-<TAHUN>-<SEQ>, dikirim ke Odoo saat dikonfirmasi"
        breadcrumb={[
          { label: 'Purchase', href: '/purchase/orders' },
          { label: 'Orders', href: '/purchase/orders' },
          { label: isEdit ? 'Edit' : 'Baru' },
        ]}
        actions={
          <Button variant="ghost" icon={ArrowLeft} onClick={() => navigate('/purchase/orders')}>
            Kembali
          </Button>
        }
      />

      {isEdit && detail.isLoading ? (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Spinner size="sm" /> Memuat PO…
        </div>
      ) : null}

      {isEdit && detail.error !== null ? (
        <section className={cn(CARD, 'flex flex-col gap-2')}>
          <p role="alert" className="text-sm font-medium text-accent-coral">
            Gagal memuat PO (perlu login atau PO tidak ada).
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
            PO berstate {detail.data?.state} tidak dapat diubah; hanya DRAFT yang boleh diedit.
          </p>
        </section>
      ) : null}

      <form className="flex flex-col gap-4" onSubmit={handleSubmit}>
        <section className={cn(CARD, 'grid grid-cols-1 gap-4 md:grid-cols-2')}>
          <Select
            label="Vendor *"
            options={vendorOptions}
            value={values.vendor_id}
            onChange={(event) => setField('vendor_id', event.target.value)}
            {...(showErrors && errors.vendor_id !== undefined ? { error: errors.vendor_id } : {})}
          />
          <Input
            label="Tanggal Diharapkan"
            type="date"
            value={values.expected_date}
            onChange={(event) => setField('expected_date', event.target.value)}
            {...(showErrors && errors.expected_date !== undefined
              ? { error: errors.expected_date }
              : {})}
          />
          <Input
            label="Catatan"
            value={values.notes}
            placeholder="catatan internal MES"
            onChange={(event) => setField('notes', event.target.value)}
          />
        </section>

        <section className={cn(CARD, 'flex flex-col gap-3')}>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-sm font-semibold text-foreground">
              Baris PO ({String(values.lines.length)} baris)
            </h2>
            <Button
              type="button"
              variant="secondary"
              size="sm"
              icon={Plus}
              onClick={() => setDraft(addPoLine(values))}
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
                      setDraft(updatePoLine(values, index, { product_id: event.target.value }))
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
                      setDraft(updatePoLine(values, index, { qty: event.target.value }))
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
                      setDraft(updatePoLine(values, index, { price_unit: event.target.value }))
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
                        updatePoLine(values, index, {
                          tax_ids: next === '' ? [] : [Number(next)],
                        }),
                      );
                    }}
                  />
                </div>
                <div className="md:col-span-2">
                  <Input
                    label="Rencana"
                    type="date"
                    value={line.date_planned}
                    onChange={(event) =>
                      setDraft(updatePoLine(values, index, { date_planned: event.target.value }))
                    }
                    {...(lineError?.date_planned !== undefined
                      ? { error: lineError.date_planned }
                      : {})}
                  />
                </div>
                <div className="md:col-span-1">
                  <p className="text-xs text-muted-foreground">Subtotal</p>
                  <p className="font-mono text-sm tabular-nums">
                    {poLineSubtotal(line.qty, line.price_unit).toFixed(2)}
                  </p>
                </div>
                <div className="md:col-span-1">
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    icon={Trash2}
                    aria-label={`Hapus baris ${String(index + 1)}`}
                    onClick={() => setDraft(removePoLine(values, index))}
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
              PO lahir DRAFT (MES-only). Push ke Odoo terjadi saat state → CONFIRMED (halaman
              detail); vendor wajib sudah punya Odoo ID &amp; setiap baris berharga &gt; 0.
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <Button type="submit" icon={Save} loading={save.isPending} disabled={formLocked}>
              {isEdit ? 'Simpan Perubahan' : 'Simpan PO'}
            </Button>
            <Button type="button" variant="secondary" onClick={() => navigate('/purchase/orders')}>
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


