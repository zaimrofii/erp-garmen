import { AlertOctagon } from 'lucide-react';
import { cn } from '@/lib/cn';

/**
 * BottleneckAlert - peringatan simpul macet (Visual Design System v1.0 bagian 2.5).
 * Selalu memuat angka konkret (jumlah bundle + estimasi delay), bukan hanya warna.
 */

interface BottleneckAlertProps {
  wc: string;
  count: number;
  delayHours: number;
  className?: string;
}

export function BottleneckAlert({ wc, count, delayHours, className }: BottleneckAlertProps) {
  return (
    <div
      role="alert"
      className={cn(
        'flex items-start gap-3 rounded-lg border border-accent-coral/30 bg-accent-coral/10 p-4',
        className,
      )}
    >
      <AlertOctagon className="mt-0.5 h-4 w-4 shrink-0 text-accent-coral" aria-hidden="true" />
      <div className="flex flex-col gap-0.5">
        <p className="text-sm font-semibold text-foreground">Bottleneck: {wc}</p>
        <p className="text-xs text-muted-foreground">
          Antrean {count} bundle - estimasi delay {delayHours} jam
        </p>
      </div>
    </div>
  );
}
