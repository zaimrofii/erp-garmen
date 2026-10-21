/** Helper tampilan observability AI (PURE) — dipakai halaman & test. */

export interface DateRange {
  from: string;
  to: string;
}

/** Rentang default 7 hari (termasuk hari ini) dalam format YYYY-MM-DD. */
export function defaultRange(days = 7, now: Date = new Date()): DateRange {
  const to = now.toISOString().slice(0, 10);
  const start = new Date(now.getTime() - (days - 1) * 24 * 60 * 60 * 1000);

  return { from: start.toISOString().slice(0, 10), to };
}

/** Titik `polyline` SVG dari deret nilai (0..1 pada sumbu Y). */
export function chartPoints(
  values: readonly number[],
  width = 320,
  height = 80,
): string {
  if (values.length === 0) return '';

  const max = Math.max(...values, 0.000001);
  const step = values.length === 1 ? 0 : width / (values.length - 1);

  return values
    .map((value, index) => {
      const x = Math.round(index * step);
      const y = Math.round(height - (value / max) * height);
      return `${x},${y}`;
    })
    .join(' ');
}

export function formatUsd(value: number): string {
  return `$${value.toFixed(4)}`;
}

export function formatPct(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}
