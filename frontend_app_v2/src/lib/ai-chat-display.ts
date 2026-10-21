/** Helper tampilan chat AI (PURE) — dipakai komponen & test. */

/** Kelas warna badge confidence: hijau > 0.8, kuning 0.6–0.8, merah < 0.6. */
export function confidenceClass(score: number | null): string {
  if (score === null) return 'text-muted-foreground';
  if (score > 0.8) return 'text-success';
  if (score >= 0.6) return 'text-warning';
  return 'text-danger';
}
