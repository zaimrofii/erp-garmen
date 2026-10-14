import type { ReactNode } from 'react';
import { cn } from '@/lib/cn';
import { CARD } from '@/lib/tokens';

/**
 * BarChart - chart batang CSS murni (Fase 21). TANPA library chart.
 *
 * Tinggi batang = `value / max` (default `max` = nilai tertinggi), diwarnai token
 * `var(--accent-blue-gradient)` supaya ikut berubah saat tema gelap.
 *
 * Catatan implementasi:
 * - Batang dibungkus `flex-1 items-end` (bukan `height: %` langsung di kolom) supaya
 *   selalu tumbuh dari dasar dan tidak menabrak label nilai di atasnya.
 * - Nilai juga ditulis sebagai teks di atas batang + `aria-label` per batang, jadi
 *   makna chart tidak bergantung pada tinggi/ warna saja.
 * - `transition-[height]` (bukan `transition-all`).
 * - Empty state sengaja TANPA `CARD` (halaman sudah membungkus chart dengan `CARD`)
 *   agar tidak terlihat card-di-dalam-card.
 */

export interface BarChartPoint {
  label: string;
  value: number;
}

interface BarChartProps {
  data: BarChartPoint[];
  /** Default: nilai tertinggi pada `data`. */
  max?: number;
  /** Tinggi area chart dalam px (default 200). */
  height?: number;
  valueFormatter?: (value: number) => string;
  emptyMessage?: string;
  className?: string;
}

export function BarChart({
  data,
  max,
  height = 200,
  valueFormatter,
  emptyMessage = 'Belum ada data.',
  className,
}: BarChartProps) {
  if (data.length === 0) {
    return (
      <div className={cn('flex min-h-[120px] items-center justify-center', className)}>
        <p className="text-sm text-muted-foreground">{emptyMessage}</p>
      </div>
    );
  }

  const peak = max ?? Math.max(...data.map((point) => point.value));

  return (
    <div
      className={cn('flex items-end gap-2 rounded-xl bg-muted/30 p-3', className)}
      style={{ height: `${height}px` }}
    >
      {data.map((point, index) => {
        const pct = peak > 0 ? (point.value / peak) * 100 : 0;
        const text =
          valueFormatter === undefined ? String(point.value) : valueFormatter(point.value);

        return (
          <div
            key={`${point.label}-${index}`}
            className="flex h-full flex-1 flex-col items-center gap-1"
          >
            <span className="text-[10px] font-semibold tabular-nums text-foreground">{text}</span>

            <div className="flex w-full flex-1 items-end">
              <div
                role="img"
                aria-label={`${point.label}: ${text}`}
                className="w-full rounded-t-md transition-[height] duration-300"
                style={{
                  height: `${pct}%`,
                  minHeight: '2px',
                  backgroundImage: 'var(--accent-blue-gradient)',
                }}
              />
            </div>

            <span className="max-w-full truncate text-[10px] font-medium text-muted-foreground">
              {point.label}
            </span>
          </div>
        );
      })}
    </div>
  );
}

/** Kartu pembungkus chart + judul (dipakai 4 halaman reports agar konsisten). */
interface BarChartCardProps {
  title: string;
  hint?: string;
  children: ReactNode;
  className?: string;
}

export function BarChartCard({ title, hint, children, className }: BarChartCardProps) {
  return (
    <section className={cn(CARD, 'flex flex-col gap-4', className)}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold tracking-tight text-foreground">{title}</h2>
        {hint === undefined ? null : (
          <span className="text-xs text-muted-foreground">{hint}</span>
        )}
      </div>
      {children}
    </section>
  );
}
