import type { LucideIcon } from 'lucide-react';
import { cn } from '@/lib/cn';
import { CARD } from '@/lib/tokens';

/**
 * KpiCard - kartu KPI besar (Screen D, Visual Design System bagian 3.4).
 *
 * `tone` memberi warna pada kotak ikon + teks trend (bukan pada angkanya) sehingga
 * angka tetap kontras di kedua tema. Nilai selalu teks, jadi makna tidak bergantung
 * pada warna saja.
 */

export type KpiTone = 'blue' | 'coral' | 'muted';

const ICON_TONE_CLASS: Record<KpiTone, string> = {
  blue: 'bg-accent-blue/10 text-accent-blue',
  coral: 'bg-accent-coral/10 text-accent-coral',
  muted: 'bg-muted text-muted-foreground',
};

const TREND_TONE_CLASS: Record<KpiTone, string> = {
  blue: 'text-accent-blue',
  coral: 'text-accent-coral',
  muted: 'text-muted-foreground',
};

interface KpiCardProps {
  label: string;
  value: string;
  trend?: string;
  tone?: KpiTone;
  icon?: LucideIcon;
  className?: string;
}

export function KpiCard({
  label,
  value,
  trend,
  tone = 'muted',
  icon: Icon,
  className,
}: KpiCardProps) {
  return (
    <article className={cn(CARD, 'flex flex-col gap-3 p-4', className)}>
      <div className="flex items-center justify-between gap-2">
        <span className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground/80">
          {label}
        </span>

        {Icon !== undefined ? (
          <div
            className={cn(
              'flex h-8 w-8 shrink-0 items-center justify-center rounded-lg',
              ICON_TONE_CLASS[tone],
            )}
          >
            <Icon className="h-4 w-4" aria-hidden="true" />
          </div>
        ) : null}
      </div>

      <p className="text-3xl font-bold tabular-nums tracking-tight text-foreground">{value}</p>

      {trend !== undefined ? (
        <p className={cn('text-xs font-medium', TREND_TONE_CLASS[tone])}>{trend}</p>
      ) : null}
    </article>
  );
}
