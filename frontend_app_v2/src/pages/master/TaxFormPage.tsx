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
import { createTax, fetchTax, updateTax } from '@/api/masterTaxes';
import { useFeedback } from '@/app/app-runtime';
import { useApiClient } from '@/hooks/useApiClient';
import { cn } from '@/lib/cn';
import {
  AMOUNT_TYPE_OPTIONS,
  EMPTY_TAX_FORM,
  isTaxAmountType,
  isTaxFormValid,
  isTaxUse,
  taxFormFromRow,
  taxInputFromForm,
  TAX_USE_OPTIONS,
  validateTaxForm,
  type TaxFormValues,
} from '@/lib/master-tax';
import { CARD } from '@/lib/tokens';

/**
 * TaxFormPage - route `/master/taxes/new` + `/master/taxes/:id/edit` (H3.6).
 *
 * MES = source of truth master: field `name`, `code` (boleh kosong → dibuat otomatis
 * dari nama), `amount` (0 diizinkan), `amount_type`, `type_tax_use`, `price_include`,
 * `is_default` (penanda default MES), `active`.
 *
 *   * create → `POST /api/v1/master/taxes/` (`createTax`);
 *   * edit   → `PUT /api/v1/master/taxes/<id>/` (`updateTax`);
 *   * validasi `lib/master-tax.ts::validateTaxForm` (PURE) — pesan error muncul
 *     setelah submit pertama; tombol tidak dimatikan supaya penyebabnya terlihat;
 *   * sukses → Toast + pindah ke detail; push Odoo asinkron (Celery).
 *
 * `amount_type`/`type_tax_use` **tidak** dikirim ke Odoo sebagai `tax_group_id` —
 * Odoo mengisi grup pajaknya sendiri (`_compute_tax_group_id`).
 */

interface ToastState {
  tone: ToastTone;
  title: string;
  description: string;
}

export function TaxFormPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const client = useApiClient();
  const { trigger } = useFeedback();

  const parsedId = id === undefined ? null : Number(id);
  const taxId = parsedId !== null && Number.isFinite(parsedId) ? parsedId : null;
  const isEdit = taxId !== null;

  const [draft, setDraft] = useState<TaxFormValues | null>(null);
  const [submitted, setSubmitted] = useState(false);
  const [toast, setToast] = useState<ToastState | null>(null);

  const detail = useQuery({
    queryKey: ['master-tax', taxId],
    queryFn: () => fetchTax(client, taxId ?? 0),
    enabled: isEdit,
    staleTime: 15_000,
  });

  /** Nilai form = draft pengguna → data GET (mode edit) → form kosong (tanpa effect). */
  const values: TaxFormValues =
    draft ?? (detail.data === undefined ? EMPTY_TAX_FORM : taxFormFromRow(detail.data));

  const errors = useMemo(() => validateTaxForm(values), [values]);
  const valid = isTaxFormValid(errors);

  const save = useMutation({
    mutationFn: async () => {
      const input = taxInputFromForm(values);

      return isEdit ? updateTax(client, taxId, input) : createTax(client, input);
    },
    onSuccess: (saved) => {
      trigger('success');
      setToast({
        tone: 'success',
        title: isEdit ? 'Pajak diperbarui' : 'Pajak dibuat',
        description: `${saved.code || saved.name} — push Odoo ${
          saved.queued ? 'diantrekan' : 'belum masuk broker'
        } (Odoo ID: ${saved.odoo_id === null ? '-' : String(saved.odoo_id)}).`,
      });
      navigate(`/master/taxes/${String(saved.id)}`);
    },
    onError: (caught) => {
      trigger('error');
      setToast({
        tone: 'error',
        title: 'Gagal menyimpan pajak',
        description: caught instanceof Error ? caught.message : 'Permintaan simpan gagal.',
      });
    },
  });

  function setField<K extends keyof TaxFormValues>(field: K, value: TaxFormValues[K]): void {
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
        title={isEdit ? 'Edit Pajak' : 'Pajak Baru'}
        subtitle="Master pajak MES — disimpan di MES lalu di-push ke Odoo (asinkron)"
        breadcrumb={[
          { label: 'Inventory', href: '/inventory/products' },
          { label: 'Master Pajak', href: '/master/taxes' },
          { label: isEdit ? 'Edit' : 'Baru' },
        ]}
        actions={
          <Button variant="ghost" icon={ArrowLeft} onClick={() => navigate('/master/taxes')}>
            Kembali
          </Button>
        }
      />

      {isEdit && detail.isLoading ? (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Spinner size="sm" /> Memuat pajak…
        </div>
      ) : null}

      {isEdit && detail.error !== null ? (
        <section className={cn(CARD, 'flex flex-col gap-2')}>
          <p role="alert" className="text-sm font-medium text-accent-coral">
            Gagal memuat pajak (perlu login atau pajak tidak ada).
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
            label="Nama *"
            value={values.name}
            placeholder="mis. PPN 11%"
            onChange={(event) => setField('name', event.target.value)}
            {...(showErrors && errors.name !== undefined ? { error: errors.name } : {})}
          />
          <Input
            label="Kode"
            value={values.code}
            placeholder="mis. PPN11-SALE (kosong = dibuat dari nama)"
            onChange={(event) => setField('code', event.target.value)}
            {...(showErrors && errors.code !== undefined ? { error: errors.code } : {})}
          />
          <Input
            label="Tarif *"
            type="number"
            min={0}
            step="0.01"
            value={values.amount}
            onChange={(event) => setField('amount', event.target.value)}
            {...(showErrors && errors.amount !== undefined ? { error: errors.amount } : {})}
          />
          <Select
            label="Tipe nilai"
            options={AMOUNT_TYPE_OPTIONS.map((option) => ({
              value: option.value,
              label: option.label,
            }))}
            value={values.amount_type}
            onChange={(event) => {
              const next = event.target.value;
              if (isTaxAmountType(next)) setField('amount_type', next);
            }}
          />
          <Select
            label="Jenis pajak"
            options={TAX_USE_OPTIONS.map((option) => ({
              value: option.value,
              label: option.label,
            }))}
            value={values.type_tax_use}
            onChange={(event) => {
              const next = event.target.value;
              if (isTaxUse(next)) setField('type_tax_use', next);
            }}
          />
        </section>

        <section className={cn(CARD, 'flex flex-wrap items-center justify-between gap-3')}>
          <div className="flex flex-col gap-2">
            <Checkbox
              label="Harga sudah termasuk pajak (price_include)"
              checked={values.price_include}
              onCheckedChange={(checked) => setField('price_include', checked)}
            />
            <Checkbox
              label="Jadikan pajak default MES (dipakai form order/invoice)"
              checked={values.is_default}
              onCheckedChange={(checked) => setField('is_default', checked)}
            />
            <Checkbox
              label="Pajak aktif (bisa dipakai order & invoice)"
              checked={values.active}
              onCheckedChange={(checked) => setField('active', checked)}
            />
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <Button type="submit" icon={Save} loading={save.isPending}>
              {isEdit ? 'Simpan Perubahan' : 'Simpan Pajak'}
            </Button>
            <Button type="button" variant="secondary" onClick={() => navigate('/master/taxes')}>
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
