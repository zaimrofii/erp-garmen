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
import { createVendorBill, fetchVendorBill, updateVendorBill } from '@/api/vendorBills';
import { fetchProducts, PRODUCTS_LIMIT_MAX } from '@/api/masterProducts';
import { fetchPartners, PARTNERS_LIMIT_MAX } from '@/api/masterPartners';
import { fetchTaxes, TAXES_LIMIT_MAX } from '@/api/masterTaxes';
import {
  fetchPurchaseOrderMes,
  fetchPurchaseOrdersMes,
  PURCHASE_ORDERS_MES_LIMIT_MAX,
} from '@/api/purchaseOrdersCrud';
import { useFeedback } from '@/app/app-runtime';
import { useApiClient } from '@/hooks/useApiClient';
import { cn } from '@/lib/cn';
import {
  addBillLine,
  billFormFromDetail,
  billFormFromPurchaseOrderDetail,
  billFormTotal,
  billInputFromForm,
  EMPTY_BILL_FORM,
  isBillFormValid,
  lineSubtotal,
  NO_PO_OPTION,
  NO_TAX_OPTION,
  NO_VENDOR_OPTION,
  removeBillLine,
  updateBillLine,
  validateBillForm,
  type BillFormValues,
} from '@/lib/vendor-bill';
import { taxOptionLabel } from '@/lib/master-tax';
import { CARD } from '@/lib/tokens';

