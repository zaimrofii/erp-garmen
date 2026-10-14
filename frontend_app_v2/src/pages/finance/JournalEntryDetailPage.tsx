import { useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, CheckCircle2, Pencil, Send, Trash2, XCircle } from 'lucide-react';
import { Badge } from '@/components/atoms/Badge';
import { Button } from '@/components/atoms/Button';
import { Spinner } from '@/components/atoms/Spinner';
import { Toast, type ToastTone } from '@/components/atoms/Toast';
import { DenseTable, type DenseTableColumn } from '@/components/molecules/DenseTable';
import { PageHeader } from '@/components/molecules/PageHeader';
import {
  actJournalEntry,
  deleteJournalEntry,
  fetchJournalEntry,
  type JournalEntryAction,
} from '@/api/journalEntries';
import { useFeedback } from '@/app/app-runtime';
import { useApiClient } from '@/hooks/useApiClient';
import { cn } from '@/lib/cn';
import {
  JOURNAL_ENTRY_ACTION_LABELS,
  JOURNAL_ENTRY_STATE_TO_ACTION,
  journalEntryBalance,
  journalEntryBalanceText,
  journalEntryDetailItems,
  journalEntryLineItems,
  journalEntryStateLabel,
  journalEntryStateTone,
  type JournalEntryLineItem,
} from '@/lib/journal-entry';
import { CARD } from '@/lib/tokens';

/**
 * JournalEntryDetailPage - route `/finance/journal-entries/:id` (H3.4, read-only + aksi).
 *
 * Menampilkan satu entry + baris jurnalnya + jejak sync (`odoo_sync_status`/`odoo_id`);
 * tombol aksi mengikuti `allowed_actions` backend:
 *
 *   * **DRAFT** → `confirm` (push draft `account.move` `move_type='entry'` ke Odoo; butuh
 *     journal general + semua akun sudah punya `odoo_id` + Σ debit = Σ kredit) atau
 *     `cancel`; entry hanya bisa di-**Edit/Hapus** selama DRAFT;
 *   * **CONFIRMED/SENT** → `done` (murni MES) atau `cancel` (`button_cancel` bila
 *     `odoo_id` ada).
 *
 * ⚠️ **Posting bukan di MES**: entry dikirim draft dan akuntan Odoo yang mem-posting.
 */

interface ToastState {
  tone: ToastTone;
  title: string;
  description: string;
}

/** Ikon per aksi transisi (label dari `JOURNAL_ENTRY_ACTION_LABELS`). */
const ACTION_ICONS = {
  confirm: Send,
  done: CheckCircle2,
  cancel: XCircle,
} as const;

/** Kolom tabel baris jurnal (bentuk backend `entry_line_rows`). */
const LINE_COLUMNS: DenseTableColumn<JournalEntryLineItem>[] = [
  {
    key: 'account',
    label: 'Akun',
    render: (row) => <span className="font-mono tabular-nums">{row.account}</span>,
  },
  { key: 'name', label: 'Keterangan' },
  { key: 'partner', label: 'Partner' },
  { key: 'debit', label: 'Debit', align: 'right' },
  { key: 'credit', label: 'Kredit', align: 'right' },
];

