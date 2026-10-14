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
import { fetchWAConfig, testWAConnection, updateWAConfig } from '@/api/waConfig';
import { useFeedback } from '@/app/app-runtime';
import { useApiClient } from '@/hooks/useApiClient';
import { cn } from '@/lib/cn';
import {
  BACKEND_OPTIONS,
  CONFIG_FIELD_LABELS,
  effectiveStatusRows,
  formatConfigValue,
  isMaskedApiKey,
  isWAConfigFormValid,
  validateWAConfigForm,
  waConfigFormFromRow,
  waConfigInputFromForm,
  type WAConfigFormValues,
} from '@/lib/wa-config';
import { CARD } from '@/lib/tokens';
import type { WAConfigEnvelope, WATestConnectionResult } from '@/types/wa-config';

/**
 * WAConfigPage - route `/settings/wa` (H5.8, khusus admin).
 *
 * **SINGLETON + Opsi B** (pola H5.6): halaman ini menyimpan *profil gateway* WhatsApp
 * ke DB (ber-jejak), **tetapi TIDAK meng-override `.env`** — konsumen
 * (`integrations/wa_bot/services.get_wa_gateway` → `POST /api/v1/wa/send/`,
 * `tasks_reconciliation.py`, `ai/hitl_views.py`) tetap membaca `.env`. Aktivasi = salin
 * nilai ke `.env` lalu restart `django`/`celery_worker`/`celery_beat` (perintahnya
 * datang dari backend: `restart_command`).
 *
 * Dua bagian:
 *   1. **Gateway WA** — backend (`mock`/`real`/`api`), URL API, API key (masked), aktif;
 *   2. **Status** (read-only) — `effective` (nilai `.env` yang aktif), `diverges`
 *      (field yang beda), `needs_restart`, tombol **Test Koneksi** (POST read-only,
 *      tidak mengirim pesan), dan instruksi restart.
 *
 * API key: backend **selalu** mengembalikan `***`; kirim `***` = jangan ubah,
 * kosongkan field (di luar mask) = hapus.
 *
 * Guard route: `SETTINGS_ROLES` (pola `/settings/company`, `/settings/integration`).
 */

const QUERY_KEY = 'settings-wa';

interface ToastState {
  tone: ToastTone;
  title: string;
  description: string;
}

