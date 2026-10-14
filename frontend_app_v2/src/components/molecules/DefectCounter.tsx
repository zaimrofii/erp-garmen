import { Minus, Plus } from 'lucide-react';
import { cn } from '@/lib/cn';
import { PILL_PRIMARY, PILL_SECONDARY } from '@/lib/tokens';

/**
 * DefectCounter - counter qty per jenis cacat (multi-qty, Visual Design System bagian 3.3).
 *
 * Tombol minus/plus 36x36 px (>=48 px area sentuh efektif karena berada di dalam baris
 * ber-`gap-2`), nilai tengah `tabular-nums` supaya tidak "melompat" saat berubah.
 * Kedua tombol icon-only -> WAJIB `aria-label`.
 */

interface DefectCounterProps {
  value: number;
  onChange: (value: number) => void;
  min?: number;
  max?: number;
  label?: string;
  disabled?: boolean;
  className?: string;
}

export function DefectCounter({
  value,
  onChange,
  min = 0,
  max,
  label,
  disabled = false,
  className,
}: DefectCounterProps) {
  const upperBound = max ?? 999;
  const atMin = value <= min;
  const atMax = value >= upperBound;

  return (
    <div className={cn('flex items-center gap-2', className)}>
      <button
        type="button"
        onClick={() => onChange(Math.max(min, value - 1))}
        disabled={disabled || atMin}
        aria-label={label === undefined ? 'Kurangi' : `Kurangi ${label}`}
        className={cn(
          PILL_SECONDARY,
          'h-9 w-9 shrink-0 disabled:opacity-50',
          'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2',
        )}
      >
        <Minus className="h-4 w-4" aria-hidden="true" />
      </button>

      <span className="min-w-8 text-center text-sm font-semibold tabular-nums text-foreground">
        {value}
      </span>

      <button
        type="button"
        onClick={() => onChange(Math.min(upperBound, value + 1))}
        disabled={disabled || atMax}
        aria-label={label === undefined ? 'Tambah' : `Tambah ${label}`}
        className={cn(
          PILL_PRIMARY,
          'h-9 w-9 shrink-0 disabled:opacity-50',
          'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2',
        )}
      >
        <Plus className="h-4 w-4" aria-hidden="true" />
      </button>
    </div>
  );
}
