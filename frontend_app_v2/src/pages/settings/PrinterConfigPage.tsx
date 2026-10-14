import { useMemo, useState, type FormEvent } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Activity, Printer, RefreshCw, Save } from 'lucide-react';
import { Badge } from '@/components/atoms/Badge';
import { Button } from '@/components/atoms/Button';
import { Checkbox } from '@/components/atoms/Checkbox';
import { Input } from '@/components/atoms/Input';
import { Select } from '@/components/atoms/Select';
import { Spinner } from '@/components/atoms/Spinner';
import { Toast, type ToastTone } from '@/components/atoms/Toast';
import { PageHeader } from '@/components/molecules/PageHeader';
import {
  fetchPrinterConfig,
  testPrinterConnection,
  updatePrinterConfig,
} from '@/api/printerConfig';
import { useFeedback } from '@/app/app-runtime';
import { useApiClient } from '@/hooks/useApiClient';
import { cn } from '@/lib/cn';
import {
  BACKEND_OPTIONS,
  CONFIG_FIELD_LABELS,
  effectiveStatusRows,
  formatConfigValue,
  isPrinterConfigFormValid,
  printerConfigFormFromRow,
  printerConfigInputFromForm,
  validatePrinterConfigForm,
  visibleFieldGroups,
  type PrinterConfigFormValues,
} from '@/lib/printer-config';
import { CARD } from '@/lib/tokens';
import {
  PRINTER_PORT_MAX,
  PRINTER_PORT_MIN,
  type PrinterConfigEnvelope,
  type PrinterTestConnectionResult,
} from '@/types/printer-config';

/**
 * PrinterConfigPage - route `/settings/printers` (H5.7, khusus admin).
 *
 * **SINGLETON + Opsi B** (pola H5.6/H5.8): halaman ini menyimpan *profil printer* ke DB
 * (ber-jejak), **tetapi TIDAK meng-override `.env`** — konsumen
 * (`integrations/printing.backends.get_backend()` → `POST /api/v1/print/bundle-tag/`
 * & `/print/kupon/`) tetap membaca `.env`. Aktivasi = salin nilai ke `.env` lalu restart
 * `django`/`celery_worker`/`celery_beat` (perintahnya datang dari backend:
 * `restart_command`).
 *
 * Tiga blok field **kondisional** (mengikuti backend yang dipilih):
 *   1. **USB** (backend `usb`) — vendor id + product id (wajib);
 *   2. **Network** (backend `network`) — host + port 1..65535 (wajib);
 *   3. **Mock** (backend `mock`) — folder hasil cetak (opsional).
 *
 * Bagian **Status** (read-only): `effective` (nilai `.env` yang aktif), `diverges`,
 * `needs_restart`, tombol **Test Koneksi** (read-only; **tidak pernah mencetak** — hanya
 * TCP connect / cek folder), dan instruksi restart.
 *
 * ⚠️ Tanpa mask: host/port/USB id bukan kredensial (beda H5.6/H5.8).
 * Guard route: `SETTINGS_ROLES` (pola `/settings/integration`, `/settings/wa`).
 */

const QUERY_KEY = 'settings-printer';

interface ToastState {
  tone: ToastTone;
  title: string;
  description: string;
}

