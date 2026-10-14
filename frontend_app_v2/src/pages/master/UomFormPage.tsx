import { useMemo, useState, type FormEvent } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useMutation, useQuery } from '@tanstack/react-query';
import { ArrowLeft, Save } from 'lucide-react';
import { Button } from '@/components/atoms/Button';
import { Checkbox } from '@/components/atoms/Checkbox';
import { Input } from '@/components/atoms/Input';
import { Select } from '@/components/atoms/Select';
import { Spinner } from '@/components/atoms/Spinner';
import { Toast, type ToastTone } from '@/components/atoms/Toast';
import { PageHeader } from '@/components/molecules/PageHeader';
import { createUom, fetchUom, updateUom } from '@/api/masterUoms';
import { useFeedback } from '@/app/app-runtime';
import { useApiClient } from '@/hooks/useApiClient';
import { cn } from '@/lib/cn';
import {
  EMPTY_UOM_FORM,
  isUomFormValid,
  isUomType,
  uomFormFromRow,
  uomInputFromForm,
  UOM_TYPE_OPTIONS,
  validateUomForm,
  type UomFormValues,
} from '@/lib/master-uom';
import { CARD } from '@/lib/tokens';

/**
 * UomFormPage - route `/master/uoms/new` + `/master/uoms/:id/edit` (H1.2).
 *
 * MES = source of truth master: 7 field (code, name, category, uom_type, factor,
 * rounding, active) — `category`/`uom_type`/`factor`/`rounding` disimpan di MES
 * karena **wajib** di Odoo (`uom.uom`), sehingga push tidak perlu mengarang data.
 *
 *   * create → `POST /api/v1/master/uoms/` (`createUom`);
 *   * edit   → `PUT /api/v1/master/uoms/<id>/` (`updateUom`);
 *   * validasi `lib/master-uom.ts::validateUomForm` (PURE) — pesan error muncul
 *     setelah submit pertama; tombol tidak dimatikan supaya penyebabnya terlihat;
 *   * sukses → Toast + pindah ke detail; push Odoo asinkron (Celery);
 *   * izin tulis dibatasi role ADMIN/OWNER di backend (403 kalau bukan).
 */

interface ToastState {
  tone: ToastTone;
  title: string;
  description: string;
}

export function UomFormPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const client = useApiClient();
  const { trigger } = useFeedback();

  const parsedId = id === undefined ? null : Number(id);
  const uomId = parsedId !== null && Number.isFinite(parsedId) ? parsedId : null;
  const isEdit = uomId !== null;

  const [draft, setDraft] = useState<UomFormValues | null>(null);
  const [submitted, setSubmitted] = useState(false);
  const [toast, setToast] = useState<ToastState | null>(null);

  const detail = useQuery({
    queryKey: ['master-uom', uomId],
    queryFn: () => fetchUom(client, uomId ?? 0),
    enabled: isEdit,
    staleTime: 15_000,
  });

  /** Nilai form = draft pengguna → data GET (mode edit) → form kosong (tanpa effect). */
  const values: UomFormValues =
    draft ?? (detail.data === undefined ? EMPTY_UOM_FORM : uomFormFromRow(detail.data));

  const errors = useMemo(() => validateUomForm(values), [values]);
  const valid = isUomFormValid(errors);

  const save = useMutation({
    mutationFn: async () => {
      const input = uomInputFromForm(values);

      return isEdit ? updateUom(client, uomId, input) : createUom(client, input);
    },
    onSuccess: (saved) => {
      trigger('success');
      setToast({
        tone: 'success',
        title: isEdit ? 'UoM diperbarui' : 'UoM dibuat',
        description: `${saved.code} — push Odoo ${
          saved.queued ? 'diantrekan' : 'belum masuk broker'
        } (Odoo ID: ${saved.odoo_id === null ? '-' : String(saved.odoo_id)}).`,
      });
      navigate(`/master/uoms/${String(saved.id)}`);
    },
    onError: (caught) => {
      trigger('error');
      setToast({
        tone: 'error',
        title: 'Gagal menyimpan UoM',
        description: caught instanceof Error ? caught.message : 'Permintaan simpan gagal.',
      });
    },
  });

  function setField<K extends keyof UomFormValues>(field: K, value: UomFormValues[K]): void {
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
        title={isEdit ? 'Edit UoM' : 'UoM Baru'}
        subtitle="Master UoM MES — disimpan di MES lalu di-push ke Odoo (asinkron)"
        breadcrumb={[
          { label: 'Inventory', href: '/inventory/products' },
          { label: 'Master UoM', href: '/master/uoms' },
          { label: isEdit ? 'Edit' : 'Baru' },
        ]}
        actions={
          <Button variant="ghost" icon={ArrowLeft} onClick={() => navigate('/master/uoms')}>
            Kembali
          </Button>
        }
      />

      {isEdit && detail.isLoading ? (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Spinner size="sm" /> Memuat UoM…
        </div>
      ) : null}

      {isEdit && detail.error !== null ? (
        <section className={cn(CARD, 'flex flex-col gap-2')}>
          <p role="alert" className="text-sm font-medium text-accent-coral">
            Gagal memuat UoM (perlu login atau UoM tidak ada).
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
            placeholder="mis. PCS"
            onChange={(event) => setField('code', event.target.value)}
            {...(showErrors && errors.code !== undefined ? { error: errors.code } : {})}
          />
          <Input
            label="Nama *"
            value={values.name}
            placeholder="mis. Pieces"
            onChange={(event) => setField('name', event.target.value)}
            {...(showErrors && errors.name !== undefined ? { error: errors.name } : {})}
          />
          <Input
            label="Kategori *"
            value={values.category}
            placeholder="mis. Unit (dibuat otomatis di Odoo kalau belum ada)"
            onChange={(event) => setField('category', event.target.value)}
            {...(showErrors && errors.category !== undefined ? { error: errors.category } : {})}
          />
          <Select
            label="Tipe"
            options={UOM_TYPE_OPTIONS.map((option) => ({
              value: option.value,
              label: option.label,
            }))}
            value={values.uom_type}
            onChange={(event) => {
              const next = event.target.value;
              if (isUomType(next)) setField('uom_type', next);
            }}
          />
          <Input
            label="Rasio (factor) *"
            type="number"
            min={0}
            step="0.0001"
            value={values.factor}
            onChange={(event) => setField('factor', event.target.value)}
            {...(showErrors && errors.factor !== undefined ? { error: errors.factor } : {})}
          />
          <Input
            label="Presisi pembulatan *"
            type="number"
            min={0}
            step="0.0001"
            value={values.rounding}
            onChange={(event) => setField('rounding', event.target.value)}
            {...(showErrors && errors.rounding !== undefined ? { error: errors.rounding } : {})}
          />
        </section>

        <section className={cn(CARD, 'flex flex-wrap items-center justify-between gap-3')}>
          <Checkbox
            label="UoM aktif (bisa dipakai produk & order)"
            checked={values.active}
            onCheckedChange={(checked) => setField('active', checked)}
          />

          <div className="flex flex-wrap items-center gap-2">
            <Button type="submit" icon={Save} loading={save.isPending}>
              {isEdit ? 'Simpan Perubahan' : 'Simpan UoM'}
            </Button>
            <Button type="button" variant="secondary" onClick={() => navigate('/master/uoms')}>
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

