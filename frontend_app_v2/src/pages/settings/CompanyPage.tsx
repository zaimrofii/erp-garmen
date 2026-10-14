import { useMemo, useState, type FormEvent } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { RefreshCw, Save } from 'lucide-react';
import { Button } from '@/components/atoms/Button';
import { Checkbox } from '@/components/atoms/Checkbox';
import { Input } from '@/components/atoms/Input';
import { Select, type SelectOption } from '@/components/atoms/Select';
import { Spinner } from '@/components/atoms/Spinner';
import { Textarea } from '@/components/atoms/Textarea';
import { Toast, type ToastTone } from '@/components/atoms/Toast';
import { PageHeader } from '@/components/molecules/PageHeader';
import { fetchCompany, updateCompany } from '@/api/company';
import { CURRENCIES_LIMIT_MAX, fetchCurrencies } from '@/api/masterCurrencies';
import { useFeedback } from '@/app/app-runtime';
import { useApiClient } from '@/hooks/useApiClient';
import { cn } from '@/lib/cn';
import {
  MAX_COMPANY_NAME_LENGTH,
  companyFormFromRow,
  companyInputFromForm,
  isCompanyFormValid,
  validateCompanyForm,
  type CompanyFormValues,
} from '@/lib/company';
import { CARD } from '@/lib/tokens';

/**
 * CompanyPage - route `/settings/company` (H5.1, khusus admin).
 *
 * Profil perusahaan (identitas header dokumen/cetak) — **SINGLETON**:
 *
 *   * `GET /api/v1/settings/company/` → `{"company": {…}|null}` (`null` = belum diisi;
 *     **tanpa** seed — UI menampilkan form kosong, pola `/taxes/default/` H3.6);
 *   * **Simpan** → `PUT …/company/` (**create-on-first-PUT**: baris dibuat sekali bila
 *     belum ada ⇒ 2× Simpan tetap 1 baris; izin tulis backend **ADMIN/OWNER**);
 *   * field: nama*, nama legal, alamat, kota, negara (ISO 2 huruf), telepon, email,
 *     NPWP (15/16 digit — pola H1.6), website, logo URL, **mata uang** (dropdown H5.2),
 *     zona waktu, aktif;
 *   * **MES-only**: tanpa tombol Sync (identitas tidak dikirim ke `res.company` Odoo —
 *     `res.company` = konfigurasi akuntansi); setiap simpan mencatat ledger `SKIPPED`
 *     di `/api/v1/sync/records/?status=SKIPPED`.
 *
 * Guard route: `SETTINGS_ROLES` (pola `/settings/sequences`, `/settings/currencies`).
 */

const QUERY_KEY = 'settings-company';
const CURRENCY_QUERY_KEY = 'settings-company-currencies';

interface ToastState {
  tone: ToastTone;
  title: string;
  description: string;
}

