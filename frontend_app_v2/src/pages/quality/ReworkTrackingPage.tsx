import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { RefreshCw } from 'lucide-react';
import { Button } from '@/components/atoms/Button';
import { Spinner } from '@/components/atoms/Spinner';
import { Tabs } from '@/components/atoms/Tabs';
import { PageHeader } from '@/components/molecules/PageHeader';
import { StatusChip } from '@/components/molecules/StatusChip';
import { fetchReworkRecords } from '@/api/qc';
import { useApiClient } from '@/hooks/useApiClient';
import { cn } from '@/lib/cn';
import { CARD, TABLE_CELL, TABLE_HEAD } from '@/lib/tokens';

/**
 * ReworkTrackingPage - riwayat rework QC (F2C.2).
 *
 * Data NYATA `GET /api/v1/quality/rework/` (B6). CATATAN: `from_step`/`to_step`
 * SELALU `null` (backend `CycleInstance` tidak menyimpan step) → dirender "—".
 */

const ALL = 'all';

const FILTERS = [
  { id: ALL, label: 'Semua' },
  { id: 'open', label: 'Buka' },
  { id: 'closed', label: 'Tutup' },
];

export function ReworkTrackingPage() {
  const client = useApiClient();
  const [filter, setFilter] = useState<string>(ALL);

  const { data, isLoading, isFetching, error, refetch } = useQuery({
    queryKey: ['qc-rework'],
    queryFn: () => fetchReworkRecords(client),
    staleTime: 15_000,
  });

  const records = data ?? [];
  const visible =
    filter === ALL
      ? records
      : records.filter((record) => (filter === 'open' ? record.is_open : !record.is_open));

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <PageHeader
        title="Rework Tracking"
        subtitle="Siklus rework QC per bundle"
        breadcrumb={[{ label: 'Quality' }, { label: 'Rework' }]}
        actions={
          <Button
            variant="secondary"
            size="sm"
            icon={RefreshCw}
            loading={isFetching}
            onClick={() => {
              void refetch();
            }}
          >
            Refresh
          </Button>
        }
      />

      <Tabs tabs={FILTERS} active={filter} onChange={setFilter} className="self-start" />

      <section className={cn(CARD, 'flex flex-col gap-3 p-0')}>
        {isLoading ? (
          <div className="flex items-center justify-center p-8">
            <Spinner size="lg" />
          </div>
        ) : null}

        {error !== null ? (
          <p role="alert" className="p-4 text-sm font-medium text-accent-coral">
            Gagal memuat data rework.
          </p>
        ) : null}

        {!isLoading && visible.length === 0 ? (
          <p className="p-6 text-sm text-muted-foreground">Belum ada rework tercatat.</p>
        ) : null}

        {visible.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full border-collapse">
              <caption className="sr-only">Riwayat rework</caption>
              <thead>
                <tr>
                  <th scope="col" className={TABLE_HEAD}>
                    Bundle
                  </th>
                  <th scope="col" className={TABLE_HEAD}>
                    From Step
                  </th>
                  <th scope="col" className={TABLE_HEAD}>
                    To Step
                  </th>
                  <th scope="col" className={TABLE_HEAD}>
                    Iterasi
                  </th>
                  <th scope="col" className={TABLE_HEAD}>
                    Mulai
                  </th>
                  <th scope="col" className={TABLE_HEAD}>
                    Selesai
                  </th>
                  <th scope="col" className={TABLE_HEAD}>
                    Status
                  </th>
                </tr>
              </thead>
              <tbody>
                {visible.map((record, index) => (
                  <tr key={`${record.bundle_code ?? '-'}-${record.started_at ?? index}`}>
                    <td className={cn(TABLE_CELL, 'font-mono')}>{record.bundle_code ?? '—'}</td>
                    <td className={TABLE_CELL}>{record.from_step ?? '—'}</td>
                    <td className={TABLE_CELL}>{record.to_step ?? '—'}</td>
                    <td className={TABLE_CELL}>{record.iteration}</td>
                    <td className={TABLE_CELL}>
                      {record.started_at === null
                        ? '—'
                        : new Date(record.started_at).toLocaleString('id-ID')}
                    </td>
                    <td className={TABLE_CELL}>
                      {record.closed_at === null
                        ? '—'
                        : new Date(record.closed_at).toLocaleString('id-ID')}
                    </td>
                    <td className={TABLE_CELL}>
                      <StatusChip
                        status={record.is_open ? 'delay' : 'on_track'}
                        label={record.is_open ? 'Buka' : 'Tutup'}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </section>
    </div>
  );
}
