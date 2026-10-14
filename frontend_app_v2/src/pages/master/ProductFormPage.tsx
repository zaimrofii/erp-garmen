import { useMemo, useState, type FormEvent } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useMutation, useQuery } from '@tanstack/react-query';
import { ArrowLeft, Save } from 'lucide-react';
import { Button } from '@/components/atoms/Button';
import { Checkbox } from '@/components/atoms/Checkbox';
import { Input } from '@/components/atoms/Input';
import { Select, type SelectOption } from '@/components/atoms/Select';
import { Spinner } from '@/components/atoms/Spinner';
import { Toast, type ToastTone } from '@/components/atoms/Toast';
import { PageHeader } from '@/components/molecules/PageHeader';
import { createProduct, fetchProduct, updateProduct } from '@/api/masterProducts';
import { fetchUoms, UOMS_LIMIT_MAX } from '@/api/masterUoms';
import { useFeedback } from '@/app/app-runtime';
import { useApiClient } from '@/hooks/useApiClient';
import { cn } from '@/lib/cn';
import { uomOptionLabel } from '@/lib/master-uom';
import {
  EMPTY_PRODUCT_FORM,
  isProductFormValid,
  productFormFromRow,
  productInputFromForm,
  validateProductForm,
  type ProductFormValues,
} from '@/lib/master-product';
import { CARD } from '@/lib/tokens';
import type { MasterUomRow } from '@/types/master-uom';

/**
 * ProductFormPage - route `/master/products/new` + `/master/products/:id` (H1.1).
 *
 * MES = source of truth master: form ini SUDAH cukup untuk membuat/mengubah produk
 * tanpa membuka Odoo (klien lama tetap bisa menarik data Odoo lewat sync master).
 *
 *   * create → `POST /api/v1/master/products/` (`createProduct`, backend 201 + `task_id`);
 *   * edit   → `PUT /api/v1/master/products/<id>/` (`updateProduct`; hanya field yang
 *     dikirim yang berubah, jadi prefilling dari detail aman);
 *   * validasi `lib/master-product.ts::validateProductForm` (PURE) — pesan error baru
 *     muncul setelah submit pertama (`submitted`); tombol TIDAK dimatikan supaya
 *     pengguna tahu penyebabnya;
 *   * **UoM**: dropdown dari master UoM (`fetchUoms({active:true, limit:200})`,
 *     H1.2) — backend menolak `uom_id` yang tidak ada; opsi kosong = tanpa UoM;
 *   * sukses → Toast + pindah ke halaman detail (menampilkan `odoo_id` hasil sync);
 *     push ke Odoo asinkron (Celery) jadi form tidak menunggu ERP.
 */

interface ToastState {
  tone: ToastTone;
  title: string;
  description: string;
}

/** Referensi stabil untuk "belum ada UoM" supaya `useMemo` validasi tidak dihitung ulang. */
const EMPTY_UOM_OPTIONS: MasterUomRow[] = [];

