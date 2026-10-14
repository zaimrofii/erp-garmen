import { useMemo, useState, type FormEvent } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Filter, RefreshCw, ShieldCheck } from 'lucide-react';
import { Badge } from '@/components/atoms/Badge';
import { Button } from '@/components/atoms/Button';
import { Input } from '@/components/atoms/Input';
import { Modal } from '@/components/atoms/Modal';
import { Select } from '@/components/atoms/Select';
import { Spinner } from '@/components/atoms/Spinner';
import { DenseTable, type DenseTableColumn } from '@/components/molecules/DenseTable';
import { PageHeader } from '@/components/molecules/PageHeader';
import { PaginationBar } from '@/components/molecules/PaginationBar';
import {
  EMPTY_AUDIT_FILTERS,
  fetchAuditLog,
  fetchAuditLogs,
  type AuditLogFilters,
  type AuditLogRow,
} from '@/api/auditLogs';
import { useApiClient } from '@/hooks/useApiClient';
import { cn } from '@/lib/cn';
import {
  RESULT_OPTIONS,
  actorLabel,
  auditDetailEntries,
  auditResultTone,
  dash,
  formatAuditTimestamp,
  hasActiveFilters,
  isAuditFiltersValid,
  metadataSummary,
  validateAuditFilters,
} from '@/lib/audit-log';
import { CARD } from '@/lib/tokens';

/**
 * AuditLogPage - route `/settings/audit-log` (H5.5, ADMIN/OWNER).
 *
 * **READ-ONLY** (append-only): hanya membaca jejak audit dari
 * `GET /api/v1/settings/audit/` (+ `/<id>/` untuk detail). Tidak ada tombol
 * create/edit/hapus — audit trail tidak boleh diubah dari UI.
 *
 * Filter: user id, aksi (exact atau **prefix** bila diakhiri titik — `master.`),
 * resource, resource id, hasil (`OK|FAILED|CONFLICT|DENIED`), rentang tanggal
 * (inklusif; tanggal-saja = sampai akhir hari itu) dan kata kunci
 * (username/nama/aksi/resource). Paging offset `limit`/`cursor`.
 *
 * Kolom daftar memakai `metadata_preview` (JSON dipotong 100 karakter, rahasia
 * **sudah** di-mask backend); klik baris → modal detail dengan payload/metadata
 * lengkap (juga sudah di-mask).
 *
 * Guard route: `SETTINGS_ROLES` (halaman Settings; anonim/operator ditolak backend 403).
 *
 * ⚠️ Path FRONTEND `/settings/audit-log` (BUKAN `/settings/audit`) karena
 * `/settings/audit` sudah dipakai **F9** (audit produk tanpa `odoo_id`).
 */

const QUERY_KEY = 'settings-audit';
const DETAIL_KEY = 'settings-audit-detail';
const DEFAULT_LIMIT = 50;

/** Kolom tabel: mengikuti field NYATA baris backend (tanpa karangan). */
const COLUMNS: DenseTableColumn<AuditLogRow>[] = [
  {
    key: 'timestamp',
    label: 'Waktu',
    render: (row) => (
      <span className="font-mono text-xs tabular-nums">
        {formatAuditTimestamp(row.timestamp)}
      </span>
    ),
  },
  { key: 'actor', label: 'Pelaku', render: (row) => actorLabel(row) },
  {
    key: 'action',
    label: 'Aksi',
    render: (row) => <span className="font-mono text-xs">{dash(row.action)}</span>,
  },
  {
    key: 'resource',
    label: 'Resource',
    render: (row) => <span className="font-mono text-xs">{dash(row.resource)}</span>,
  },
  {
    key: 'resource_id',
    label: 'ID',
    render: (row) => <span className="font-mono text-xs">{dash(row.resource_id)}</span>,
  },
  {
    key: 'result',
    label: 'Hasil',
    render: (row) => <Badge tone={auditResultTone(row.result)}>{dash(row.result)}</Badge>,
  },
  {
    key: 'metadata_preview',
    label: 'Metadata',
    render: (row) => (
      <span className="font-mono text-xs text-muted-foreground">
        {metadataSummary(row)}
      </span>
    ),
  },
];

