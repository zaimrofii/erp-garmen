import { Clock } from 'lucide-react';
import { Button } from '@/components/atoms/Button';
import { CHATTER_PAGE_LIMIT_DEFAULT } from '@/lib/chatter-merge';
import type { ChatterEvent } from '@/lib/schemas/chatter.schema';
import { cn } from '@/lib/cn';

/**
 * ChatterBox - daftar aktivitas (presentational).
 *
 * Fase 15: komponen ini TIDAK mengambil data sendiri (v2 dulu `resource` + `id`).
 * Halaman/container yang memegang `useChatter`/`useWebSocket` dan mengoper `preview`,
 * jadi chatter tetap bisa digabung dengan event real-time tanpa komponen ini tahu
 * soal jaringan. `key={event.id}` wajib (larangan `key={index}`).
 *
 * F1 (D4): prop kanonik = `preview` (kontrak backend v4.3 §3.3 mengirim `preview`, bukan
 * `events` — bentuk lama sudah dihapus backend).
 * F4 (4.3): alias deprecated `events` DIHAPUS - 3 halaman (BundleWorkshopPage,
 * bundles/BundleDetailPage, production/BundleDetailPage) sudah migrasi ke `preview`
 * + event real-time lewat `useChatterWs` (`mergeChatterPreview`).
 * `limit`/`cursor` = jejak state paginasi — query sebenarnya tetap dibuat `useChatter`.
 */

interface ChatterBoxProps {
  /** Daftar event dari `chatter.preview` + event WS (`mergeChatterPreview`). */
  preview: ChatterEvent[];
  loading?: boolean;
  onLoadMore?: () => void;
  hasMore?: boolean;
  /** `limit` halaman yang diminta; default `CHATTER_PAGE_LIMIT_DEFAULT` (20, kontrak §3.3). */
  limit?: number;
  /** Cursor halaman berikutnya dari `chatter.next_cursor` (`null` = belum ada). */
  cursor?: string | null;
  className?: string;
}

function initialsOf(name: string): string {
  const parts = name.trim().split(/\s+/).filter((part) => part.length > 0);
  if (parts.length === 0) return '?';

  const first = parts[0];
  const last = parts.length > 1 ? parts[parts.length - 1] : '';

  return `${first.charAt(0)}${last.charAt(0)}`.toUpperCase();
}

function formatRelativeTime(iso: string): string {
  const timestamp = new Date(iso).getTime();
  if (!Number.isFinite(timestamp)) return iso;

  const minutes = Math.round((Date.now() - timestamp) / 60_000);
  if (minutes < 1) return 'baru saja';
  if (minutes < 60) return `${minutes} menit lalu`;

  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} jam lalu`;

  const days = Math.round(hours / 24);
  return `${days} hari lalu`;
}

function formatPayloadValue(value: unknown): string {
  if (value === null || value === undefined) return '-';
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);

  return JSON.stringify(value) ?? '-';
}

export function ChatterBox({
  preview,
  loading = false,
  onLoadMore,
  hasMore = false,
  limit = CHATTER_PAGE_LIMIT_DEFAULT,
  cursor = null,
  className,
}: ChatterBoxProps) {
  const items = preview;

  return (
    <section
      data-chatter-preview-count={items.length}
      data-chatter-limit={limit}
      data-chatter-cursor={cursor ?? ''}
      className={cn('flex flex-col gap-3', className)}
    >
      <h2 className="text-sm font-semibold tracking-tight text-foreground">Aktivitas</h2>

      {loading ? <p className="text-sm text-muted-foreground">Memuat aktivitas...</p> : null}

      {!loading && items.length === 0 ? (
        <div className="flex items-center gap-2 rounded-lg border border-border/40 p-3 text-sm text-muted-foreground">
          <Clock className="h-4 w-4 shrink-0" aria-hidden="true" />
          Belum ada aktivitas
        </div>
      ) : null}

      <ol className="flex flex-col gap-2">
        {items.map((event) => (
          <li
            key={event.id}
            data-chatter-event={event.id}
            className="flex gap-3 rounded-lg border border-border/40 p-3 transition-colors hover:bg-muted/30"
          >
            <span
              aria-hidden="true"
              className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-muted text-xs font-semibold uppercase text-muted-foreground"
            >
              {initialsOf(event.actor.name)}
            </span>

            <div className="flex min-w-0 flex-col gap-0.5">
              <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
                <span className="text-sm font-semibold text-foreground">{event.actor.name}</span>
                <span className="text-xs text-muted-foreground">
                  {formatRelativeTime(event.created_at)}
                </span>
              </div>

              <p className="text-sm text-foreground">{event.summary}</p>

              {event.payload !== undefined ? (
                <dl className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-muted-foreground">
                  {Object.entries(event.payload)
                    .slice(0, 3)
                    .map(([key, value]) => (
                      <div key={key} className="flex gap-1">
                        <dt className="uppercase tracking-wider">{key}</dt>
                        <dd className="tabular-nums">{formatPayloadValue(value)}</dd>
                      </div>
                    ))}
                </dl>
              ) : null}
            </div>
          </li>
        ))}
      </ol>

      {hasMore && onLoadMore !== undefined ? (
        <div>
          <Button
            variant="secondary"
            size="sm"
            aria-label={`Muat ${limit} aktivitas lagi`}
            onClick={onLoadMore}
          >
            Muat lebih banyak
          </Button>
        </div>
      ) : null}
    </section>
  );
}
