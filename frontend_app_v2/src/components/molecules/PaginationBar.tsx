import { ChevronLeft, ChevronRight } from 'lucide-react';
import { cn } from '@/lib/cn';
import { PILL_SECONDARY } from '@/lib/tokens';

/**
 * PaginationBar - kontrol pagination offset-based untuk tabel dense (Fase 20).
 *
 * Dibuat sebagai komponen (bukan disalin ke 7 halaman) supaya label "Menampilkan x-y
 * dari n" + tombol prev/next konsisten. Tombol icon-only -> WAJIB `aria-label`.
 */

interface PaginationBarProps {
  page: number;
  totalPages: number;
  rangeStart: number;
  rangeEnd: number;
  total: number;
  canPrev: boolean;
  canNext: boolean;
  onPrev: () => void;
  onNext: () => void;
  className?: string;
}

const NAV_BUTTON_CLASS =
  'h-9 w-9 shrink-0 p-0 disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2';

export function PaginationBar({
  page,
  totalPages,
  rangeStart,
  rangeEnd,
  total,
  canPrev,
  canNext,
  onPrev,
  onNext,
  className,
}: PaginationBarProps) {
  return (
    <div className={cn('flex flex-wrap items-center justify-between gap-2', className)}>
      <p className="text-xs tabular-nums text-muted-foreground">
        {total === 0 ? 'Tidak ada baris' : `Menampilkan ${rangeStart}-${rangeEnd} dari ${total}`}
      </p>

      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={onPrev}
          disabled={!canPrev}
          aria-label="Halaman sebelumnya"
          className={cn(PILL_SECONDARY, NAV_BUTTON_CLASS)}
        >
          <ChevronLeft className="h-4 w-4" aria-hidden="true" />
        </button>

        <span className="text-xs tabular-nums text-muted-foreground">
          Halaman {page} / {totalPages}
        </span>

        <button
          type="button"
          onClick={onNext}
          disabled={!canNext}
          aria-label="Halaman berikutnya"
          className={cn(PILL_SECONDARY, NAV_BUTTON_CLASS)}
        >
          <ChevronRight className="h-4 w-4" aria-hidden="true" />
        </button>
      </div>
    </div>
  );
}
