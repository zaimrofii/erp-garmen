import { useMemo, useState, type FormEvent } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useMutation, useQuery } from '@tanstack/react-query';
import { ArrowLeft, Plus, Save, Trash2 } from 'lucide-react';
import { Button } from '@/components/atoms/Button';
import { Checkbox } from '@/components/atoms/Checkbox';
import { Input } from '@/components/atoms/Input';
import { Select } from '@/components/atoms/Select';
import { Spinner } from '@/components/atoms/Spinner';
import { Toast, type ToastTone } from '@/components/atoms/Toast';
import { PageHeader } from '@/components/molecules/PageHeader';
import { createBom, fetchBom, updateBom } from '@/api/masterBoms';
import { fetchProducts, PRODUCTS_LIMIT_MAX } from '@/api/masterProducts';
import { fetchUoms, UOMS_LIMIT_MAX } from '@/api/masterUoms';
import { useFeedback } from '@/app/app-runtime';
import { useApiClient } from '@/hooks/useApiClient';
import { cn } from '@/lib/cn';
import {
  addBomLine,
  bomFormFromDetail,
  bomInputFromForm,
  EMPTY_BOM_FORM,
  isBomFormValid,
  productOptionLabel,
  removeBomLine,
  updateBomLine,
  validateBomForm,
  type BomFormValues,
} from '@/lib/master-bom';
import { CARD } from '@/lib/tokens';

/**
 * BomFormPage - route `/master/boms/new` + `/master/boms/:id/edit` (H1.5).
 *
 * Header (produk, output_qty, satuan, kode opsional, nama, catatan, aktif) +
 * **editor baris komponen INLINE**:
 *
 *   * tambah/hapus baris di layar, lalu simpan SEKALI → `createBom`/`updateBom`
 *     mengirim `lines[]`; backend menulis header + baris dalam satu transaksi
 *     (baris lama yang hilang di-*soft-delete*, bukan dihapus);
 *   * setiap baris: produk (dropdown master produk H1.1), qty, satuan (dropdown
 *     UoM H1.2; kosong = warisi satuan produk), sequence, catatan;
 *   * validasi PURE `lib/master-bom.ts`: produk wajib, output_qty/qty > 0, dan
 *     komponen tidak boleh produk BOM sendiri (siklus antar-BOM dijaga backend);
 *   * kode boleh dikosongkan → backend membangkitkan `BOM-<kode produk>`;
 *   * izin tulis dibatasi role ADMIN/OWNER di backend (403 kalau bukan).
 */

interface ToastState {
  tone: ToastTone;
  title: string;
  description: string;
}

/** Opsi "kosong" untuk `<select>` (mengirim `null` ke backend). */
const NO_PRODUCT_OPTION = { value: '', label: '— Pilih produk —' };
const NO_UOM_OPTION = { value: '', label: '— Warisi satuan produk —' };