export function WAConfigPage() {
  const client = useApiClient();
  const queryClient = useQueryClient();
  const { trigger } = useFeedback();

  const [draft, setDraft] = useState<WAConfigFormValues | null>(null);
  const [submitted, setSubmitted] = useState(false);
  const [toast, setToast] = useState<ToastState | null>(null);
  const [testResult, setTestResult] = useState<WATestConnectionResult | null>(null);

  const detail = useQuery({
    queryKey: [QUERY_KEY],
    queryFn: () => fetchWAConfig(client),
    staleTime: 15_000,
  });

  const envelope: WAConfigEnvelope | null = detail.data ?? null;

  /** Nilai form = draft pengguna → data GET → form kosong (tanpa effect). */
  const values: WAConfigFormValues = draft ?? waConfigFormFromRow(envelope?.config ?? null);

  const errors = useMemo(() => validateWAConfigForm(values), [values]);
  const valid = isWAConfigFormValid(errors);

  const save = useMutation({
    mutationFn: () => updateWAConfig(client, waConfigInputFromForm(values)),
    onSuccess: (saved) => {
      trigger('success');
      setToast({
        tone: 'success',
        title: 'Profil gateway WA disimpan',
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
        title: 'Gagal menyimpan profil gateway',
        description: caught instanceof Error ? caught.message : 'Permintaan simpan gagal.',
      });
    },
  });

  const test = useMutation({
    mutationFn: () => testWAConnection(client),
    onSuccess: (result) => {
      trigger(result.ok ? 'success' : 'error');
      setTestResult(result);
    },
    onError: (caught) => {
      trigger('error');
      setToast({
        tone: 'error',
        title: 'Gagal menguji gateway WA',
        description: caught instanceof Error ? caught.message : 'Permintaan uji gagal.',
      });
    },
  });

  function setField<K extends keyof WAConfigFormValues>(
    field: K,
    value: WAConfigFormValues[K],
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

  /** Baris gateway efektif (`.env` yang benar-benar aktif) untuk bagian Status. */
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
        title="WA Gateway"
        subtitle="Profil gateway WhatsApp — disimpan di MES; aktivasi lewat .env + restart worker"
        breadcrumb={[{ label: 'Settings' }, { label: 'WA Gateway' }]}
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
          <Spinner size="sm" /> Memuat konfigurasi WA…
        </div>
      ) : null}

      {detail.error !== null ? (
        <section className={cn(CARD, 'flex flex-col gap-2')}>
          <p role="alert" className="text-sm font-medium text-accent-coral">
            Gagal memuat konfigurasi WA.
          </p>
        </section>
      ) : null}

      {envelope !== null && envelope.config === null ? (
        <p className="text-xs text-muted-foreground">
          Profil belum diisi — pilih backend lalu klik Simpan Profil (baris dibuat otomatis;
          PUT pertama = create).
        </p>
      ) : null}

      <form className="flex flex-col gap-4" onSubmit={handleSubmit}>
        <section className={cn(CARD, 'grid grid-cols-1 gap-4 md:grid-cols-2')}>
          <h2 className="text-sm font-medium text-foreground md:col-span-2">
            WA Gateway (backend + kredensial)
          </h2>
          <Select
            label="Backend WA"
            options={BACKEND_OPTIONS}
            value={values.wa_backend}
            onChange={(event) => setField('wa_backend', event.target.value)}
            {...(showErrors && errors.wa_backend !== undefined
              ? { error: errors.wa_backend }
              : {})}
          />
          <Input
            label="URL API WA"
            value={values.wa_api_url}
            placeholder="mis. http://wa-gateway:8080"
            onChange={(event) => setField('wa_api_url', event.target.value)}
            {...(showErrors && errors.wa_api_url !== undefined
              ? { error: errors.wa_api_url }
              : {})}
          />
          <Input
            label="API key WA"
            type="password"
            value={values.wa_api_key}
            placeholder="*** = pertahankan kunci tersimpan"
            onChange={(event) => setField('wa_api_key', event.target.value)}
            {...(showErrors && errors.wa_api_key !== undefined
              ? { error: errors.wa_api_key }
              : {})}
          />
          <div className="md:col-span-2">
            <Checkbox
              label="Profil aktif (referensi gateway)"
              checked={values.active}
              onCheckedChange={(checked) => setField('active', checked)}
            />
          </div>
          <p className="text-xs text-muted-foreground md:col-span-2">
            {isMaskedApiKey(values.wa_api_key)
              ? 'API key tersimpan (ditampilkan sebagai ***) — biarkan apa adanya agar tidak berubah.'
              : 'Isi kunci baru untuk mengganti, atau kosongkan lalu Simpan untuk menghapus.'}
          </p>
        </section>

        <section className={cn(CARD, 'flex flex-wrap items-center justify-between gap-3')}>
          <p className="text-xs text-muted-foreground">
            MES-only: profil ini tidak dikirim ke vendor WA — setiap tulis tercatat sebagai
            ledger SKIPPED.
          </p>
          <Button type="submit" icon={Save} loading={save.isPending}>
            Simpan Profil
          </Button>
        </section>
      </form>

      <section className={cn(CARD, 'flex flex-col gap-3 p-4')}>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-col gap-1">
            <h2 className="text-sm font-medium text-foreground">
              Status gateway aktif (.env)
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
                {testResult.ok ? 'Gateway OK' : 'Gateway gagal'}
              </Badge>
              {testResult.mock ? (
                <span className="text-xs text-muted-foreground">
                  backend {testResult.backend}
                </span>
              ) : (
                <span className="text-xs text-muted-foreground">
                  {testResult.backend}
                  {testResult.url === null ? '' : ` · ${testResult.url}`}
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

