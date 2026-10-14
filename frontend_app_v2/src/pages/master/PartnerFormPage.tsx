import { useMemo, useState, type FormEvent } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useMutation, useQuery } from '@tanstack/react-query';
import { ArrowLeft, Save } from 'lucide-react';
import { Button } from '@/components/atoms/Button';
import { Checkbox } from '@/components/atoms/Checkbox';
import { Input } from '@/components/atoms/Input';
import { Spinner } from '@/components/atoms/Spinner';
import { Toast, type ToastTone } from '@/components/atoms/Toast';
import { PageHeader } from '@/components/molecules/PageHeader';
import { createPartner, fetchPartner, updatePartner } from '@/api/masterPartners';
import { useFeedback } from '@/app/app-runtime';
import { useApiClient } from '@/hooks/useApiClient';
import { cn } from '@/lib/cn';
import {
  EMPTY_PARTNER_FORM,
  isPartnerFormValid,
  partnerFormFromRow,
  partnerInputFromForm,
  validatePartnerForm,
  type PartnerFormValues,
} from '@/lib/master-partner';
import { CARD } from '@/lib/tokens';

/**
 * PartnerFormPage - route `/master/partners/new` + `/master/partners/:id/edit` (H1.6).
 *
 * Field: nama (wajib), peran `Pelanggan`/`Supplier` (minimal satu aktif),
 * jenis (perusahaan/perorangan), email, telepon, kota, alamat, NPWP, aktif.
 *
 *   * create → `POST /api/v1/master/partners/` (`createPartner`);
 *   * edit   → `PUT /api/v1/master/partners/<id>/` (`updatePartner`);
 *   * validasi PURE `lib/master-partner.ts` (nama wajib, peran minimal satu, NPWP
 *     15/16 digit, email format) — error muncul setelah submit pertama;
 *   * kode boleh dikosongkan → backend membangkitkan `PTR-<slug nama>`;
 *   * sukses → Toast + pindah ke detail; push Odoo asinkron (`erp_sync.push_master_partner`);
 *   * izin tulis dibatasi role ADMIN/OWNER di backend (403 kalau bukan).
 */

interface ToastState {
  tone: ToastTone;
  title: string;
  description: string;
}

