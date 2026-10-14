import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { RefreshCw } from 'lucide-react';
import { Badge } from '@/components/atoms/Badge';
import { Button } from '@/components/atoms/Button';
import { Input } from '@/components/atoms/Input';
import { Toast, type ToastTone } from '@/components/atoms/Toast';
import { DenseTable, type DenseTableColumn } from '@/components/molecules/DenseTable';
import { PageHeader } from '@/components/molecules/PageHeader';
import {
  getReconciliationReport,
  parseReconciliationDays,
  RECONCILIATION_DAYS_DEFAULT,
  RECONCILIATION_DAYS_MAX,
  RECONCILIATION_DAYS_MIN,
  type ReconciliationEntry,
} from '@/api/reconciliation';
import { useFeedback } from '@/app/app-runtime';
import { useApiClient } from '@/hooks/useApiClient';
import { cn } from '@/lib/cn';
import { CARD } from '@/lib/tokens';

/**
 * ReconciliationReportPage - route `/reports/reconciliation` (F9/9.1).
 *
 * Riwayat rekonsiliasi stok MES vs Odoo (kontrak §6.2, `GET /reconciliation/report/?days=N`).
 * `days` dikunci 1..90 oleh BACKEND (di luar itu 400) — input di sini divalidasi lebih dulu
 * (`parseReconciliationDays`) supaya request tidak pernah dikirim saat nilainya jelas salah.
 * `IsAuthenticated` → tanpa session backend membalas 403; halaman menampilkan pesan (tidak blank).
 *
 * Tabel memakai `DenseTable` (Fase 20) — tidak ada tabel paralel. Endpoint ini READ-ONLY dan
 * tidak menyentuh Odoo (trigger rekonsiliasi = Celery beat mingguan).
 */

/** Baris tabel = entri + `id` turunan (`run_at` + odoo_id + posisi) karena backend tidak mengirim id. */
interface ReconciliationRow extends ReconciliationEntry {
  id: string;
}

interface ToastState {
  tone: ToastTone;
  title: string;
  description: string;
}

function formatQty(value: number | null): string {
  return value === null ? '-' : value.toLocaleString('id-ID');
}

function toRows(entries: readonly ReconciliationEntry[]): ReconciliationRow[] {
  return entries.map((entry, index) => ({
    ...entry,
    id: `${entry.run_at ?? '-'}#${String(entry.product_odoo_id ?? '-')}#${String(index)}`,
  }));
}

const COLUMNS: DenseTableColumn<ReconciliationRow>[] = [
  { key: 'run_at', label: 'Waktu', render: (row) => row.run_at ?? '-' },
  {
    key: 'product_code',
    label: 'Produk',
    render: (row) => <span className="font-mono text-xs">{row.product_code ?? '-'}</span>,
  },
  {
    key: 'product_odoo_id',
    label: 'Odoo ID',
    align: 'right',
    render: (row) => formatQty(row.product_odoo_id),
  },
  { key: 'mes_qty', label: 'MES', align: 'right', render: (row) => formatQty(row.mes_qty) },
  { key: 'odoo_qty', label: 'Odoo', align: 'right', render: (row) => formatQty(row.odoo_qty) },
  { key: 'diff', label: 'Selisih', align: 'right', render: (row) => formatQty(row.diff) },
  {
    key: 'is_alert',
    label: 'Status',
    render: (row) => (
      <Badge tone={row.is_alert ? 'coral' : 'muted'}>
        {row.is_alert ? 'Di luar toleransi' : 'Aman'}
      </Badge>
    ),
  },
  { key: 'notes', label: 'Catatan', render: (row) => row.notes ?? '-' },
];

export function ReconciliationReportPage() {
  const apiClient = useApiClient();
  const { trigger } = useFeedback();

  const [daysInput, setDaysInput] = useState(String(RECONCILIATION_DAYS_DEFAULT));
  const [toast, setToast] = useState<ToastState | null>(null);

  const days = parseReconciliationDays(daysInput);
  const effectiveDays = days ?? RECONCILIATION_DAYS_DEFAULT;

  const report = useQuery({
    queryKey: ['reconciliation-report', effectiveDays],
    queryFn: () => getReconciliationReport(apiClient, effectiveDays),
    enabled: days !== null,
    staleTime: 30_000,
  });

  async function handleRefresh(): Promise<void> {
    const result = await report.refetch();

    if (result.error !== null && result.error !== undefined) {
      trigger('error');
      setToast({
        tone: 'error',
        title: 'Gagal memuat laporan',
        description:
          result.error instanceof Error
            ? result.error.message
            : 'Reconciliation report gagal dimuat.',
      });
      return;
    }

    trigger('success');
    setToast({
      tone: 'success',
      title: 'Laporan dimuat',
      description: `${String(result.data?.entries.length ?? 0)} baris rekonsiliasi (${String(effectiveDays)} hari terakhir).`,
    });
  }

  const entries = report.data?.entries ?? [];
  const alertCount = entries.filter((entry) => entry.is_alert).length;
  const queryError = report.error === null || report.error === undefined ? null : report.error;
  const loadError = queryError === null ? null : 'Gagal memuat rekonsiliasi (perlu login?).';

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <PageHeader
        title="Reconciliation Report"
        subtitle="Riwayat selisih stok MES vs Odoo (read-only, tanpa memanggil Odoo)"
        breadcrumb={[{ label: 'Reports' }, { label: 'Reconciliation' }]}
      />

      <section className={cn(CARD, 'flex flex-wrap items-end justify-between gap-3')}>
        <div className="flex flex-wrap items-end gap-3">
          <Input
            type="number"
            min={RECONCILIATION_DAYS_MIN}
            max={RECONCILIATION_DAYS_MAX}
            label={`Rentang hari (${String(RECONCILIATION_DAYS_MIN)}-${String(RECONCILIATION_DAYS_MAX)})`}
            value={daysInput}
            className="w-32"
            {...(days === null ? { error: 'Isi bilangan 1-90.' } : {})}
            onChange={(event) => {
              setDaysInput(event.target.value);
            }}
          />

          <div className="flex flex-col gap-0.5 pb-2">
            <span className="text-sm font-semibold text-foreground">
              {report.isLoading ? 'Memuat…' : `${String(entries.length)} baris`}
            </span>
            <span className="text-xs text-muted-foreground">
              {String(alertCount)} di luar toleransi
              {report.data === undefined ? '' : ` dari total ${String(report.data.count)} tercatat`}
            </span>
          </div>
        </div>

        <Button
          variant="secondary"
          icon={RefreshCw}
          loading={report.isFetching}
          disabled={days === null || report.isFetching}
          onClick={() => {
            void handleRefresh();
          }}
        >
          Muat Ulang
        </Button>
      </section>

      <section className={cn(CARD, 'p-0')}>
        <DenseTable
          columns={COLUMNS}
          rows={toRows(entries)}
          loading={report.isLoading}
          error={days === null ? 'Rentang hari tidak valid — isi bilangan 1-90.' : loadError}
          onRetry={() => {
            void report.refetch();
          }}
          emptyMessage={`Belum ada rekonsiliasi pada ${String(effectiveDays)} hari terakhir.`}
        />
      </section>

      <Toast
        open={toast !== null}
        onOpenChange={(open) => {
          if (!open) setToast(null);
        }}
        tone={toast?.tone ?? 'default'}
        title={toast?.title ?? ''}
        description={toast?.description}
      />
    </div>
  );
}
