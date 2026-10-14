import { useMemo, useState, type FormEvent } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Activity, RefreshCw, Save } from 'lucide-react';
import { Badge } from '@/components/atoms/Badge';
import { Button } from '@/components/atoms/Button';
import { Checkbox } from '@/components/atoms/Checkbox';
import { Input } from '@/components/atoms/Input';
import { Select } from '@/components/atoms/Select';
import { Spinner } from '@/components/atoms/Spinner';
import { Toast, type ToastTone } from '@/components/atoms/Toast';
import { PageHeader } from '@/components/molecules/PageHeader';
import {
  fetchIntegrationConfig,
  testIntegrationConnection,
  updateIntegrationConfig,
} from '@/api/integrationConfig';
import { useFeedback } from '@/app/app-runtime';
import { useApiClient } from '@/hooks/useApiClient';
import { cn } from '@/lib/cn';
import {
  ADAPTER_OPTIONS,
  CONFIG_FIELD_LABELS,
  MAX_TOLERANCE_PCT,
  MAX_WA_LENGTH,
  effectiveStatusRows,
  formatConfigValue,
  integrationConfigFormFromRow,
  integrationConfigInputFromForm,
  isIntegrationConfigFormValid,
  isMaskedApiKey,
  validateIntegrationConfigForm,
  type IntegrationConfigFormValues,
  type IntegrationConfigTextField,
} from '@/lib/integration-config';
import { CARD } from '@/lib/tokens';
import type { IntegrationConfigEnvelope, TestConnectionResult } from '@/types/integration-config';

/**
 * IntegrationConfigPage - route `/settings/integration` (H5.6, khusus admin).
 *
 * **SINGLETON + Opsi B**: halaman ini menyimpan *profil* config MES ↔ Odoo ke DB
 * (ber-jejak), **tetapi TIDAK meng-override `.env`** — konsumen (adapter, transport,
 * task) tetap membaca `.env`. Aktivasi = salin nilai ke `.env` lalu restart
 * `django`/`celery_worker`/`celery_beat` (perintahnya datang dari backend:
 * `restart_command`).
 *
 * Lima bagian:
 *   1. **Odoo** — adapter (`odoo`/`null`), URL, database, user, API key (masked),
 *      timeout, aktif;
 *   2. **Lokasi** — 4 id lokasi Odoo + UoM default;
 *   3. **Advanced** — picking type internal + journal pembayaran;
 *   4. **Rekonsiliasi** — toleransi unit/rasio + penerima alert WA;
 *   5. **Status** (read-only) — `effective` (nilai `.env` yang aktif), `diverges`
 *      (field yang beda), `needs_restart`, tombol **Test Koneksi** (POST read-only),
 *      dan instruksi restart.
 *
 * API key: backend **selalu** mengembalikan `***`; kirim `***` = jangan ubah,
 * kosongkan field (di luar mask) = hapus.
 *
 * Guard route: `SETTINGS_ROLES` (pola `/settings/company`, `/settings/currencies`).
 */

const QUERY_KEY = 'settings-integration';

/** Field id lokasi Odoo + label (bagian "Lokasi"). */
const LOCATION_FIELDS: { field: IntegrationConfigTextField; label: string }[] = [
  { field: 'odoo_location_wip_id', label: 'Lokasi WIP (id)' },
  { field: 'odoo_location_production_id', label: 'Lokasi Produksi (id)' },
  { field: 'odoo_location_fg_id', label: 'Lokasi FG (id)' },
  { field: 'odoo_location_scrap_id', label: 'Lokasi Scrap (id)' },
  { field: 'odoo_uom_id', label: 'UoM default (id, mis. PCS)' },
];

/** Field advanced + label (bagian "Advanced"). */
const ADVANCED_FIELDS: { field: IntegrationConfigTextField; label: string }[] = [
  { field: 'odoo_picking_type_internal_id', label: 'Picking type internal (id)' },
  { field: 'odoo_payment_journal_id', label: 'Journal pembayaran (id)' },
];

interface ToastState {
  tone: ToastTone;
  title: string;
  description: string;
}