export function PartnerFormPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const client = useApiClient();
  const { trigger } = useFeedback();

  const parsedId = id === undefined ? null : Number(id);
  const partnerId = parsedId !== null && Number.isFinite(parsedId) ? parsedId : null;
  const isEdit = partnerId !== null;

  const [draft, setDraft] = useState<PartnerFormValues | null>(null);
  const [submitted, setSubmitted] = useState(false);
  const [toast, setToast] = useState<ToastState | null>(null);

  const detail = useQuery({
    queryKey: ['master-partner', partnerId],
    queryFn: () => fetchPartner(client, partnerId ?? 0),
    enabled: isEdit,
    staleTime: 15_000,
  });

  /** Nilai form = draft pengguna → data GET (mode edit) → form kosong (tanpa effect). */
  const values: PartnerFormValues =
    draft ?? (detail.data === undefined ? EMPTY_PARTNER_FORM : partnerFormFromRow(detail.data));

  const errors = useMemo(() => validatePartnerForm(values), [values]);
  const valid = isPartnerFormValid(errors);

  const save = useMutation({
    mutationFn: async () => {
      const input = partnerInputFromForm(values);

      return isEdit ? updatePartner(client, partnerId, input) : createPartner(client, input);
    },
    onSuccess: (saved) => {
      trigger('success');
      setToast({
        tone: 'success',
        title: isEdit ? 'Partner diperbarui' : 'Partner dibuat',
        description: `${saved.code} — push Odoo ${
          saved.queued ? 'diantrekan' : 'belum masuk broker'
        } (Odoo ID: ${saved.odoo_id === null ? 'belum ada' : String(saved.odoo_id)}).`,
      });
      navigate(`/master/partners/${String(saved.id)}`);
    },
    onError: (caught) => {
      trigger('error');
      setToast({
        tone: 'error',
        title: 'Gagal menyimpan partner',
        description: caught instanceof Error ? caught.message : 'Permintaan simpan gagal.',
      });
    },
  });

  function setField<K extends keyof PartnerFormValues>(
    field: K,
    value: PartnerFormValues[K],
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
        title={isEdit ? 'Edit Partner' : 'Partner Baru'}
        subtitle="Master partner MES — disimpan di MES lalu di-push ke Odoo (asinkron)"
        breadcrumb={[
          { label: 'Inventory', href: '/inventory/products' },
          { label: 'Master Partner', href: '/master/partners' },
          { label: isEdit ? 'Edit' : 'Baru' },
        ]}
        actions={
          <Button variant="ghost" icon={ArrowLeft} onClick={() => navigate('/master/partners')}>
            Kembali
          </Button>
        }
      />

      {isEdit && detail.isLoading ? (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Spinner size="sm" /> Memuat partner…
        </div>
      ) : null}

      {isEdit && detail.error !== null ? (
        <section className={cn(CARD, 'flex flex-col gap-2')}>
          <p role="alert" className="text-sm font-medium text-accent-coral">
            Gagal memuat partner (perlu login atau partner tidak ada).
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
            placeholder="mis. PT Buyer Export"
            onChange={(event) => setField('name', event.target.value)}
            {...(showErrors && errors.name !== undefined ? { error: errors.name } : {})}
          />
          <Input
            label="Kode (opsional)"
            value={values.code}
            placeholder="kosongkan agar dibuat otomatis"
            onChange={(event) => setField('code', event.target.value)}
            {...(showErrors && errors.code !== undefined ? { error: errors.code } : {})}
          />
          <Input
            label="Email"
            type="email"
            value={values.email}
            placeholder="nama@domain.com"
            onChange={(event) => setField('email', event.target.value)}
            {...(showErrors && errors.email !== undefined ? { error: errors.email } : {})}
          />
          <Input
            label="Telepon"
            value={values.phone}
            placeholder="mis. +62 812-3456-7890"
            onChange={(event) => setField('phone', event.target.value)}
            {...(showErrors && errors.phone !== undefined ? { error: errors.phone } : {})}
          />
          <Input
            label="Kota"
            value={values.city}
            placeholder="mis. Bandung"
            onChange={(event) => setField('city', event.target.value)}
            {...(showErrors && errors.city !== undefined ? { error: errors.city } : {})}
          />
          <Input
            label="NPWP"
            value={values.npwp}
            placeholder="15/16 digit (boleh dengan titik/strip)"
            onChange={(event) => setField('npwp', event.target.value)}
            {...(showErrors && errors.npwp !== undefined ? { error: errors.npwp } : {})}
          />
          <div className="md:col-span-2">
            <Input
              label="Alamat"
              value={values.address}
              placeholder="mis. Jl. Merdeka 10"
              onChange={(event) => setField('address', event.target.value)}
              {...(showErrors && errors.address !== undefined ? { error: errors.address } : {})}
            />
          </div>
        </section>

        <section className={cn(CARD, 'flex flex-wrap items-center justify-between gap-3')}>
          <div className="flex flex-col gap-2">
            <Checkbox
              label="Pelanggan (dipakai di Sales Order)"
              checked={values.is_customer}
              onCheckedChange={(checked) => setField('is_customer', checked)}
            />
            <Checkbox
              label="Supplier / vendor (dipakai di Purchase Order)"
              checked={values.is_vendor}
              onCheckedChange={(checked) => setField('is_vendor', checked)}
            />
            <Checkbox
              label="Perusahaan (badan usaha; non-aktif = perorangan)"
              checked={values.is_company}
              onCheckedChange={(checked) => setField('is_company', checked)}
            />
            <Checkbox
              label="Partner aktif"
              checked={values.active}
              onCheckedChange={(checked) => setField('active', checked)}
            />
            {showErrors && errors.roles !== undefined ? (
              <p role="alert" className="text-sm font-medium text-accent-coral">
                {errors.roles}
              </p>
            ) : null}
            <p className="text-xs text-muted-foreground">
              Catatan: minimal satu peran harus aktif. NPWP dikirim ke Odoo sebagai `vat`
              (digit saja), alamat sebagai `street`.
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <Button type="submit" icon={Save} loading={save.isPending}>
              {isEdit ? 'Simpan Perubahan' : 'Simpan Partner'}
            </Button>
            <Button type="button" variant="secondary" onClick={() => navigate('/master/partners')}>
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
