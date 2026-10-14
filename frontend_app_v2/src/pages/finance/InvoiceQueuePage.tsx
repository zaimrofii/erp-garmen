import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { RefreshCw } from 'lucide-react';
import { Badge } from '@/components/atoms/Badge';
import { Button } from '@/components/atoms/Button';
import { Input } from '@/components/atoms/Input';
import { Select, type SelectOption } from '@/components/atoms/Select';
import { Toast, type ToastTone } from '@/components/atoms/Toast';
import { DenseTable, type DenseTableColumn } from '@/components/molecules/DenseTable';
import { PageHeader } from '@/components/molecules/PageHeader';
import {
  getInvoices,
  INVOICE_LIMIT_DEFAULT,
  INVOICE_LIMIT_MAX,
  INVOICE_STATUSES,
  parseIntParam,
  type InvoiceRow,
} from '@/api/invoice';
import { useFeedback } from '@/app/app-runtime';
import { useApiClient } from '@/hooks/useApiClient';
import { cn } from '@/lib/cn';
import { syncStatusLabel, syncStatusTone } from '@/lib/state-display';
import { CARD } from '@/lib/tokens';

/**
 * InvoiceQueuePage - route `/finance/invoices` (F15, revive F10).
 *
 * Antrean invoice = `SyncRecord(resource="order", stage="INVOICE")` + `Order` (Fase 4.4,
 * `GET /finance/invoices/`) — READ-ONLY, `IsAuthenticated` (anon 403). Filter satu-satunya
 * yang didukung backend: `state` = **status sync** (`PENDING|SENT|FAILED|DUPLICATE`);
 * repo TIDAK menyimpan state invoice Odoo (`draft|posted`) maupun partner/amount/date,
 * jadi kolom tabel memakai field NYATA (lihat `api/real/invoice.ts`).
 *
 * Paging pakai `limit` + `cursor` (offset); `limit` divalidasi 1..200 di klien supaya
 * request jelas-salah tidak pernah dikirim (backend membalas 400 untuk param invalid).
 */

/** Baris tabel = `InvoiceRow` + `id` stabil (`order_id` boleh `null` → pakai posisi). */
interface InvoiceTableRow extends InvoiceRow {
  id: string;
}

interface ToastState {
  tone: ToastTone;
  title: string;
  description: string;
}

const STATUS_OPTIONS: SelectOption[] = [
  { value: '', label: 'Semua status' },
  ...INVOICE_STATUSES.map((status) => ({ value: status, label: syncStatusLabel(status) })),
];

const COLUMNS: DenseTableColumn<InvoiceTableRow>[] = [
  {
    key: 'order_no',
    label: 'Order',
    render: (row) => (
      <span className="font-mono text-xs">{row.order_no ?? `#${String(row.order_id ?? '-')}`}</span>
    ),
  },
  {
    key: 'invoice_status',
    label: 'Status Sync',
    render: (row) => (
      <Badge tone={syncStatusTone(row.invoice_status)}>
        {syncStatusLabel(row.invoice_status)}
      </Badge>
    ),
  },
  { key: 'erp_id', label: 'ERP ID', render: (row) => row.erp_id ?? '-' },
  { key: 'attempts', label: 'Percobaan', align: 'right' },
  { key: 'last_error', label: 'Error terakhir', render: (row) => row.last_error ?? '-' },
  { key: 'sent_at', label: 'Dikirim', render: (row) => row.sent_at ?? '-' },
  { key: 'created_at', label: 'Dibuat', render: (row) => row.created_at ?? '-' },
];

function toRows(rows: readonly InvoiceRow[]): InvoiceTableRow[] {
  return rows.map((row, index) => ({
    ...row,
    id: `${String(row.order_id ?? 'x')}#${String(row.erp_id ?? '-')}#${String(index)}`,
  }));
}

export function InvoiceQueuePage() {
  const apiClient = useApiClient();
  const { trigger } = useFeedback();

  const [status, setStatus] = useState('');
  const [limitInput, setLimitInput] = useState(String(INVOICE_LIMIT_DEFAULT));
  const [toast, setToast] = useState<ToastState | null>(null);

  const limit = parseIntParam(limitInput, 1, INVOICE_LIMIT_MAX) ?? INVOICE_LIMIT_DEFAULT;

  const invoices = useQuery({
    queryKey: ['invoice-queue', status, limit],
    queryFn: () => getInvoices(apiClient, { state: status, limit }),
    staleTime: 30_000,
  });

  async function handleRefresh(): Promise<void> {
    const result = await invoices.refetch();

    if (result.error !== null && result.error !== undefined) {
      trigger('error');
      setToast({
        tone: 'error',
        title: 'Gagal memuat antrean invoice',
        description:
          result.error instanceof Error ? result.error.message : 'Antrean invoice gagal dimuat.',
      });
      return;
    }

    trigger('success');
    setToast({
      tone: 'success',
      title: 'Antrean invoice dimuat',
      description: `${String(result.data?.rows.length ?? 0)} baris (total ${String(result.data?.total_count ?? 0)}).`,
    });
  }

  const rows = invoices.data?.rows ?? [];
  const limitInvalid = parseIntParam(limitInput, 1, INVOICE_LIMIT_MAX) === null;
  const queryError = invoices.error === null || invoices.error === undefined ? null : invoices.error;
  const loadError = queryError === null ? null : 'Gagal memuat antrean invoice (perlu login?).';

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <PageHeader
        title="Antrean Invoice"
        subtitle="Status sync invoice MES → Odoo (read-only; satu Order = satu invoice)"
        breadcrumb={[{ label: 'Finance' }, { label: 'Invoices' }]}
      />

      <section className={cn(CARD, 'flex flex-wrap items-end justify-between gap-3')}>
        <div className="flex flex-wrap items-end gap-3">
          <Select
            label="Status sync"
            options={STATUS_OPTIONS}
            value={status}
            className="w-40"
            onChange={(event) => {
              setStatus(event.target.value);
            }}
          />
          <Input
            type="number"
            min={1}
            max={INVOICE_LIMIT_MAX}
            label={`Baris per halaman (1-${String(INVOICE_LIMIT_MAX)})`}
            value={limitInput}
            className="w-40"
            {...(limitInvalid ? { error: `Isi bilangan 1-${String(INVOICE_LIMIT_MAX)}.` } : {})}
            onChange={(event) => {
              setLimitInput(event.target.value);
            }}
          />

          <div className="flex flex-col gap-0.5 pb-2">
            <span className="text-sm font-semibold text-foreground">
              {invoices.isLoading ? 'Memuat…' : `${String(rows.length)} baris`}
            </span>
            <span className="text-xs text-muted-foreground">
              {invoices.data === undefined
                ? 'menunggu backend'
                : `total ${String(invoices.data.total_count)}${invoices.data.has_next ? ' · ada halaman berikutnya' : ''}`}
            </span>
          </div>
        </div>

        <Button
          variant="secondary"
          icon={RefreshCw}
          loading={invoices.isFetching}
          disabled={invoices.isFetching}
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
          rows={toRows(rows)}
          loading={invoices.isLoading}
          error={loadError}
          onRetry={() => {
            void invoices.refetch();
          }}
          emptyMessage="Belum ada invoice pada filter ini."
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