export function JournalEntryDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const client = useApiClient();
  const queryClient = useQueryClient();
  const { trigger } = useFeedback();

  const [toast, setToast] = useState<ToastState | null>(null);

  const parsedId = id === undefined ? null : Number(id);
  const entryId = parsedId !== null && Number.isFinite(parsedId) ? parsedId : null;

  const { data: entry, isLoading, error, refetch } = useQuery({
    queryKey: ['journal-entry', entryId],
    queryFn: () => fetchJournalEntry(client, entryId ?? 0),
    enabled: entryId !== null,
    staleTime: 15_000,
  });

  function afterChange(message: string): void {
    trigger('success');
    setToast({ tone: 'success', title: message, description: 'Perubahan tersimpan di MES.' });
    void queryClient.invalidateQueries({ queryKey: ['journal-entries'] });
    void refetch();
  }

  const runAction = useMutation({
    mutationFn: async (action: JournalEntryAction) => actJournalEntry(client, entryId ?? 0, action),
    onSuccess: (saved) => {
      afterChange(`${saved.code} → ${journalEntryStateLabel(saved.state)}`);
    },
    onError: (caught) => {
      trigger('error');
      setToast({
        tone: 'error',
        title: 'Aksi gagal',
        description: caught instanceof Error ? caught.message : 'Permintaan aksi gagal.',
      });
    },
  });

  const remove = useMutation({
    mutationFn: async () => deleteJournalEntry(client, entryId ?? 0),
    onSuccess: () => {
      trigger('success');
      navigate('/finance/journal-entries');
    },
    onError: (caught) => {
      trigger('error');
      setToast({
        tone: 'error',
        title: 'Gagal menghapus journal entry',
        description: caught instanceof Error ? caught.message : 'Permintaan hapus gagal.',
      });
    },
  });

  const isDraft = entry?.state === 'DRAFT';
  const actions = entry?.allowed_actions ?? [];
  const balance = entry === undefined ? null : journalEntryBalance(entry);

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <PageHeader
        title={entry === undefined ? 'Detail Journal Entry' : entry.code}
        subtitle="Jurnal manual double-entry MES — draft account.move di Odoo, push saat CONFIRMED"
        breadcrumb={[
          { label: 'Finance', href: '/finance/journal-entries' },
          { label: entry === undefined ? 'Detail' : entry.code },
        ]}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Button
              variant="secondary"
              icon={ArrowLeft}
              onClick={() => navigate('/finance/journal-entries')}
            >
              Kembali
            </Button>

            <Button
              icon={Pencil}
              disabled={entry === undefined || !isDraft}
              onClick={() => navigate(`/finance/journal-entries/${String(entryId)}/edit`)}
            >
              Edit
            </Button>

            {actions.map((target) => {
              const action = JOURNAL_ENTRY_STATE_TO_ACTION[target];
              if (action === undefined) return null;

              return (
                <Button
                  key={target}
                  variant={action === 'cancel' ? 'secondary' : 'primary'}
                  icon={ACTION_ICONS[action]}
                  loading={runAction.isPending}
                  onClick={() => runAction.mutate(action)}
                >
                  {JOURNAL_ENTRY_ACTION_LABELS[target]}
                </Button>
              );
            })}

            <Button
              variant="secondary"
              icon={Trash2}
              disabled={entry === undefined || !isDraft}
              loading={remove.isPending}
              onClick={() => remove.mutate()}
            >
              Hapus
            </Button>
          </div>
        }
      />

      {isLoading ? (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Spinner size="sm" /> Memuat journal entry…
        </div>
      ) : null}

      {error !== null ? (
        <section className={cn(CARD, 'flex flex-col gap-2')}>
          <p role="alert" className="text-sm font-medium text-accent-coral">
            Gagal memuat journal entry (perlu login atau entry tidak ada).
          </p>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => {
              void refetch();
            }}
          >
            Coba Lagi
          </Button>
        </section>
      ) : null}

      {entry !== undefined ? (
        <>
          <section className={cn(CARD, 'flex flex-wrap items-center gap-3')}>
            <span className="font-mono text-sm font-semibold text-foreground">{entry.code}</span>
            <Badge tone={journalEntryStateTone(entry.state)}>
              {journalEntryStateLabel(entry.state)}
            </Badge>
            <Badge tone={entry.journal_type === 'general' ? 'blue' : 'muted'}>
              {`Journal ${entry.journal_code ?? '-'}${
                entry.journal_type === '' ? '' : ` (${entry.journal_type})`
              }`}
            </Badge>
            <Badge tone={entry.odoo_id === null ? 'coral' : 'blue'}>
              {entry.odoo_id === null ? 'Belum sync Odoo' : `Odoo #${String(entry.odoo_id)}`}
            </Badge>
            {entry.odoo_sync_status !== null ? (
              <Badge tone={entry.odoo_sync_status === 'FAILED' ? 'coral' : 'muted'}>
                {`Sync ${entry.odoo_sync_status}`}
              </Badge>
            ) : null}
          </section>

          {entry.odoo_sync_error !== null ? (
            <section className={cn(CARD, 'flex flex-col gap-1')}>
              <span className="text-xs font-medium text-muted-foreground">Error sync terakhir</span>
              <span className="text-sm text-accent-coral">{entry.odoo_sync_error}</span>
            </section>
          ) : null}

          <section className={cn(CARD, 'grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3')}>
            {journalEntryDetailItems(entry).map((item) => (
              <div key={item.label} className="flex flex-col gap-1">
                <span className="text-xs font-medium text-muted-foreground">{item.label}</span>
                <span
                  className={cn(
                    'text-sm text-foreground',
                    item.mono === true ? 'font-mono' : undefined,
                  )}
                >
                  {item.value}
                </span>
              </div>
            ))}
          </section>

          {balance !== null ? (
            <section className={cn(CARD, 'flex flex-wrap items-center gap-3 text-sm')}>
              <span
                className={cn(
                  'font-medium',
                  balance.balanced ? 'text-muted-foreground' : 'text-accent-coral',
                )}
              >
                {journalEntryBalanceText(balance)}
              </span>
              <span className="text-muted-foreground">
                Baris:{' '}
                <span className="font-mono tabular-nums text-foreground">{entry.line_count}</span>
              </span>
            </section>
          ) : null}

          <section className={cn(CARD, 'p-0')}>
            <DenseTable
              columns={LINE_COLUMNS}
              rows={journalEntryLineItems(entry.lines)}
              loading={false}
              error={null}
              emptyMessage="Entry ini belum punya baris jurnal."
            />
          </section>

          {entry.memo !== '' ? (
            <section className={cn(CARD, 'flex flex-col gap-1')}>
              <span className="text-xs font-medium text-muted-foreground">Catatan</span>
              <span className="text-sm text-foreground">{entry.memo}</span>
            </section>
          ) : null}
        </>
      ) : null}

      <Toast
        open={toast !== null}
        onOpenChange={() => setToast(null)}
        title={toast?.title ?? ''}
        {...(toast === null ? {} : { tone: toast.tone, description: toast.description })}
      />
    </div>
  );
}