export function CompanyPage() {
  const client = useApiClient();
  const queryClient = useQueryClient();
  const { trigger } = useFeedback();

  const [draft, setDraft] = useState<CompanyFormValues | null>(null);
  const [submitted, setSubmitted] = useState(false);
  const [toast, setToast] = useState<ToastState | null>(null);

  const detail = useQuery({
    queryKey: [QUERY_KEY],
    queryFn: () => fetchCompany(client),
    staleTime: 15_000,
  });

  const currencies = useQuery({
    queryKey: [CURRENCY_QUERY_KEY],
    queryFn: () => fetchCurrencies(client, { active: true, limit: CURRENCIES_LIMIT_MAX }),
    staleTime: 60_000,
  });

  /** Nilai form = draft pengguna → data GET → form kosong (tanpa effect). */
  const values: CompanyFormValues =
    draft ?? companyFormFromRow(detail.data === undefined ? null : detail.data);

  const errors = useMemo(() => validateCompanyForm(values), [values]);
  const valid = isCompanyFormValid(errors);

  const save = useMutation({
    mutationFn: () => updateCompany(client, companyInputFromForm(values)),
    onSuccess: (saved) => {
      trigger('success');
      setToast({
        tone: 'success',
        title: 'Profil perusahaan disimpan',
        description: `${saved.name} — MES-only (ledger SKIPPED, tidak dikirim ke Odoo).`,
      });
      setDraft(null);
      setSubmitted(false);
      void queryClient.invalidateQueries({ queryKey: [QUERY_KEY] });
    },
    onError: (caught) => {
      trigger('error');
      setToast({
        tone: 'error',
        title: 'Gagal menyimpan profil',
        description: caught instanceof Error ? caught.message : 'Permintaan simpan gagal.',
      });
    },
  });

  function setField<K extends keyof CompanyFormValues>(
    field: K,
    value: CompanyFormValues[K],
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

  /** Opsi dropdown mata uang (H5.2) — hanya mata uang aktif. */
  const currencyOptions: SelectOption[] = useMemo(() => {
    const rows = currencies.data?.rows ?? [];

    return [
      { value: '', label: '— Tanpa mata uang —' },
      ...rows.map((row) => ({ value: String(row.id), label: `${row.code} — ${row.name}` })),
    ];
  }, [currencies.data]);

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <PageHeader
        title="Company Profile"
        subtitle="Identitas perusahaan MES (header dokumen/cetak) — MES-only, tidak disinkron ke Odoo"
        breadcrumb={[{ label: 'Settings' }, { label: 'Company' }]}
        actions={
          <Button
            variant="ghost"
            icon={RefreshCw}
            onClick={() => {
              setDraft(null);
              void detail.refetch();
            }}
          >
            Muat Ulang
          </Button>
        }
      />

      {detail.isLoading ? (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Spinner size="sm" /> Memuat profil perusahaan…
        </div>
      ) : null}

      {detail.error !== null ? (
        <section className={cn(CARD, 'flex flex-col gap-2')}>
          <p role="alert" className="text-sm font-medium text-accent-coral">
            Gagal memuat profil perusahaan.
          </p>
        </section>
      ) : null}

      {detail.data === null && draft === null ? (
        <p className="text-xs text-muted-foreground">
          Profil belum diisi — isi nama perusahaan lalu klik Simpan (baris dibuat otomatis,
          PUT pertama = create).
        </p>
      ) : null}

      <form className="flex flex-col gap-4" onSubmit={handleSubmit}>
        <section className={cn(CARD, 'grid grid-cols-1 gap-4 md:grid-cols-2')}>
          <Input
            label="Nama perusahaan *"
            value={values.name}
            placeholder={`mis. PT Garmen Jaya (maks ${String(MAX_COMPANY_NAME_LENGTH)} karakter)`}
            onChange={(event) => setField('name', event.target.value)}
            {...(showErrors && errors.name !== undefined ? { error: errors.name } : {})}
          />
          <Input
            label="Nama legal"
            value={values.legal_name}
            placeholder="mis. PT Garmen Jaya Sejahtera"
            onChange={(event) => setField('legal_name', event.target.value)}
          />
          <div className="md:col-span-2">
            <Textarea
              label="Alamat"
              value={values.address}
              placeholder="mis. Jl. Industri 1, Blok C"
              onChange={(event) => setField('address', event.target.value)}
            />
          </div>
          <Input
            label="Kota"
            value={values.city}
            placeholder="mis. Bandung"
            onChange={(event) => setField('city', event.target.value)}
          />
          <Input
            label="Negara (ISO 2 huruf)"
            value={values.country}
            placeholder="mis. ID"
            onChange={(event) => setField('country', event.target.value)}
            {...(showErrors && errors.country !== undefined ? { error: errors.country } : {})}
          />
          <Input
            label="Telepon"
            value={values.phone}
            placeholder="mis. 022-123456"
            onChange={(event) => setField('phone', event.target.value)}
          />
          <Input
            label="Email"
            value={values.email}
            placeholder="mis. admin@perusahaan.co.id"
            onChange={(event) => setField('email', event.target.value)}
            {...(showErrors && errors.email !== undefined ? { error: errors.email } : {})}
          />
          <Input
            label="NPWP"
            value={values.npwp}
            placeholder="15/16 digit (boleh dengan titik/strip)"
            onChange={(event) => setField('npwp', event.target.value)}
            {...(showErrors && errors.npwp !== undefined ? { error: errors.npwp } : {})}
          />
          <Input
            label="Website"
            value={values.website}
            placeholder="mis. https://perusahaan.co.id"
            onChange={(event) => setField('website', event.target.value)}
            {...(showErrors && errors.website !== undefined ? { error: errors.website } : {})}
          />
          <div className="md:col-span-2">
            <Input
              label="URL logo"
              value={values.logo_url}
              placeholder="mis. https://perusahaan.co.id/logo.png"
              onChange={(event) => setField('logo_url', event.target.value)}
              {...(showErrors && errors.logo_url !== undefined ? { error: errors.logo_url } : {})}
            />
          </div>
        </section>

        <section className={cn(CARD, 'grid grid-cols-1 gap-4 md:grid-cols-2')}>
          <Select
            label="Mata uang default (H5.2)"
            options={currencyOptions}
            value={values.currencyId}
            onChange={(event) => setField('currencyId', event.target.value)}
          />
          <Input
            label="Zona waktu"
            value={values.timezone}
            placeholder="mis. Asia/Jakarta"
            onChange={(event) => setField('timezone', event.target.value)}
            {...(showErrors && errors.timezone !== undefined ? { error: errors.timezone } : {})}
          />
          <div className="flex flex-wrap items-center justify-between gap-3 md:col-span-2">
            <div className="flex flex-col gap-2">
              <Checkbox
                label="Profil aktif (dipakai di header dokumen/cetak)"
                checked={values.active}
                onCheckedChange={(checked) => setField('active', checked)}
              />
              <p className="text-xs text-muted-foreground">
                MES-only: identitas perusahaan tidak dikirim ke `res.company` Odoo
                (konfigurasi akuntansi) — jejak tulis terlihat sebagai ledger `SKIPPED`.
              </p>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <Button type="submit" icon={Save} loading={save.isPending}>
                Simpan Profil
              </Button>
            </div>
          </div>
        </section>
      </form>

      {toast !== null ? (
        <Toast
          open={toast !== null}
          onOpenChange={() => setToast(null)}
          title={toast.title}
          tone={toast.tone}
          description={toast.description}
        />
      ) : null}
    </div>
  );
}