export function BomFormPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const client = useApiClient();
  const { trigger } = useFeedback();

  const parsedId = id === undefined ? null : Number(id);
  const bomId = parsedId !== null && Number.isFinite(parsedId) ? parsedId : null;
  const isEdit = bomId !== null;

  const [draft, setDraft] = useState<BomFormValues | null>(null);
  const [submitted, setSubmitted] = useState(false);
  const [toast, setToast] = useState<ToastState | null>(null);

  const detail = useQuery({
    queryKey: ['master-bom', bomId],
    queryFn: () => fetchBom(client, bomId ?? 0),
    enabled: isEdit,
    staleTime: 15_000,
  });

  /** Master produk (dropdown header + baris). */
  const products = useQuery({
    queryKey: ['master-products', 'bom-options'],
    queryFn: () => fetchProducts(client, { limit: PRODUCTS_LIMIT_MAX, active: true }),
    staleTime: 60_000,
  });

  /** Master UoM (dropdown output + baris). */
  const uoms = useQuery({
    queryKey: ['master-uoms', 'bom-options'],
    queryFn: () => fetchUoms(client, { limit: UOMS_LIMIT_MAX, active: true }),
    staleTime: 60_000,
  });

  /** Nilai form = draft pengguna → data GET (mode edit) → form kosong (tanpa effect). */
  const values: BomFormValues =
    draft ?? (detail.data === undefined ? EMPTY_BOM_FORM : bomFormFromDetail(detail.data));

  const errors = useMemo(() => validateBomForm(values), [values]);
  const valid = isBomFormValid(errors);

  const productOptions = useMemo<{ value: string; label: string }[]>(() => {
    const rows = products.data?.rows ?? [];

    return [
      NO_PRODUCT_OPTION,
      ...rows.map((row) => ({ value: String(row.id), label: productOptionLabel(row) })),
    ];
  }, [products.data]);

  const uomOptions = useMemo<{ value: string; label: string }[]>(() => {
    const rows = uoms.data?.rows ?? [];

    return [NO_UOM_OPTION, ...rows.map((row) => ({ value: String(row.id), label: row.name }))];
  }, [uoms.data]);

  const save = useMutation({
    mutationFn: async () => {
      const input = bomInputFromForm(values);

      return isEdit ? updateBom(client, bomId, input) : createBom(client, input);
    },
    onSuccess: (saved) => {
      trigger('success');
      setToast({
        tone: 'success',
        title: isEdit ? 'BOM diperbarui' : 'BOM dibuat',
        description: `${saved.code} — ${String(saved.lines.length)} komponen, push Odoo ${
          saved.queued ? 'diantrekan' : 'belum masuk broker'
        } (Odoo ID: ${saved.odoo_id === null ? 'belum ada' : String(saved.odoo_id)}).`,
      });
      navigate(`/master/boms/${String(saved.id)}`);
    },
    onError: (caught) => {
      trigger('error');
      setToast({
        tone: 'error',
        title: 'Gagal menyimpan BOM',
        description: caught instanceof Error ? caught.message : 'Permintaan simpan gagal.',
      });
    },
  });

  function setField<K extends keyof BomFormValues>(field: K, value: BomFormValues[K]): void {
    setDraft({ ...values, [field]: value });
  }

  function handleAddLine(): void {
    setDraft(addBomLine(values));
  }

  function handleRemoveLine(index: number): void {
    setDraft(removeBomLine(values, index));
  }

  function handleLineChange(
    index: number,
    patch: Parameters<typeof updateBomLine>[2],
  ): void {
    setDraft(updateBomLine(values, index, patch));
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
        title={isEdit ? 'Edit BOM' : 'BOM Baru'}
        subtitle="Bill of Material MES — header + komponen dikirim sekaligus (asinkron ke Odoo)"
        breadcrumb={[
          { label: 'Inventory', href: '/inventory/products' },
          { label: 'Master BOM', href: '/master/boms' },
          { label: isEdit ? 'Edit' : 'Baru' },
        ]}
        actions={
          <Button variant="ghost" icon={ArrowLeft} onClick={() => navigate('/master/boms')}>
            Kembali
          </Button>
        }
      />

      {isEdit && detail.isLoading ? (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Spinner size="sm" /> Memuat BOM…
        </div>
      ) : null}

      {isEdit && detail.error !== null ? (
        <section className={cn(CARD, 'flex flex-col gap-2')}>
          <p role="alert" className="text-sm font-medium text-accent-coral">
            Gagal memuat BOM (perlu login atau BOM tidak ada).
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
            label="Produk *"
            options={productOptions}
            value={values.product_id}
            onChange={(event) => setField('product_id', event.target.value)}
            {...(showErrors && errors.product_id !== undefined ? { error: errors.product_id } : {})}
          />
          <Input
            label="Jumlah Output *"
            type="number"
            min="0"
            step="0.001"
            value={values.output_qty}
            onChange={(event) => setField('output_qty', event.target.value)}
            {...(showErrors && errors.output_qty !== undefined ? { error: errors.output_qty } : {})}
          />
          <Select
            label="Satuan Output"
            options={uomOptions}
            value={values.uom_id}
            onChange={(event) => setField('uom_id', event.target.value)}
            {...(showErrors && errors.uom_id !== undefined ? { error: errors.uom_id } : {})}
          />
          <Input
            label="Kode (opsional)"
            value={values.code}
            placeholder="kosongkan agar dibuat otomatis"
            onChange={(event) => setField('code', event.target.value)}
            {...(showErrors && errors.code !== undefined ? { error: errors.code } : {})}
          />
          <Input
            label="Nama"
            value={values.name}
            placeholder="mis. BOM Kaos Export L"
            onChange={(event) => setField('name', event.target.value)}
            {...(showErrors && errors.name !== undefined ? { error: errors.name } : {})}
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
              Komponen ({String(values.lines.length)} baris)
            </h2>
            <Button
              type="button"
              variant="secondary"
              size="sm"
              icon={Plus}
              onClick={handleAddLine}
            >
              Tambah Baris
            </Button>
          </div>

          {values.lines.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              Belum ada komponen. Tambahkan baris untuk memilih bahan.
            </p>
          ) : null}

          {values.lines.map((line, index) => {
            const lineError = showErrors ? errors.lines?.[index] : undefined;

            return (
              <div
                key={`${String(line.id ?? 'baru')}-${String(index)}`}
                className="grid grid-cols-1 items-end gap-3 border-t border-border pt-3 md:grid-cols-12"
              >
                <div className="md:col-span-4">
                  <Select
                    label={`Komponen ${String(index + 1)} *`}
                    options={productOptions}
                    value={line.product_id}
                    onChange={(event) =>
                      handleLineChange(index, { product_id: event.target.value })
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
                    step="0.001"
                    value={line.qty}
                    onChange={(event) => handleLineChange(index, { qty: event.target.value })}
                    {...(lineError?.qty !== undefined ? { error: lineError.qty } : {})}
                  />
                </div>
                <div className="md:col-span-3">
                  <Select
                    label="Satuan"
                    options={uomOptions}
                    value={line.uom_id}
                    onChange={(event) => handleLineChange(index, { uom_id: event.target.value })}
                    {...(lineError?.uom_id !== undefined ? { error: lineError.uom_id } : {})}
                  />
                </div>
                <div className="md:col-span-1">
                  <Input
                    label="Urut"
                    type="number"
                    min="0"
                    value={line.sequence}
                    onChange={(event) => handleLineChange(index, { sequence: event.target.value })}
                  />
                </div>
                <div className="md:col-span-2">
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    icon={Trash2}
                    aria-label={`Hapus baris ${String(index + 1)}`}
                    onClick={() => handleRemoveLine(index)}
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
            <Checkbox
              label="BOM aktif (dipakai perhitungan kebutuhan bahan)"
              checked={values.active}
              onCheckedChange={(checked) => setField('active', checked)}
            />
            <p className="text-xs text-muted-foreground">
              Catatan: komponen tidak boleh memakai produk BOM sendiri; siklus antar-BOM
              ditolak backend. Kode kosong dibuat otomatis (BOM-&lt;kode produk&gt;).
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <Button type="submit" icon={Save} loading={save.isPending}>
              {isEdit ? 'Simpan Perubahan' : 'Simpan BOM'}
            </Button>
            <Button type="button" variant="secondary" onClick={() => navigate('/master/boms')}>
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