export function AuditLogPage() {
  const client = useApiClient();

  const [draft, setDraft] = useState<AuditLogFilters>({ ...EMPTY_AUDIT_FILTERS });
  const [applied, setApplied] = useState<AuditLogFilters>({ ...EMPTY_AUDIT_FILTERS });
  const [cursor, setCursor] = useState(0);
  const [selectedId, setSelectedId] = useState<number | null>(null);

  const errors = useMemo(() => validateAuditFilters(draft), [draft]);
  const valid = isAuditFiltersValid(errors);

  const logs = useQuery({
    queryKey: [QUERY_KEY, applied, cursor],
    queryFn: () => fetchAuditLogs(client, applied, { limit: DEFAULT_LIMIT, cursor }),
    staleTime: 15_000,
  });

  const detail = useQuery({
    queryKey: [DETAIL_KEY, selectedId],
    queryFn: () => fetchAuditLog(client, selectedId ?? 0),
    enabled: selectedId !== null,
    staleTime: 60_000,
  });

  function setField<K extends keyof AuditLogFilters>(
    field: K,
    value: AuditLogFilters[K],
  ): void {
    setDraft({ ...draft, [field]: value });
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();

    if (!valid) return;

    setCursor(0);
    setApplied({ ...draft });
  }

  function handleReset(): void {
    setDraft({ ...EMPTY_AUDIT_FILTERS });
    setApplied({ ...EMPTY_AUDIT_FILTERS });
    setCursor(0);
  }

  const rows = logs.data?.rows ?? [];
  const total = logs.data?.total_count ?? 0;
  const page = Math.floor(cursor / DEFAULT_LIMIT) + 1;
  const totalPages = total === 0 ? 1 : Math.ceil(total / DEFAULT_LIMIT);
  const rangeStart = total === 0 ? 0 : cursor + 1;
  const rangeEnd = cursor + rows.length;
  const loadError =
    logs.error === null || logs.error === undefined
      ? null
      : 'Gagal memuat audit log (perlu login ADMIN/OWNER?).';

  /** Entry modal detail (payload/metadata sebagai blok JSON, sudah masked backend). */
  const detailEntries = detail.data === undefined ? [] : auditDetailEntries(detail.data);

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <PageHeader
        title="Audit Log"
        subtitle="Jejak audit MES (siapa, kapan, aksi apa) — read-only, khusus ADMIN/OWNER"
        breadcrumb={[{ label: 'Settings' }, { label: 'Audit Log' }]}
        actions={
          <Button
            variant="ghost"
            icon={RefreshCw}
            onClick={() => {
              void logs.refetch();
            }}
          >
            Muat Ulang
          </Button>
        }
      />

      <form className={cn(CARD, 'flex flex-col gap-4')} onSubmit={handleSubmit}>
        <div className="flex items-center gap-2">
          <Filter className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
          <h2 className="text-sm font-medium text-foreground">Filter</h2>
        </div>

        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          <Input
            label="Kata kunci"
            value={draft.search}
            placeholder="username / nama / aksi / resource"
            onChange={(event) => setField('search', event.target.value)}
            {...(errors.search !== undefined ? { error: errors.search } : {})}
          />
          <Input
            label="Aksi (exact atau prefix, mis. master.)"
            value={draft.action}
            placeholder="master.create"
            onChange={(event) => setField('action', event.target.value)}
          />
          <Input
            label="Resource"
            value={draft.resource}
            placeholder="master.product"
            onChange={(event) => setField('resource', event.target.value)}
          />
          <Input
            label="Resource ID"
            value={draft.resource_id}
            placeholder="mis. 12"
            onChange={(event) => setField('resource_id', event.target.value)}
          />
          <Select
            label="Hasil"
            options={RESULT_OPTIONS}
            value={draft.result}
            onChange={(event) => setField('result', event.target.value)}
            {...(errors.result !== undefined ? { error: errors.result } : {})}
          />
          <Input
            label="User ID"
            type="number"
            value={draft.user_id}
            placeholder="id pelaku"
            onChange={(event) => setField('user_id', event.target.value)}
            {...(errors.user_id !== undefined ? { error: errors.user_id } : {})}
          />
          <Input
            label="Dari tanggal"
            type="date"
            value={draft.date_from}
            onChange={(event) => setField('date_from', event.target.value)}
            {...(errors.date_from !== undefined ? { error: errors.date_from } : {})}
          />
          <Input
            label="Sampai tanggal (inklusif)"
            type="date"
            value={draft.date_to}
            onChange={(event) => setField('date_to', event.target.value)}
            {...(errors.date_to !== undefined ? { error: errors.date_to } : {})}
          />
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="flex items-center gap-2 text-xs text-muted-foreground">
            <ShieldCheck className="h-3 w-3" aria-hidden="true" />
            Read-only: audit trail append-only — UI ini tidak pernah mengubah data.
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <Button
              type="button"
              variant="ghost"
              disabled={!hasActiveFilters(draft) && !hasActiveFilters(applied)}
              onClick={handleReset}
            >
              Bersihkan
            </Button>
            <Button type="submit" icon={Filter} loading={logs.isFetching}>
              Terapkan Filter
            </Button>
          </div>
        </div>
      </form>

      <section className={cn(CARD, 'flex flex-col gap-3 p-0')}>
        <DenseTable
          columns={COLUMNS}
          rows={rows}
          loading={logs.isLoading}
          error={loadError}
          onRetry={() => {
            void logs.refetch();
          }}
          onRowClick={(row) => setSelectedId(row.id)}
          emptyMessage="Belum ada audit pada filter ini."
        />

        <div className="px-4 pb-4">
          <PaginationBar
            page={page}
            totalPages={totalPages}
            rangeStart={rangeStart}
            rangeEnd={rangeEnd}
            total={total}
            canPrev={cursor > 0}
            canNext={logs.data?.has_more === true && rows.length > 0}
            onPrev={() => {
              setCursor(Math.max(0, cursor - DEFAULT_LIMIT));
            }}
            onNext={() => {
              setCursor(logs.data?.next_cursor ?? cursor + DEFAULT_LIMIT);
            }}
          />
        </div>
      </section>

      <Modal
        open={selectedId !== null}
        onOpenChange={(open) => {
          if (!open) setSelectedId(null);
        }}
        title="Detail audit"
        description="Payload & metadata lengkap — rahasia (api_key/password/token) sudah di-mask backend."
      >
        {detail.isLoading ? (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Spinner size="sm" /> Memuat detail audit…
          </div>
        ) : null}

        {detail.error !== null && detail.error !== undefined ? (
          <p role="alert" className="text-sm font-medium text-accent-coral">
            Gagal memuat detail audit.
          </p>
        ) : null}

        {detailEntries.length === 0 ? null : (
          <div className="flex flex-col gap-3">
            {detailEntries.map((entry) => (
              <div key={entry.label} className="flex flex-col gap-1">
                <span className="text-xs text-muted-foreground">{entry.label}</span>
                <span
                  className={cn(
                    'whitespace-pre-line text-sm',
                    entry.mono ? 'font-mono text-xs tabular-nums' : '',
                  )}
                >
                  {entry.value}
                </span>
              </div>
            ))}
          </div>
        )}
      </Modal>
    </div>
  );
}


