import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { RefreshCw } from 'lucide-react';
import { Button } from '@/components/atoms/Button';
import { Spinner } from '@/components/atoms/Spinner';
import { Tabs } from '@/components/atoms/Tabs';
import { PageHeader } from '@/components/molecules/PageHeader';
import { StatusChip } from '@/components/molecules/StatusChip';
import { fetchQCLogs } from '@/api/qc';
import { useApiClient } from '@/hooks/useApiClient';
import { cn } from '@/lib/cn';
import { CARD, TABLE_CELL, TABLE_HEAD } from '@/lib/tokens';

/**
 * DefectLogPage - agregat defect QC per work center (F2C.2).
 *
 * Data NYATA `GET /api/v1/quality/defects/` (B4 + G3): baris `DefectRow` dengan
 * `defect_entries[]` (detail per cacat) + `action` (`rework`/`scrap`/`null`).
 */

const ALL_WC = 'all';

const ACTION_LABEL: Record<string, string> = { rework: 'Rework', scrap: 'Scrap' };

export function DefectLogPage() {
  const client = useApiClient();
  const [wcFilter, setWcFilter] = useState<string>(ALL_WC);

  const { data, isLoading, isFetching, error, refetch } = useQuery({
    queryKey: ['qc-logs'],
    queryFn: () => fetchQCLogs(client),
    staleTime: 15_000,
  });

  const logs = data ?? [];
  const wcTabs = [
    { id: ALL_WC, label: 'Semua WC' },
    ...Array.from(new Set(logs.map((log) => log.wc_code ?? '—'))).map((wc) => ({
      id: wc,
      label: wc,
    })),
  ];

  const visibleLogs = wcFilter === ALL_WC ? logs : logs.filter((log) => (log.wc_code ?? '—') === wcFilter);

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <PageHeader
        title="Defect Log"
        subtitle="Agregat defect QC per work center"
        breadcrumb={[{ label: 'Quality' }, { label: 'Defect Log' }]}
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

      <Tabs tabs={wcTabs} active={wcFilter} onChange={setWcFilter} className="self-start" />

      <section className={cn(CARD, 'flex flex-col gap-3 p-0')}>
        {isLoading ? (
          <div className="flex items-center justify-center p-8">
            <Spinner size="lg" />
          </div>
        ) : null}

        {error !== null ? (
          <p role="alert" className="p-4 text-sm font-medium text-accent-coral">
            Gagal memuat defect log.
          </p>
        ) : null}

        {!isLoading && visibleLogs.length === 0 ? (
          <p className="p-6 text-sm text-muted-foreground">Belum ada catatan defect.</p>
        ) : null}

        {visibleLogs.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full border-collapse">
              <caption className="sr-only">Catatan defect QC</caption>
              <thead>
                <tr>
                  <th scope="col" className={TABLE_HEAD}>
                    WC
                  </th>
                  <th scope="col" className={TABLE_HEAD}>
                    Bundle
                  </th>
                  <th scope="col" className={TABLE_HEAD}>
                    Jenis Cacat
                  </th>
                  <th scope="col" className={TABLE_HEAD}>
                    Qty
                  </th>
                  <th scope="col" className={TABLE_HEAD}>
                    Aksi
                  </th>
                  <th scope="col" className={TABLE_HEAD}>
                    Tanggal
                  </th>
                </tr>
              </thead>
              <tbody>
                {visibleLogs.map((log, index) => (
                  <tr key={`${log.bundle_code ?? '-'}-${log.recorded_at ?? index}`}>
                    <td className={TABLE_CELL}>{log.wc_code ?? '—'}</td>
                    <td className={cn(TABLE_CELL, 'font-mono')}>{log.bundle_code ?? '—'}</td>
                    <td className={TABLE_CELL}>
                      <ul className="flex flex-wrap gap-1">
                        {log.defect_entries.map((entry, entryIndex) => (
                          <li
                            key={`${entry.type}-${entry.location ?? entryIndex}`}
                            className="rounded-pill bg-muted px-2 py-0.5 text-[11px] text-muted-foreground"
                          >
                            {entry.type}
                            {entry.location === null ? '' : ` - ${entry.location}`}
                            {entry.note.length === 0 ? '' : ` (${entry.note})`}
                          </li>
                        ))}
                      </ul>
                    </td>
                    <td className={TABLE_CELL}>
                      {log.defect_entries.reduce((total, entry) => total + entry.qty, 0)}
                    </td>
                    <td className={TABLE_CELL}>
                      {log.action === null ? (
                        '—'
                      ) : (
                        <StatusChip
                          status={log.action === 'scrap' ? 'bottleneck' : 'delay'}
                          label={ACTION_LABEL[log.action] ?? log.action}
                        />
                      )}
                    </td>
                    <td className={TABLE_CELL}>
                      {log.recorded_at === null
                        ? '—'
                        : new Date(log.recorded_at).toLocaleString('id-ID')}
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
