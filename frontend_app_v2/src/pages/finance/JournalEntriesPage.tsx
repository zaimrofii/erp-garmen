import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Plus } from 'lucide-react';
import { Badge } from '@/components/atoms/Badge';
import { Button } from '@/components/atoms/Button';
import { Input } from '@/components/atoms/Input';
import { DenseTable, type DenseTableColumn } from '@/components/molecules/DenseTable';
import { PageHeader } from '@/components/molecules/PageHeader';
import { PaginationBar } from '@/components/molecules/PaginationBar';
import { TableToolbar } from '@/components/molecules/TableToolbar';
import {
  fetchJournalEntries,
  JOURNAL_ENTRIES_LIMIT_MAX,
  type JournalEntryRow,
} from '@/api/journalEntries';
import { useApiClient } from '@/hooks/useApiClient';
import { useCsvExport, type CsvColumn } from '@/hooks/use-csv-export';
import { usePagination } from '@/hooks/use-pagination';
import { cn } from '@/lib/cn';
import {
  isJournalEntryStateFilter,
  journalEntryStateLabel,
  journalEntryStateTone,
  JOURNAL_ENTRY_STATE_FILTERS,
  stateParamForJournalEntryFilter,
} from '@/lib/journal-entry';
import { CARD } from '@/lib/tokens';
import type { JournalEntryState } from '@/types/journal-entry';

/**
 * JournalEntriesPage - route `/finance/journal-entries` (H3.4, app Finance).
 *
 * Daftar journal entry manual MES NYATA dari `GET /api/v1/finance/journal-entries/`
 * (`api/journalEntries.ts` → MODE.journalEntries='real'):
 *
 *   * filter server: `?search=` (kode/ref/memo/journal), `?state=`, `?date_from=`/
 *     `?date_to=` (ISO) + Reset Filter;
 *   * kolom: Kode, Journal, Tanggal, Referensi, Debit, Kredit, State, Odoo ID;
 *   * klik baris → detail; "Journal Entry Baru" → `/finance/journal-entries/new`;
 *   * Export CSV via `useCsvExport` (kolom = bentuk backend).
 *
 * ⚠️ MES **tidak mem-posting**: entry dikirim sebagai `account.move` `move_type='entry'`
 * **draft**, akuntan Odoo yang mem-posting. Guard route: `FINANCE_ROLES`.
 */

const EMPTY_ROWS: JournalEntryRow[] = [];

const CSV_COLUMNS: CsvColumn<JournalEntryRow>[] = [
  { key: 'code', label: 'Kode' },
  { key: 'journal_code', label: 'Journal' },
  { key: 'entry_date', label: 'Tanggal' },
  { key: 'ref', label: 'Referensi' },
  { key: 'total_debit', label: 'Total debit' },
  { key: 'total_credit', label: 'Total kredit' },
  { key: 'state', label: 'State' },
  { key: 'odoo_id', label: 'Odoo ID' },
];

const COLUMNS: DenseTableColumn<JournalEntryRow>[] = [
  {
    key: 'code',
    label: 'Kode',
    render: (row) => <span className="font-mono tabular-nums">{row.code}</span>,
  },
  {
    key: 'journal_code',
    label: 'Journal',
    render: (row) => (
      <span>
        <span className="font-mono tabular-nums">{row.journal_code ?? '-'}</span>
        {row.journal_name === null ? null : (
          <span className="text-muted-foreground">{` — ${row.journal_name}`}</span>
        )}
      </span>
    ),
  },
  { key: 'entry_date', label: 'Tanggal' },
  {
    key: 'ref',
    label: 'Referensi',
    render: (row) => <span className="font-mono tabular-nums">{row.ref === '' ? '-' : row.ref}</span>,
  },
  { key: 'total_debit', label: 'Debit', align: 'right' },
  { key: 'total_credit', label: 'Kredit', align: 'right' },
  {
    key: 'state',
    label: 'State',
    render: (row) => (
      <Badge tone={journalEntryStateTone(row.state)}>{journalEntryStateLabel(row.state)}</Badge>
    ),
  },
  {
    key: 'odoo_id',
    label: 'Odoo ID',
    align: 'right',
    render: (row) =>
      row.odoo_id === null ? (
        <span className="text-muted-foreground">-</span>
      ) : (
        <span className="font-mono tabular-nums">{String(row.odoo_id)}</span>
      ),
  },
];