export function PrinterConfigPage() {
  const client = useApiClient();
  const queryClient = useQueryClient();
  const { trigger } = useFeedback();

  const [draft, setDraft] = useState<PrinterConfigFormValues | null>(null);
  const [submitted, setSubmitted] = useState(false);
  const [toast, setToast] = useState<ToastState | null>(null);
  const [testResult, setTestResult] = useState<PrinterTestConnectionResult | null>(null);

  const detail = useQuery({
    queryKey: [QUERY_KEY],
    queryFn: () => fetchPrinterConfig(client),
    staleTime: 15_000,
  });

  const envelope: PrinterConfigEnvelope | null = detail.data ?? null;

  /** Nilai form = draft pengguna → data GET → form kosong (tanpa effect). */
  const values: PrinterConfigFormValues =
    draft ?? printerConfigFormFromRow(envelope?.config ?? null);

  const errors = useMemo(() => validatePrinterConfigForm(values), [values]);
  const valid = isPrinterConfigFormValid(errors);
  const groups = visibleFieldGroups(values.printer_backend);

  const save = useMutation({
    mutationFn: () => updatePrinterConfig(client, printerConfigInputFromForm(values)),
    onSuccess: (saved) => {
      trigger('success');
      setToast({
        tone: 'success',
        title: 'Profil printer disimpan',
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
        title: 'Gagal menyimpan profil printer',
        description: caught instanceof Error ? caught.message : 'Permintaan simpan gagal.',
      });
    },
  });

  const test = useMutation({
    mutationFn: () => testPrinterConnection(client),
    onSuccess: (result) => {
      trigger(result.ok ? 'success' : 'error');
      setTestResult(result);
    },
    onError: (caught) => {
      trigger('error');
      setToast({
        tone: 'error',
        title: 'Gagal menguji printer',
        description: caught instanceof Error ? caught.message : 'Permintaan uji gagal.',
      });
    },
  });

  function setField<K extends keyof PrinterConfigFormValues>(
    field: K,
    value: PrinterConfigFormValues[K],
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

  /** Baris printer efektif (`.env` yang benar-benar aktif) untuk bagian Status. */
  const statusRows = useMemo(
    () => (envelope === null ? [] : effectiveStatusRows(envelope.effective)),
    [envelope],
  );

  /** Hanya field yang benar-benar beda (DB vs `.env`) — tanpa mask. */
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
        title="Printer"
        subtitle="Profil printer thermal ESC/POS — disimpan di MES; aktivasi lewat .env + restart worker"
        breadcrumb={[{ label: 'Settings' }, { label: 'Printer' }]}
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
          <Spinner size="sm" /> Memuat konfigurasi printer…
        </div>
      ) : null}

      {detail.error !== null ? (
        <section className={cn(CARD, 'flex flex-col gap-2')}>
          <p role="alert" className="text-sm font-medium text-accent-coral">
            Gagal memuat konfigurasi printer.
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
          <h2 className="flex items-center gap-2 text-sm font-medium text-foreground md:col-span-2">
            <Printer className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
            Printer (backend + kredensial)
          </h2>
          <Select
            label="Backend printer"
            options={BACKEND_OPTIONS}
            value={values.printer_backend}
            onChange={(event) => setField('printer_backend', event.target.value)}
            {...(showErrors && errors.printer_backend !== undefined
              ? { error: errors.printer_backend }
              : {})}
          />
          <div className="flex items-end pb-2">
            <Checkbox
              label="Profil aktif (referensi printer)"
              checked={values.active}
              onCheckedChange={(checked) => setField('active', checked)}
            />
          </div>
          <p className="text-xs text-muted-foreground md:col-span-2">
            {groups.usb
              ? 'Backend USB masih stub (butuh python-escpos + libusb) — vendor/product tetap dicatat sebagai referensi.'
              : groups.network
                ? `Backend network mengirim bytes ESC/POS via TCP raw ke host:port (${String(PRINTER_PORT_MIN)}..${String(PRINTER_PORT_MAX)}).`
                : 'Backend mock menulis hasil cetak ke file .bin di folder mock — tanpa printer fisik.'}
          </p>
        </section>

        {groups.usb ? (
          <section className={cn(CARD, 'grid grid-cols-1 gap-4 md:grid-cols-2')}>
            <h2 className="text-sm font-medium text-foreground md:col-span-2">
              USB (wajib untuk backend usb)
            </h2>
            <Input
              label="USB vendor id"
              value={values.printer_usb_vendor_id}
              placeholder="mis. 0x04b8"
              onChange={(event) => setField('printer_usb_vendor_id', event.target.value)}
              {...(showErrors && errors.printer_usb_vendor_id !== undefined
                ? { error: errors.printer_usb_vendor_id }
                : {})}
            />
            <Input
              label="USB product id"
              value={values.printer_usb_product_id}
              placeholder="mis. 0x0202"
              onChange={(event) => setField('printer_usb_product_id', event.target.value)}
              {...(showErrors && errors.printer_usb_product_id !== undefined
                ? { error: errors.printer_usb_product_id }
                : {})}
            />
          </section>
        ) : null}

        {groups.network ? (
          <section className={cn(CARD, 'grid grid-cols-1 gap-4 md:grid-cols-2')}>
            <h2 className="text-sm font-medium text-foreground md:col-span-2">
              Network (wajib untuk backend network)
            </h2>
            <Input
              label="Host printer"
              value={values.printer_network_host}
              placeholder="mis. 192.168.1.50"
              onChange={(event) => setField('printer_network_host', event.target.value)}
              {...(showErrors && errors.printer_network_host !== undefined
                ? { error: errors.printer_network_host }
                : {})}
            />
            <Input
              label={`Port printer (${String(PRINTER_PORT_MIN)}..${String(PRINTER_PORT_MAX)})`}
              type="number"
              value={values.printer_network_port}
              placeholder="mis. 9100"
              onChange={(event) => setField('printer_network_port', event.target.value)}
              {...(showErrors && errors.printer_network_port !== undefined
                ? { error: errors.printer_network_port }
                : {})}
            />
          </section>
        ) : null}

        {groups.mock ? (
          <section className={cn(CARD, 'grid grid-cols-1 gap-4')}>
            <h2 className="text-sm font-medium text-foreground">
              Mock (opsional untuk backend mock)
            </h2>
            <Input
              label="Folder hasil cetak"
              value={values.printer_mock_dir}
              placeholder="kosong = default server (/tmp/print_mock)"
              onChange={(event) => setField('printer_mock_dir', event.target.value)}
              {...(showErrors && errors.printer_mock_dir !== undefined
                ? { error: errors.printer_mock_dir }
                : {})}
            />
          </section>
        ) : null}

        <section className={cn(CARD, 'flex flex-wrap items-center justify-between gap-3')}>
          <p className="text-xs text-muted-foreground">
            MES-only: profil ini tidak dikirim ke Odoo/printer — setiap tulis tercatat sebagai
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
              Status printer aktif (.env)
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
                {testResult.ok ? 'Printer OK' : 'Printer belum siap'}
              </Badge>
              <span className="text-xs text-muted-foreground">backend {testResult.backend}</span>
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

