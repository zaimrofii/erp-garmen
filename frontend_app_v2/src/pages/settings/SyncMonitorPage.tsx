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
  getSyncRecords,
  parseIntParam,
  SYNC_LIMIT_DEFAULT,
  SYNC_LIMIT_MAX,
  SYNC_STAGES,
  SYNC_STATUSES,
  type SyncRecordRow,
} from '@/api/syncMonitor';
import { useFeedback } from '@/app/app-runtime';
import { useApiClient } from '@/hooks/useApiClient';
import { cn } from '@/lib/cn';
import { syncStatusLabel, syncStatusTone } from '@/lib/state-display';
import { CARD } from '@/lib/tokens';

/**
 * SyncMonitorPage - route `/settings/sync` (F15, revive F10).
 *
 * Daftar `SyncRecord` apa pun (Fase 4.4, `GET /sync/records/`) — READ-ONLY,
 * `IsAuthenticated` (anon 403). Filter yang didukung backend: `stage`
 * (`WIP|FG|SCRAP|INVOICE`) dan `status` (`PENDING|SENT|FAILED|DUPLICATE`), keduanya
 * case-insensitive; paging `limit` (1..200) + `cursor` (offset).
 *
 * Kolom mengikuti field NYATA baris backend: `id, resource, resource_id, stage, status,
 * attempts, last_error, erp_id, sent_at, created_at` (urut terbaru dulu dari server).
 */

/** Baris tabel = `SyncRecordRow` (sudah punya `id` angka dari backend). */

interface ToastState {
  tone: ToastTone;
  title: string;
  description: string;
}

const STAGE_OPTIONS: SelectOption[] = [
  { value: '', label: 'Semua stage' },
  ...SYNC_STAGES.map((stage) => ({ value: stage, label: stage })),
];

const STATUS_OPTIONS: SelectOption[] = [
  { value: '', label: 'Semua status' },
  ...SYNC_STATUSES.map((status) => ({ value: status, label: syncStatusLabel(status) })),
];

const COLUMNS: DenseTableColumn<SyncRecordRow>[] = [
  { key: 'id', label: 'ID', align: 'right' },
  {
    key: 'resource',
    label: 'Resource',
    render: (row) => <span className="font-mono text-xs">{row.resource || '-'}</span>,
  },
  {
    key: 'resource_id',
    label: 'Resource ID',
    render: (row) => <span className="font-mono text-xs">{row.resource_id || '-'}</span>,
  },
  { key: 'stage', label: 'Stage', render: (row) => row.stage || '-' },
  {
    key: 'status',
    label: 'Status',
    render: (row) => (
      <Badge tone={syncStatusTone(row.status)}>{syncStatusLabel(row.status)}</Badge>
    ),
  },
  { key: 'attempts', label: 'Percobaan', align: 'right' },
  { key: 'last_error', label: 'Error terakhir', render: (row) => row.last_error ?? '-' },
  { key: 'erp_id', label: 'ERP ID', render: (row) => row.erp_id ?? '-' },
  { key: 'sent_at', label: 'Dikirim', render: (row) => row.sent_at ?? '-' },
  { key: 'created_at', label: 'Dibuat', render: (row) => row.created_at ?? '-' },
];

export function SyncMonitorPage() {
  const apiClient = useApiClient();
  const { trigger } = useFeedback();

  const [stage, setStage] = useState('');
  const [status, setStatus] = useState('');
  const [limitInput, setLimitInput] = useState(String(SYNC_LIMIT_DEFAULT));
  const [toast, setToast] = useState<ToastState | null>(null);

  const limit = parseIntParam(limitInput, 1, SYNC_LIMIT_MAX) ?? SYNC_LIMIT_DEFAULT;
  const limitInvalid = parseIntParam(limitInput, 1, SYNC_LIMIT_MAX) === null;

  const records = useQuery({
    queryKey: ['sync-records', stage, status, limit],
    queryFn: () => getSyncRecords(apiClient, { stage, status, limit }),
    staleTime: 15_000,
  });

  async function handleRefresh(): Promise<void> {
    const result = await records.refetch();

    if (result.error !== null && result.error !== undefined) {
      trigger('error');
      setToast({
        tone: 'error',
        title: 'Gagal memuat SyncRecord',
        description:
          result.error instanceof Error ? result.error.message : 'Daftar SyncRecord gagal dimuat.',
      });
      return;
    }

    trigger('success');
    setToast({
      tone: 'success',
      title: 'SyncRecord dimuat',
      description: `${String(result.data?.rows.length ?? 0)} baris (total ${String(result.data?.total_count ?? 0)}).`,
    });
  }

  const rows = records.data?.rows ?? [];
  const queryError = records.error === null || records.error === undefined ? null : records.error;
  const loadError = queryError === null ? null : 'Gagal memuat SyncRecord (perlu login?).';

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <PageHeader
        title="Sync Monitor"
        subtitle="Jejak sinkronisasi MES → ERP per record (read-only, Fase 4.4)"
        breadcrumb={[{ label: 'Settings' }, { label: 'Sync Monitor' }]}
      />

      <section className={cn(CARD, 'flex flex-wrap items-end justify-between gap-3')}>
        <div className="flex flex-wrap items-end gap-3">
          <Select
            label="Stage"
            options={STAGE_OPTIONS}
            value={stage}
            className="w-36"
            onChange={(event) => {
              setStage(event.target.value);
            }}
          />
          <Select
            label="Status"
            options={STATUS_OPTIONS}
            value={status}
            className="w-36"
            onChange={(event) => {
              setStatus(event.target.value);
            }}
          />
          <Input
            type="number"
            min={1}
            max={SYNC_LIMIT_MAX}
            label={`Baris per halaman (1-${String(SYNC_LIMIT_MAX)})`}
            value={limitInput}
            className="w-40"
            {...(limitInvalid ? { error: `Isi bilangan 1-${String(SYNC_LIMIT_MAX)}.` } : {})}
            onChange={(event) => {
              setLimitInput(event.target.value);
            }}
          />

          <div className="flex flex-col gap-0.5 pb-2">
            <span className="text-sm font-semibold text-foreground">
              {records.isLoading ? 'Memuat…' : `${String(rows.length)} baris`}
            </span>
            <span className="text-xs text-muted-foreground">
              {records.data === undefined
                ? 'menunggu backend'
                : `total ${String(records.data.total_count)}${records.data.has_next ? ' · ada halaman berikutnya' : ''}`}
            </span>
          </div>
        </div>

        <Button
          variant="secondary"
          icon={RefreshCw}
          loading={records.isFetching}
          disabled={records.isFetching}
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
          rows={rows}
          loading={records.isLoading}
          error={loadError}
          onRetry={() => {
            void records.refetch();
          }}
          emptyMessage="Belum ada SyncRecord pada filter ini."
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
