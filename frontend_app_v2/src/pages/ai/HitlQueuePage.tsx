import { useCallback, useMemo, useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { RefreshCw } from 'lucide-react';
import { Button } from '@/components/atoms/Button';
import { Modal } from '@/components/atoms/Modal';
import { Spinner } from '@/components/atoms/Spinner';
import {
  DenseTable,
  type DenseTableColumn,
} from '@/components/molecules/DenseTable';
import { PageHeader } from '@/components/molecules/PageHeader';
import { PaginationBar } from '@/components/molecules/PaginationBar';
import { approveHitl, fetchHitlQueue, rejectHitl } from '@/api/hitlQueue';
import { useApiClient } from '@/hooks/useApiClient';
import { cn } from '@/lib/cn';
import { BADGE, CARD } from '@/lib/tokens';
import type { HitlQueuePage, HitlQueueRow } from '@/types/hitl-queue';

/**
 * HitlQueuePage — `/ai/hitl` (S.3).
 *
 * Antrean persetujuan usulan aksi AI: filter status/risk, tabel, modal detail,
 * setujui/tolak (tolak wajib alasan), pagination. Semua aksi lewat endpoint
 * HITL backend — TIDAK ada eksekusi aksi dari UI.
 */

const PAGE_SIZE = 20;
const STATUS_OPTIONS = ['PENDING', 'APPROVED', 'REJECTED', 'EXPIRED', 'ALL'] as const;
const RISK_OPTIONS = ['', 'LOW', 'MEDIUM', 'HIGH'] as const;

const STATUS_CLASS: Record<string, string> = {
  PENDING: 'bg-warning/15 text-warning border border-warning/30',
  APPROVED: 'bg-success/15 text-success border border-success/30',
  REJECTED: 'bg-danger/15 text-danger border border-danger/30',
  EXPIRED: 'bg-muted text-muted-foreground',
};

function actionLabel(row: HitlQueueRow): string {
  return (
    row.proposed_action.actions?.[0]?.action ??
    row.proposed_action.problem ??
    row.query_text ??
    '-'
  );
}

function formatDate(value: string | null): string {
  return value ? value.slice(0, 16).replace('T', ' ') : '-';
}

export function HitlQueuePage({
  initialPage,
}: {
  initialPage?: HitlQueuePage;
} = {}) {
  const client = useApiClient();
  const [status, setStatus] = useState('PENDING');
  const [risk, setRisk] = useState('');
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<HitlQueueRow | null>(null);
  const [note, setNote] = useState('');
  const [reason, setReason] = useState('');

  const query = useQuery({
    queryKey: ['hitl-queue', status, risk, page],
    queryFn: () =>
      fetchHitlQueue(client, {
        status,
        risk: risk || undefined,
        limit: PAGE_SIZE,
        offset: (page - 1) * PAGE_SIZE,
      }),
    enabled: initialPage === undefined,
    staleTime: 30_000,
  });

  const data = initialPage ?? query.data;
  const rows = data?.rows ?? [];
  const total = data?.total_count ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  const closeModal = useCallback((): void => {
    setSelected(null);
    setNote('');
    setReason('');
  }, []);

  const handleOpenChange = useCallback(
    (open: boolean): void => {
      if (!open) closeModal();
    },
    [closeModal],
  );

  const approve = useMutation({
    mutationFn: (row: HitlQueueRow) => approveHitl(client, row.id, note),
    onSuccess: () => {
      closeModal();
      if (initialPage === undefined) void query.refetch();
    },
  });

  const reject = useMutation({
    mutationFn: (row: HitlQueueRow) => rejectHitl(client, row.id, reason),
    onSuccess: () => {
      closeModal();
      if (initialPage === undefined) void query.refetch();
    },
  });

  const columns: DenseTableColumn<HitlQueueRow>[] = useMemo(
    () => [
      { key: 'id', label: 'ID', align: 'right' },
      {
        key: 'created_at',
        label: 'Dibuat',
        render: (row) => formatDate(row.created_at),
      },
      { key: 'action', label: 'Aksi', render: actionLabel },
      { key: 'risk_level', label: 'Risiko' },
      {
        key: 'confidence_score',
        label: 'Confidence',
        align: 'right',
        render: (row) =>
          row.confidence_score === null ? '-' : row.confidence_score.toFixed(2),
      },
      {
        key: 'status',
        label: 'Status',
        render: (row) => (
          <span className={cn(BADGE, STATUS_CLASS[row.status] ?? STATUS_CLASS.EXPIRED)}>
            {row.status}
          </span>
        ),
      },
      {
        key: 'decided_by',
        label: 'Approver',
        render: (row) => row.decided_by ?? '-',
      },
    ],
    [],
  );

  if (data === undefined) {
    return (
      <div className="flex min-h-full flex-col gap-4 p-4 lg:p-6">
        <PageHeader
          title="Antrean Persetujuan AI"
          subtitle="Usulan aksi menunggu approval"
        />
        <div className={cn(CARD, 'flex items-center gap-2 text-sm text-muted-foreground')}>
          <Spinner size="sm" />
          {query.error === null
            ? 'Memuat antrean HITL...'
            : 'Gagal memuat antrean HITL.'}
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-full flex-col gap-4 p-4 lg:p-6">
      <PageHeader
        title="Antrean Persetujuan AI"
        subtitle="Usulan aksi AI — manusia yang menyetujui, AI tidak mengeksekusi"
        breadcrumb={[{ label: 'Asisten AI' }, { label: 'HITL' }]}
        actions={
          <Button
            variant="secondary"
            size="sm"
            icon={RefreshCw}
            onClick={() => {
              if (initialPage === undefined) void query.refetch();
            }}
          >
            Muat Ulang
          </Button>
        }
      />

      <section className={cn(CARD, 'grid grid-cols-2 gap-3 lg:grid-cols-4')}>
        <label className="flex flex-col gap-1 text-xs">
          <span className="text-muted-foreground">Status</span>
          <select
            aria-label="Filter status"
            className="min-h-10 rounded-lg border border-border/80 bg-card px-3 text-sm"
            value={status}
            onChange={(event) => {
              setStatus(event.target.value);
              setPage(1);
            }}
          >
            {STATUS_OPTIONS.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </label>

        <label className="flex flex-col gap-1 text-xs">
          <span className="text-muted-foreground">Risiko</span>
          <select
            aria-label="Filter risiko"
            className="min-h-10 rounded-lg border border-border/80 bg-card px-3 text-sm"
            value={risk}
            onChange={(event) => {
              setRisk(event.target.value);
              setPage(1);
            }}
          >
            {RISK_OPTIONS.map((option) => (
              <option key={option || 'ALL'} value={option}>
                {option || 'SEMUA'}
              </option>
            ))}
          </select>
        </label>
      </section>

      <section className={CARD}>
        <DenseTable
          columns={columns}
          rows={rows}
          loading={query.isLoading && initialPage === undefined}
          error={query.error instanceof Error ? query.error.message : null}
          onRetry={() => {
            if (initialPage === undefined) void query.refetch();
          }}
          onRowClick={(row) => {
            setSelected(row);
            setNote('');
            setReason('');
          }}
          emptyMessage="Tidak ada usulan aksi pada filter ini."
        />
        <PaginationBar
          page={page}
          totalPages={totalPages}
          rangeStart={total === 0 ? 0 : (page - 1) * PAGE_SIZE + 1}
          rangeEnd={Math.min(page * PAGE_SIZE, total)}
          total={total}
          canPrev={page > 1}
          canNext={page < totalPages}
          onPrev={() => {
            setPage((value) => Math.max(1, value - 1));
          }}
          onNext={() => {
            setPage((value) => Math.min(totalPages, value + 1));
          }}
        />
      </section>

      <Modal
        open={selected !== null}
        onOpenChange={handleOpenChange}
        title={selected === null ? 'Detail HITL' : `HITL #${selected.id}`}
        description="Periksa usulan aksi sebelum menyetujui atau menolak."
        footer={
          <div className="flex flex-wrap justify-end gap-2">
            <Button variant="secondary" size="sm" onClick={closeModal}>
              Tutup
            </Button>
            <Button
              variant="danger"
              size="sm"
              disabled={selected === null || reason.trim().length === 0 || reject.isPending}
              onClick={() => {
                if (selected !== null) reject.mutate(selected);
              }}
            >
              Tolak
            </Button>
            <Button
              size="sm"
              disabled={selected === null || approve.isPending}
              onClick={() => {
                if (selected !== null) approve.mutate(selected);
              }}
            >
              Setujui
            </Button>
          </div>
        }
      >
        {selected === null ? null : (
          <div className="flex flex-col gap-3 text-sm">
            <pre className="max-h-64 overflow-auto rounded-lg bg-muted p-3 text-xs">
              {JSON.stringify(selected.proposed_action, null, 2)}
            </pre>
            <p className="text-xs text-muted-foreground">
              Pertanyaan: {selected.query_text || '-'}
            </p>
            <p className="text-xs text-muted-foreground">
              Alasan penolakan sebelumnya: {selected.rejection_reason || '-'}
            </p>
            <label className="flex flex-col gap-1 text-xs">
              <span className="text-muted-foreground">Catatan persetujuan (opsional)</span>
              <textarea
                aria-label="Catatan persetujuan"
                className="min-h-20 w-full rounded-lg border border-border/80 bg-card p-2 text-sm"
                value={note}
                onChange={(event) => {
                  setNote(event.target.value);
                }}
              />
            </label>
            <label className="flex flex-col gap-1 text-xs">
              <span className="text-muted-foreground">Alasan penolakan (wajib untuk Tolak)</span>
              <textarea
                aria-label="Alasan penolakan"
                className="min-h-20 w-full rounded-lg border border-border/80 bg-card p-2 text-sm"
                value={reason}
                onChange={(event) => {
                  setReason(event.target.value);
                }}
              />
            </label>
          </div>
        )}
      </Modal>
    </div>
  );
}

