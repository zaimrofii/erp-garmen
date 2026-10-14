import { Clock, Download, RefreshCw } from 'lucide-react';
import { Button } from '@/components/atoms/Button';
import { BottleneckAlert } from '@/components/molecules/BottleneckAlert';
import { StatusChip } from '@/components/molecules/StatusChip';
import { cn } from '@/lib/cn';
import { CARD, TABLE_CELL, TABLE_HEAD } from '@/lib/tokens';
import type { StatusChipStatus } from '@/lib/state-display';
import type { BufferQueueBundle, BufferQueueWcRow } from '@/api/bufferQueue';

/**
 * BufferQueueTable - tabel antrean buffer per work center (F2C.2, shape backend).
 *
 * Baris = work center (`BufferQueueWcRow`); detail bundle (`BufferQueueBundle`)
 * ditampilkan per WC. `from_wc`/`to_wc` bisa `null` (step pertama / terminal) → "—".
 */

const BOTTLENECK_QUEUE = 10;

const STATE_CHIP: Record<string, StatusChipStatus> = {
  DRAFT: 'delay',
  CUTTING: 'delay',
  SEWING: 'on_track',
  QC: 'on_track',
  DONE: 'on_track',
};

interface BufferQueueTableProps {
  rows: BufferQueueWcRow[];
  onRefresh?: () => void;
  onExport?: () => void;
  className?: string;
}

export function BufferQueueTable({ rows, onRefresh, onExport, className }: BufferQueueTableProps) {
  const bottlenecks = rows.filter((row) => row.queue_depth > BOTTLENECK_QUEUE);
  const worst = bottlenecks.reduce<BufferQueueWcRow | null>(
    (acc, row) => (acc === null || row.queue_depth > acc.queue_depth ? row : acc),
    null,
  );

  return (
    <section className={cn(CARD, 'flex flex-col gap-4', className)}>
      <header className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-base font-semibold tracking-tight text-foreground">Antrean Buffer</h2>
          <p className="text-xs text-muted-foreground">{rows.length} work center aktif</p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {onRefresh !== undefined ? (
            <Button variant="secondary" size="sm" icon={RefreshCw} onClick={onRefresh}>
              Refresh
            </Button>
          ) : null}
          {onExport !== undefined ? (
            <Button variant="secondary" size="sm" icon={Download} onClick={onExport}>
              Export
            </Button>
          ) : null}
        </div>
      </header>

      {rows.length === 0 ? (
        <div className="flex items-center gap-2 rounded-lg border border-border/40 p-3 text-sm text-muted-foreground">
          <Clock className="h-4 w-4 shrink-0" aria-hidden="true" />
          Antrean kosong
        </div>
      ) : (
        <div className="flex flex-col gap-5">
          {rows.map((row) => (
            <div key={row.wc_code} className="flex flex-col gap-2">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h3 className="text-sm font-semibold tracking-tight text-foreground">
                  {row.wc_name}{' '}
                  <span className="font-mono text-xs text-muted-foreground">({row.wc_code})</span>
                </h3>
                <span className="text-xs text-muted-foreground">
                  {row.queue_depth} bundle - rata-rata tunggu {row.avg_wait_min} mnt
                </span>
              </div>

              <div className="overflow-x-auto">
                <table className="w-full border-collapse">
                  <caption className="sr-only">Antrean bundle {row.wc_name}</caption>
                  <thead>
                    <tr>
                      <th scope="col" className={TABLE_HEAD}>
                        Bundle
                      </th>
                      <th scope="col" className={TABLE_HEAD}>
                        Dari
                      </th>
                      <th scope="col" className={TABLE_HEAD}>
                        Ke
                      </th>
                      <th scope="col" className={TABLE_HEAD}>
                        Qty
                      </th>
                      <th scope="col" className={TABLE_HEAD}>
                        Menunggu
                      </th>
                      <th scope="col" className={TABLE_HEAD}>
                        Status
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {row.bundles.map((bundle: BufferQueueBundle) => (
                      <tr key={bundle.code}>
                        <td className={cn(TABLE_CELL, 'font-mono')}>{bundle.code}</td>
                        <td className={TABLE_CELL}>{bundle.from_wc ?? '—'}</td>
                        <td className={TABLE_CELL}>{bundle.to_wc ?? '—'}</td>
                        <td className={TABLE_CELL}>{bundle.qty}</td>
                        <td className={TABLE_CELL}>{bundle.waited_min} mnt</td>
                        <td className={TABLE_CELL}>
                          <StatusChip
                            status={STATE_CHIP[bundle.status] ?? 'on_track'}
                            label={bundle.status}
                          />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ))}
        </div>
      )}

      {worst !== null ? (
        <BottleneckAlert
          wc={worst.wc_code}
          count={worst.queue_depth}
          delayHours={Number((worst.avg_wait_min / 60).toFixed(1))}
        />
      ) : null}
    </section>
  );
}