/**
 * VendorBillFormPage - route `/finance/vendor-bills/new` + `…/:id/edit` (H3.2).
 *
 * Header (PO, vendor, ref vendor, tanggal bill, jatuh tempo, catatan) + **editor baris
 * INLINE** (produk, qty, harga, pajak, subtotal):
 *
 *   * **auto-fill dari PO Line** (H2.2): memilih PO — atau membuka
 *     `/finance/vendor-bills/new?po=<id>` dari tombol "Buat Bill" di detail PO —
 *     mengisi baris qty × harga + pajak dan vendor secara otomatis (tetap editable);
 *   * `lines` selalu dikirim → backend memakai baris apa adanya (tanpa auto-fill ganda);
 *   * bill **tanpa PO** diizinkan (mis. biaya jasa): pilih "Tanpa PO" lalu isi baris manual;
 *   * `ref` = nomor bill dari vendor, **best-effort** (boleh kosong/duplikat);
 *   * create → `POST /api/v1/finance/vendor-bills/`; edit → `PUT …/<id>/`
 *     (DRAFT-only; backend menolak 400 setelah CONFIRMED);
 *   * sukses create → Toast (termasuk `duplicate_warning` = PO sudah punya bill aktif
 *     → termin/partial, **bukan** error) → pindah ke detail;
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

export function VendorBillFormPage() {
  const { id } = useParams<{ id: string }>();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const client = useApiClient();
  const { trigger } = useFeedback();

  const parsedId = id === undefined ? null : Number(id);
  const billId = parsedId !== null && Number.isFinite(parsedId) ? parsedId : null;
  const isEdit = billId !== null;

  const seededPo = params.get('po') ?? '';
  const [draft, setDraft] = useState<BillFormValues | null>(null);
  const [submitted, setSubmitted] = useState(false);
  const [toast, setToast] = useState<ToastState | null>(null);

  const detail = useQuery({
    queryKey: ['vendor-bill', billId],
    queryFn: () => fetchVendorBill(client, billId ?? 0),
    enabled: isEdit,
    staleTime: 15_000,
  });

  const orders = useQuery({
    queryKey: ['vendor-bill-po-options'],
    queryFn: () => fetchPurchaseOrdersMes(client, { limit: PURCHASE_ORDERS_MES_LIMIT_MAX }),
    staleTime: 60_000,
  });

  const partners = useQuery({
    queryKey: ['vendor-bill-vendor-options'],
    queryFn: () => fetchPartners(client, { limit: PARTNERS_LIMIT_MAX }),
    staleTime: 60_000,
  });

  const products = useQuery({
    queryKey: ['vendor-bill-product-options'],
    queryFn: () => fetchProducts(client, { limit: PRODUCTS_LIMIT_MAX }),
    staleTime: 60_000,
  });

  const taxes = useQuery({
    queryKey: ['vendor-bill-tax-options'],
    queryFn: () => fetchTaxes(client, { limit: TAXES_LIMIT_MAX }),
    staleTime: 60_000,
  });

  const values = useMemo<BillFormValues | null>(() => {
    if (draft !== null) return draft;
    if (isEdit) {
      return detail.data === undefined ? null : billFormFromDetail(detail.data);
    }

    return { ...EMPTY_BILL_FORM, purchase_order_id: seededPo, invoice_date: todayIso() };
  }, [draft, detail.data, isEdit, seededPo]);

  const current = values ?? EMPTY_BILL_FORM;
  const errors = useMemo(() => validateBillForm(current), [current]);
  const valid = values !== null && isBillFormValid(errors);
  const total = billFormTotal(current);

  const poOptions = useMemo<{ value: string; label: string }[]>(() => {
    const rows = orders.data?.rows ?? [];

    return [
      NO_PO_OPTION,
      ...rows.map((row) => ({
        value: String(row.id),
        label: `${row.code} — ${row.vendor_name ?? '-'}`,
      })),
    ];
  }, [orders.data]);

  const vendorOptions = useMemo<{ value: string; label: string }[]>(() => {
    const rows = partners.data?.rows ?? [];

    return [
      NO_VENDOR_OPTION,
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

  /** Ganti PO → ambil barisnya (auto-fill); vendor mengikuti PO tersebut. */
  async function handlePurchaseOrderChange(next: string): Promise<void> {
    const base = { ...current, purchase_order_id: next };
    setDraft(base);
    if (next === '') return;

    try {
      const poDetail = await fetchPurchaseOrderMes(client, Number(next));
      setDraft((existing) => {
        const origin = existing ?? base;
        const filled = billFormFromPurchaseOrderDetail(poDetail);

        return {
          ...origin,
          purchase_order_id: next,
          vendor_id: filled.vendor_id,
          lines: filled.lines,
        };
      });
    } catch {
      // PO gagal dimuat → biarkan form apa adanya (baris bisa diisi manual).
    }
  }

  function setField<K extends keyof BillFormValues>(field: K, value: BillFormValues[K]): void {
    setDraft({ ...current, [field]: value });
  }

  const save = useMutation({
    mutationFn: async () => {
      const input = billInputFromForm(current);

      return isEdit ? updateVendorBill(client, billId ?? 0, input) : createVendorBill(client, input);
    },
    onSuccess: (saved) => {
      trigger('success');
      setToast({
        tone: 'success',
        title: isEdit ? 'Vendor bill diperbarui' : 'Vendor bill dibuat',
        description:
          `${saved.code} — ${String(saved.lines_count)} baris, total ${saved.amount_total}.` +
          (saved.duplicate_warning ? ` ${saved.duplicate_warning}` : ''),
      });
      navigate(`/finance/vendor-bills/${String(saved.id)}`);
    },
    onError: (caught) => {
      trigger('error');
      setToast({
        tone: 'error',
        title: 'Gagal menyimpan vendor bill',
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
        title={isEdit ? 'Edit Vendor Bill' : 'Vendor Bill Baru'}
        subtitle="Tagihan vendor MES — draft in_invoice dikirim ke Odoo saat CONFIRMED"
        breadcrumb={[
          { label: 'Finance', href: '/finance/vendor-bills' },
          { label: isEdit ? 'Edit' : 'Baru' },
        ]}
        actions={
          <Button
            variant="ghost"
            icon={ArrowLeft}
            onClick={() => navigate('/finance/vendor-bills')}
          >
            Kembali
          </Button>
        }
      />

      {isEdit && detail.isLoading ? (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Spinner size="sm" /> Memuat vendor bill…
        </div>
      ) : null}

      {isEdit && detail.error !== null ? (
        <section className={cn(CARD, 'flex flex-col gap-2')}>
          <p role="alert" className="text-sm font-medium text-accent-coral">
            Gagal memuat vendor bill (perlu login atau bill tidak ada).
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
            label="Purchase Order"
            options={poOptions}
            value={current.purchase_order_id}
            onChange={(event) => {
              void handlePurchaseOrderChange(event.target.value);
            }}
          />
          <Select
            label="Vendor *"
            options={vendorOptions}
            value={current.vendor_id}
            onChange={(event) => setField('vendor_id', event.target.value)}
            {...(showErrors && errors.vendor_id !== undefined ? { error: errors.vendor_id } : {})}
          />
          <Input
            label="No. bill vendor (ref)"
            value={current.ref}
            placeholder="mis. INV-VENDOR-001 (boleh kosong)"
            onChange={(event) => setField('ref', event.target.value)}
            {...(showErrors && errors.ref !== undefined ? { error: errors.ref } : {})}
          />
          <Input
            label="Tanggal bill *"
            type="date"
            value={current.invoice_date}
            onChange={(event) => setField('invoice_date', event.target.value)}
            {...(showErrors && errors.invoice_date !== undefined
              ? { error: errors.invoice_date }
              : {})}
          />
          <Input
            label="Jatuh tempo"
            type="date"
            value={current.due_date}
            onChange={(event) => setField('due_date', event.target.value)}
          />
          <Input
            label="Catatan"
            value={current.notes}
            placeholder="mis. termin 1 dari 3"
            onChange={(event) => setField('notes', event.target.value)}
          />
        </section>

        <section className={cn(CARD, 'flex flex-col gap-3')}>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-sm font-semibold text-foreground">
              Baris Bill ({String(current.lines.length)} baris)
            </h2>
            <Button
              type="button"
              variant="secondary"
              size="sm"
              icon={Plus}
              onClick={() => setDraft(addBillLine(current))}
            >
              Tambah Baris
            </Button>
          </div>

          {current.lines.map((line, index) => {
            const lineError = errors.lines?.[index];

            return (
              <div
                key={line.id ?? `baru-${String(index)}`}
                className="grid grid-cols-1 items-end gap-3 border-t border-border pt-3 md:grid-cols-12"
              >
                <div className="md:col-span-3">
                  <Select
                    label={`Produk ${String(index + 1)} *`}
                    options={productOptions}
                    value={line.product_id}
                    onChange={(event) =>
                      setDraft(updateBillLine(current, index, { product_id: event.target.value }))
                    }
                    {...(lineError?.product_id !== undefined
                      ? { error: lineError.product_id }
                      : {})}
                  />
                </div>
                <div className="md:col-span-2">
                  <Input
                    label="Qty *"
                    type="number"
                    min="0"
                    step="0.01"
                    value={line.qty}
                    onChange={(event) =>
                      setDraft(updateBillLine(current, index, { qty: event.target.value }))
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
                      setDraft(updateBillLine(current, index, { price_unit: event.target.value }))
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
                        updateBillLine(current, index, {
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
                    onClick={() => setDraft(removeBillLine(current, index))}
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
              Bill lahir DRAFT (MES-only). Push ke Odoo (draft `in_invoice`) terjadi saat
              CONFIRMED di halaman detail.
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <Button type="submit" icon={Save} loading={save.isPending}>
              {isEdit ? 'Simpan Perubahan' : 'Simpan Bill'}
            </Button>
            <Button
              type="button"
              variant="secondary"
              onClick={() => navigate('/finance/vendor-bills')}
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