export function ProductFormPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const client = useApiClient();
  const { trigger } = useFeedback();

  const parsedId = id === undefined ? null : Number(id);
  const productId = parsedId !== null && Number.isFinite(parsedId) ? parsedId : null;
  const isEdit = productId !== null;

  const [draft, setDraft] = useState<ProductFormValues | null>(null);
  const [submitted, setSubmitted] = useState(false);
  const [toast, setToast] = useState<ToastState | null>(null);

  const detail = useQuery({
    queryKey: ['master-product', productId],
    queryFn: () => fetchProduct(client, productId ?? 0),
    enabled: isEdit,
    staleTime: 15_000,
  });

  /**
   * H1.2 (bonus tutup backlog H1.1) — daftar UoM aktif untuk dropdown.
   * Daftar ini juga dipakai validasi (id di luar daftar = pilihan kadaluarsa).
   */
  const uoms = useQuery({
    queryKey: ['master-uom-options'],
    queryFn: () => fetchUoms(client, { active: true, limit: UOMS_LIMIT_MAX }),
    staleTime: 60_000,
  });

  const uomRows = uoms.data?.rows ?? EMPTY_UOM_OPTIONS;
  const uomOptions: SelectOption[] = [
    { value: '', label: '— tanpa UoM —' },
    ...uomRows.map((row) => ({ value: String(row.id), label: uomOptionLabel(row) })),
  ];
  const hasUomOptions = uomRows.length > 0;

  /**
   * Nilai form = draft pengguna, atau data hasil GET (mode edit), atau form kosong.
   * Diderivasi saat render — TANPA `useEffect` penyinkron state (pola yang diminta
   * lint `react(set-state-in-effect)`; dulu prefill lewat effect).
   */
  const values: ProductFormValues =
    draft ?? (detail.data === undefined ? EMPTY_PRODUCT_FORM : productFormFromRow(detail.data));

  const errors = useMemo(
    () =>
      validateProductForm(
        values,
        hasUomOptions ? { uomIds: uomRows.map((row) => row.id) } : undefined,
      ),
    [values, hasUomOptions, uomRows],
  );
  const valid = isProductFormValid(errors);

  const save = useMutation({
    mutationFn: async () => {
      const input = productInputFromForm(values);

      return isEdit ? updateProduct(client, productId, input) : createProduct(client, input);
    },
    onSuccess: (saved) => {
      trigger('success');
      setToast({
        tone: 'success',
        title: isEdit ? 'Produk diperbarui' : 'Produk dibuat',
        description: `${saved.code} — push Odoo ${
          saved.queued ? 'diantrekan' : 'belum masuk broker'
        } (Odoo ID: ${saved.odoo_id === null ? '-' : String(saved.odoo_id)}).`,
      });
      navigate(`/master/products/${String(saved.id)}`);
    },
    onError: (caught) => {
      trigger('error');
      setToast({
        tone: 'error',
        title: 'Gagal menyimpan produk',
        description: caught instanceof Error ? caught.message : 'Permintaan simpan gagal.',
      });
    },
  });

  function setField<K extends keyof ProductFormValues>(
    field: K,
    value: ProductFormValues[K],
  ): void {
    setDraft({ ...values, [field]: value });
  }

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
        title={isEdit ? 'Edit Produk' : 'Produk Baru'}
        subtitle="Master produk MES — disimpan di MES lalu di-push ke Odoo (asinkron)"
        breadcrumb={[
          { label: 'Inventory', href: '/inventory/products' },
          { label: 'Master Products', href: '/master/products' },
          { label: isEdit ? 'Edit' : 'Baru' },
        ]}
        actions={
          <Button variant="ghost" icon={ArrowLeft} onClick={() => navigate('/master/products')}>
            Kembali
          </Button>
        }
      />

      {isEdit && detail.isLoading ? (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Spinner size="sm" /> Memuat produk…
        </div>
      ) : null}

      {isEdit && detail.error !== null ? (
        <section className={cn(CARD, 'flex flex-col gap-2')}>
          <p role="alert" className="text-sm font-medium text-accent-coral">
            Gagal memuat produk (perlu login atau produk tidak ada).
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
          <Input
            label="Kode *"
            value={values.code}
            placeholder="mis. TS-001"
            onChange={(event) => setField('code', event.target.value)}
            {...(showErrors && errors.code !== undefined ? { error: errors.code } : {})}
          />
          <Input
            label="Nama *"
            value={values.name}
            placeholder="mis. Kaos Polos"
            onChange={(event) => setField('name', event.target.value)}
            {...(showErrors && errors.name !== undefined ? { error: errors.name } : {})}
          />
          <Input
            label="Kategori"
            value={values.category}
            placeholder="mis. Atasan"
            onChange={(event) => setField('category', event.target.value)}
          />
          <Select
            label="UoM"
            options={uomOptions}
            value={values.uom}
            disabled={uoms.isLoading}
            onChange={(event) => setField('uom', event.target.value)}
            {...(showErrors && errors.uom !== undefined ? { error: errors.uom } : {})}
          />
          <Input
            label="Harga Jual"
            type="number"
            min={0}
            step="0.01"
            value={values.sale_price}
            onChange={(event) => setField('sale_price', event.target.value)}
            {...(showErrors && errors.sale_price !== undefined
              ? { error: errors.sale_price }
              : {})}
          />
          <Input
            label="Harga Pokok (HPP)"
            type="number"
            min={0}
            step="0.01"
            value={values.cost_price}
            onChange={(event) => setField('cost_price', event.target.value)}
            {...(showErrors && errors.cost_price !== undefined
              ? { error: errors.cost_price }
              : {})}
          />
          <Input
            label="Berat (kg)"
            type="number"
            min={0}
            step="0.01"
            value={values.weight}
            placeholder="opsional"
            onChange={(event) => setField('weight', event.target.value)}
            {...(showErrors && errors.weight !== undefined ? { error: errors.weight } : {})}
          />
          <Input
            label="URL Gambar"
            value={values.image_url}
            placeholder="https://…"
            onChange={(event) => setField('image_url', event.target.value)}
            {...(showErrors && errors.image_url !== undefined ? { error: errors.image_url } : {})}
          />
        </section>

        <section className={cn(CARD, 'flex flex-wrap items-center justify-between gap-3')}>
          <Checkbox
            label="Produk aktif (bisa dipakai order & BOM)"
            checked={values.active}
            onCheckedChange={(checked) => setField('active', checked)}
          />

          <div className="flex flex-wrap items-center gap-2">
            <Button type="submit" icon={Save} loading={save.isPending}>
              {isEdit ? 'Simpan Perubahan' : 'Simpan Produk'}
            </Button>
            <Button type="button" variant="secondary" onClick={() => navigate('/master/products')}>
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