export function IntegrationConfigPage() {
  const client = useApiClient();
  const queryClient = useQueryClient();
  const { trigger } = useFeedback();

  const [draft, setDraft] = useState<IntegrationConfigFormValues | null>(null);
  const [submitted, setSubmitted] = useState(false);
  const [toast, setToast] = useState<ToastState | null>(null);
  const [testResult, setTestResult] = useState<TestConnectionResult | null>(null);

  const detail = useQuery({
    queryKey: [QUERY_KEY],
    queryFn: () => fetchIntegrationConfig(client),
    staleTime: 15_000,
  });

  const envelope: IntegrationConfigEnvelope | null = detail.data ?? null;

  /** Nilai form = draft pengguna → data GET → form kosong (tanpa effect). */
  const values: IntegrationConfigFormValues =
    draft ?? integrationConfigFormFromRow(envelope?.config ?? null);

  const errors = useMemo(() => validateIntegrationConfigForm(values), [values]);
  const valid = isIntegrationConfigFormValid(errors);

  const save = useMutation({
    mutationFn: () => updateIntegrationConfig(client, integrationConfigInputFromForm(values)),
    onSuccess: (saved) => {
      trigger('success');
      setToast({
        tone: 'success',
        title: 'Profil integrasi disimpan',
        description: saved.needs_restart
          ? 'Belum aktif — salin ke .env lalu restart django/celery_worker/celery_beat.'
          : 'Sudah selaras dengan .env (tidak ada perbedaan).',
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

  const test = useMutation({
    mutationFn: () => testIntegrationConnection(client),
    onSuccess: (result) => {
      trigger(result.ok ? 'success' : 'error');
      setTestResult(result);
    },
    onError: (caught) => {
      trigger('error');
      setToast({
        tone: 'error',
        title: 'Gagal menguji koneksi',
        description: caught instanceof Error ? caught.message : 'Permintaan uji gagal.',
      });
    },
  });

  function setField<K extends keyof IntegrationConfigFormValues>(
    field: K,
    value: IntegrationConfigFormValues[K],
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

  /** Baris config efektif (`.env` yang benar-benar aktif) untuk bagian Status. */
  const statusRows = useMemo(
    () => (envelope === null ? [] : effectiveStatusRows(envelope.effective)),
    [envelope],
  );

  /** Hanya field yang benar-benar beda (DB vs `.env`) — nilai rahasia sudah masked. */
  const divergenceRows = useMemo(
    () =>
      envelope === null
        ? []
        : Object.entries(envelope.diverges).map(([field, divergence]) => ({
            field,
            label: CONFIG_FIELD_LABELS[field] ?? field,
            db: formatConfigValue(divergence.db),
            env: formatConfigValue(divergence.env),
          })),
    [envelope],
  );

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <PageHeader
        title="Integration Config"
        subtitle="Profil konfigurasi MES ↔ Odoo — disimpan di MES; aktivasi lewat .env + restart worker"
        breadcrumb={[{ label: 'Settings' }, { label: 'Integration' }]}
        actions={
          <Button
            variant="ghost"
            icon={RefreshCw}
            onClick={() => {
              setDraft(null);
              setTestResult(null);
              void detail.refetch();
            }}
          >
            Muat Ulang
          </Button>
        }
      />

      {detail.isLoading ? (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Spinner size="sm" /> Memuat konfigurasi integrasi…
        </div>
      ) : null}

      {detail.error !== null ? (
        <section className={cn(CARD, 'flex flex-col gap-2')}>
          <p role="alert" className="text-sm font-medium text-accent-coral">
            Gagal memuat konfigurasi integrasi.
          </p>
        </section>
      ) : null}

      {envelope !== null && envelope.config === null ? (
        <p className="text-xs text-muted-foreground">
          Profil belum diisi — isi kredensial Odoo lalu klik Simpan Profil (baris dibuat
          otomatis; PUT pertama = create).
        </p>
      ) : null}

      <form className="flex flex-col gap-4" onSubmit={handleSubmit}>
        <section className={cn(CARD, 'grid grid-cols-1 gap-4 md:grid-cols-2')}>
          <h2 className="text-sm font-medium text-foreground md:col-span-2">
            Odoo (adapter + kredensial)
          </h2>
          <Select
            label="Adapter ERP"
            options={ADAPTER_OPTIONS}
            value={values.erp_adapter}
            onChange={(event) => setField('erp_adapter', event.target.value)}
            {...(showErrors && errors.erp_adapter !== undefined
              ? { error: errors.erp_adapter }
              : {})}
          />
          <Input
            label="URL Odoo"
            value={values.odoo_url}
            placeholder="mis. http://odoo:8069"
            onChange={(event) => setField('odoo_url', event.target.value)}
            {...(showErrors && errors.odoo_url !== undefined ? { error: errors.odoo_url } : {})}
          />
          <Input
            label="Database Odoo"
            value={values.odoo_db}
            placeholder="mis. garmen_klien"
            onChange={(event) => setField('odoo_db', event.target.value)}
            {...(showErrors && errors.odoo_db !== undefined ? { error: errors.odoo_db } : {})}
          />
          <Input
            label="User Odoo"
            value={values.odoo_user}
            placeholder="mis. api_bot"
            onChange={(event) => setField('odoo_user', event.target.value)}
            {...(showErrors && errors.odoo_user !== undefined ? { error: errors.odoo_user } : {})}
          />
          <Input
            label="API key Odoo"
            type="password"
            value={values.odoo_api_key}
            placeholder="*** = pertahankan kunci tersimpan"
            onChange={(event) => setField('odoo_api_key', event.target.value)}
          />
          <Input
            label="Timeout Odoo (detik)"
            type="number"
            value={values.odoo_timeout}
            onChange={(event) => setField('odoo_timeout', event.target.value)}
            {...(showErrors && errors.odoo_timeout !== undefined
              ? { error: errors.odoo_timeout }
              : {})}
          />
          <div className="md:col-span-2">
            <Checkbox
              label="Profil aktif (referensi konfigurasi klien)"
              checked={values.active}
              onCheckedChange={(checked) => setField('active', checked)}
            />
          </div>
          <p className="text-xs text-muted-foreground md:col-span-2">
            {isMaskedApiKey(values.odoo_api_key)
              ? 'API key tersimpan (ditampilkan sebagai ***) — biarkan apa adanya agar tidak berubah.'
              : 'Isi kunci baru untuk mengganti, atau kosongkan lalu Simpan untuk menghapus.'}
          </p>
        </section>

        <section className={cn(CARD, 'grid grid-cols-1 gap-4 md:grid-cols-2')}>
          <h2 className="text-sm font-medium text-foreground md:col-span-2">
            Lokasi Odoo
          </h2>
          {LOCATION_FIELDS.map(({ field, label }) => (
            <Input
              key={field}
              label={label}
              type="number"
              value={values[field]}
              onChange={(event) => setField(field, event.target.value)}
              {...(showErrors && errors[field] !== undefined ? { error: errors[field] } : {})}
            />
          ))}
        </section>

        <section className={cn(CARD, 'grid grid-cols-1 gap-4 md:grid-cols-2')}>
          <h2 className="text-sm font-medium text-foreground md:col-span-2">Advanced</h2>
          {ADVANCED_FIELDS.map(({ field, label }) => (
            <Input
              key={field}
              label={label}
              type="number"
              value={values[field]}
              onChange={(event) => setField(field, event.target.value)}
              {...(showErrors && errors[field] !== undefined ? { error: errors[field] } : {})}
            />
          ))}
        </section>

        <section className={cn(CARD, 'grid grid-cols-1 gap-4 md:grid-cols-2')}>
          <h2 className="text-sm font-medium text-foreground md:col-span-2">
            Rekonsiliasi stok + alert
          </h2>
          <Input
            label="Toleransi unit (absolut)"
            type="number"
            value={values.reconciliation_tolerance_units}
            onChange={(event) => setField('reconciliation_tolerance_units', event.target.value)}
            {...(showErrors && errors.reconciliation_tolerance_units !== undefined
              ? { error: errors.reconciliation_tolerance_units }
              : {})}
          />
          <Input
            label={`Toleransi rasio (0..${String(MAX_TOLERANCE_PCT)})`}
            type="number"
            value={values.reconciliation_tolerance_pct}
            onChange={(event) => setField('reconciliation_tolerance_pct', event.target.value)}
            {...(showErrors && errors.reconciliation_tolerance_pct !== undefined
              ? { error: errors.reconciliation_tolerance_pct }
              : {})}
          />
          <div className="md:col-span-2">
            <Input
              label="Penerima alert WA (dipisah koma)"
              value={values.reconciliation_alert_wa_to}
              placeholder={`mis. 628123456789,628987654321 (maks ${String(MAX_WA_LENGTH)} karakter/nomor)`}
              onChange={(event) => setField('reconciliation_alert_wa_to', event.target.value)}
              {...(showErrors && errors.reconciliation_alert_wa_to !== undefined
                ? { error: errors.reconciliation_alert_wa_to }
                : {})}
            />
          </div>
          <div className="flex flex-wrap items-center justify-between gap-3 md:col-span-2">
            <p className="text-xs text-muted-foreground">
              MES-only: profil ini tidak dikirim ke Odoo — setiap tulis tercatat sebagai
              ledger SKIPPED.
            </p>
            <div className="flex flex-wrap items-center gap-2">
              <Button type="submit" icon={Save} loading={save.isPending}>
                Simpan Profil
              </Button>
            </div>
          </div>
        </section>
      </form>

      <section className={cn(CARD, 'flex flex-col gap-3 p-4')}>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-col gap-1">
            <h2 className="text-sm font-medium text-foreground">
              Status konfigurasi aktif (.env)
            </h2>
            <p className="text-xs text-muted-foreground">
              Nilai berikut dibaca dari .env saat proses start — bukan dari profil di atas.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {envelope === null ? null : envelope.needs_restart ? (
              <Badge tone="coral">Perlu restart</Badge>
            ) : (
              <Badge tone="blue">Selaras</Badge>
            )}
            <Button
              variant="secondary"
              icon={Activity}
              loading={test.isPending}
              onClick={() => test.mutate()}
            >
              Test Koneksi
            </Button>
          </div>
        </div>

        {envelope !== null && envelope.needs_restart ? (
          <div className="flex flex-col gap-1">
            <p className="text-sm text-muted-foreground">
              Profil berbeda dari .env — salin nilainya ke .env lalu jalankan:
            </p>
            <p className="font-mono text-xs tabular-nums">{envelope.restart_command}</p>
          </div>
        ) : null}

        {testResult !== null ? (
          <div className="flex flex-col gap-1">
            <div className="flex items-center gap-2">
              <Badge tone={testResult.ok ? 'blue' : 'muted'}>
                {testResult.ok ? 'Koneksi OK' : 'Koneksi gagal'}
              </Badge>
              {testResult.server_version === null ? null : (
                <span className="text-xs text-muted-foreground">
                  Odoo {testResult.server_version}
                </span>
              )}
            </div>
            <p className="text-sm text-muted-foreground">{testResult.message}</p>
          </div>
        ) : null}

        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          {statusRows.map((row) => (
            <div key={row.field} className="flex flex-col gap-1">
              <span className="text-xs text-muted-foreground">{row.label}</span>
              <span className="font-mono text-sm tabular-nums">{row.value}</span>
            </div>
          ))}
        </div>

        {divergenceRows.length === 0 ? null : (
          <div className="flex flex-col gap-2">
            <h3 className="text-sm font-medium text-foreground">
              Beda profil vs .env ({String(divergenceRows.length)} field)
            </h3>
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              {divergenceRows.map((row) => (
                <div key={row.field} className="flex flex-col gap-1">
                  <span className="text-xs text-muted-foreground">{row.label}</span>
                  <span className="font-mono text-sm tabular-nums">
                    profil {row.db} · .env {row.env}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
      </section>

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