export function JournalEntriesPage() {
  const navigate = useNavigate();
  const client = useApiClient();
  const { exportCsv } = useCsvExport();

  const [search, setSearch] = useState('');
  const [filter, setFilter] = useState<'all' | JournalEntryState>('all');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');

  const { data, isLoading, isFetching, error, refetch } = useQuery({
    queryKey: ['journal-entries', search, filter, dateFrom, dateTo],
    queryFn: () =>
      fetchJournalEntries(client, {
        search,
        state: stateParamForJournalEntryFilter(filter),
        date_from: dateFrom === '' ? null : dateFrom,
        date_to: dateTo === '' ? null : dateTo,
        limit: JOURNAL_ENTRIES_LIMIT_MAX,
      }),
    staleTime: 15_000,
  });

  const rows = data?.rows ?? EMPTY_ROWS;
  const pagination = usePagination(rows, { pageSize: 20 });

  const hasFilter =
    search.trim().length > 0 || filter !== 'all' || dateFrom !== '' || dateTo !== '';

  function handleSearch(value: string): void {
    setSearch(value);
    pagination.reset();
  }

  function handleFilter(id: string): void {
    if (!isJournalEntryStateFilter(id)) return;

    setFilter(id);
    pagination.reset();
  }

  function resetFilters(): void {
    setSearch('');
    setFilter('all');
    setDateFrom('');
    setDateTo('');
    pagination.reset();
  }

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <PageHeader
        title="Journal Entry"
        subtitle={`Jurnal manual double-entry (draft account.move ke Odoo) — ${String(
          data?.total_count ?? 0,
        )} baris`}
        breadcrumb={[
          { label: 'Finance', href: '/finance/journal-entries' },
          { label: 'Journal Entry' },
        ]}
        actions={
          <Button icon={Plus} onClick={() => navigate('/finance/journal-entries/new')}>
            Journal Entry Baru
          </Button>
        }
      />

      <section className={cn(CARD, 'flex flex-col gap-3 p-4')}>
        <TableToolbar
          search={search}
          onSearchChange={handleSearch}
          searchLabel="Cari journal entry"
          searchPlaceholder="Cari kode / referensi / catatan / journal"
          filters={JOURNAL_ENTRY_STATE_FILTERS}
          activeFilter={filter}
          onFilterChange={handleFilter}
          exportDisabled={rows.length === 0}
          onExport={() => exportCsv(rows, 'journal-entries.csv', CSV_COLUMNS)}
          refreshing={isFetching}
          onRefresh={() => {
            void refetch();
          }}
        />

        <div className="flex flex-wrap items-end gap-3">
          <Input
            label="Dari tanggal"
            type="date"
            value={dateFrom}
            onChange={(event) => {
              setDateFrom(event.target.value);
              pagination.reset();
            }}
          />
          <Input
            label="Sampai tanggal"
            type="date"
            value={dateTo}
            onChange={(event) => {
              setDateTo(event.target.value);
              pagination.reset();
            }}
          />

          <Button variant="secondary" size="sm" disabled={!hasFilter} onClick={resetFilters}>
            Reset Filter
          </Button>
        </div>
      </section>

      <section className={cn(CARD, 'p-0')}>
        <DenseTable
          columns={COLUMNS}
          rows={pagination.pageRows}
          loading={isLoading}
          error={error === null ? null : 'Gagal memuat journal entry.'}
          onRetry={() => {
            void refetch();
          }}
          onRowClick={(row) => navigate(`/finance/journal-entries/${String(row.id)}`)}
          emptyMessage={
            hasFilter
              ? 'Tidak ada journal entry yang cocok dengan filter.'
              : 'Belum ada journal entry. Tambahkan lewat tombol "Journal Entry Baru".'
          }
        />
      </section>

      <PaginationBar
        page={pagination.page}
        totalPages={pagination.totalPages}
        rangeStart={pagination.rangeStart}
        rangeEnd={pagination.rangeEnd}
        total={pagination.total}
        canPrev={pagination.canPrev}
        canNext={pagination.canNext}
        onPrev={pagination.goPrev}
        onNext={pagination.goNext}
      />
    </div>
  );
}
