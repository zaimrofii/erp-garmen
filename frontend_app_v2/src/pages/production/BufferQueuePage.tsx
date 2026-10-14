import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Download, RefreshCw } from 'lucide-react';
import { Button } from '@/components/atoms/Button';
import { Spinner } from '@/components/atoms/Spinner';
import { Tabs } from '@/components/atoms/Tabs';
import { BufferQueueTable } from '@/components/molecules/BufferQueueTable';
import { PageHeader } from '@/components/molecules/PageHeader';
import { fetchBufferQueue } from '@/api/bufferQueue';
import { useApiClient } from '@/hooks/useApiClient';

/**
 * BufferQueuePage - route `/production/buffer-queue` (F2C.2).
 *
 * Data NYATA `GET /api/v1/production/buffer-queue/` (B2 + G2): baris per work center.
 */

const ALL_WC = 'all';

const CSV_HEADER = ['bundle_code', 'wc_code', 'from_wc', 'to_wc', 'qty', 'waited_min', 'status'];

export function BufferQueuePage() {
  const client = useApiClient();
  const [wcFilter, setWcFilter] = useState<string>(ALL_WC);

  const { data, isLoading, isFetching, error, refetch } = useQuery({
    queryKey: ['buffer-queue'],
    queryFn: () => fetchBufferQueue(client),
    staleTime: 15_000,
  });

  if (isLoading) {
    return (
      <div className="flex min-h-full items-center justify-center p-8">
        <Spinner size="lg" />
      </div>
    );
  }

  if (error !== null || data === undefined) {
    return (
      <div className="flex min-h-full flex-col items-center justify-center gap-4 p-8">
        <p role="alert" className="text-sm font-semibold text-foreground">
          Gagal memuat antrean buffer.
        </p>
        <Button
          variant="secondary"
          onClick={() => {
            void refetch();
          }}
        >
          Coba Lagi
        </Button>
      </div>
    );
  }

  const wcTabs = [
    { id: ALL_WC, label: 'Semua WC' },
    ...data.rows.map((row) => ({ id: row.wc_code, label: row.wc_code })),
  ];

  const visibleRows =
    wcFilter === ALL_WC ? data.rows : data.rows.filter((row) => row.wc_code === wcFilter);

  const totalBundle = data.rows.reduce((total, row) => total + row.queue_depth, 0);
  const maxWait = data.rows.reduce((max, row) => Math.max(max, row.avg_wait_min), 0);

  const flat = visibleRows.flatMap((row) =>
    row.bundles.map((bundle) => ({ wc_code: row.wc_code, bundle })),
  );

  function downloadCsv(): void {
    if (typeof document === 'undefined') return;

    const lines = flat.map(({ wc_code, bundle }) =>
      [
        bundle.code,
        wc_code,
        bundle.from_wc ?? '',
        bundle.to_wc ?? '',
        String(bundle.qty),
        String(bundle.waited_min),
        bundle.status,
      ].join(','),
    );
    const blob = new Blob([[CSV_HEADER.join(','), ...lines].join('\n')], {
      type: 'text/csv;charset=utf-8',
    });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');

    link.href = url;
    link.download = `buffer-queue-${flat.length}-baris.csv`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <PageHeader
        title="Buffer Queue"
        subtitle="Antrean per work center"
        breadcrumb={[{ label: 'Production' }, { label: 'Buffer Queue' }]}
        actions={
          <>
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
            <Button
              variant="secondary"
              size="sm"
              icon={Download}
              disabled={flat.length === 0}
              onClick={downloadCsv}
            >
              Export CSV
            </Button>
          </>
        }
      />

      <p className="text-xs text-muted-foreground">
        {visibleRows.length} work center - total {totalBundle} bundle - rata-rata tunggu terlama{' '}
        {maxWait} menit
      </p>

      <Tabs tabs={wcTabs} active={wcFilter} onChange={setWcFilter} className="self-start" />

      <BufferQueueTable
        rows={visibleRows}
        onRefresh={() => {
          void refetch();
        }}
        onExport={downloadCsv}
      />
    </div>
  );
}
