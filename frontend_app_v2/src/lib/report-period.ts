/**
 * report-period.ts - filter periode bersama 4 halaman reports (Fase 21).
 *
 * ANCHOR = tanggal TERBARU di data (bukan jam dinding). Fixture dummy punya tanggal
 * tetap, jadi filter tetap deterministik dan bisa diuji tanpa bergantung waktu mesin.
 * Saat backend siap, cukup ganti anchor dengan `new Date()` / parameter dari server.
 *
 * PURE - tidak mengimpor React/apa pun, jadi aman dipakai di komponen & tes.
 */

export const PERIOD_ALL = 'all';

export interface PeriodFilter {
  id: string;
  label: string;
}

export const PERIOD_FILTERS: PeriodFilter[] = [
  { id: '7d', label: '7 hari' },
  { id: '30d', label: '30 hari' },
  { id: '90d', label: '90 hari' },
  { id: PERIOD_ALL, label: 'Semua' },
];

const MS_PER_DAY = 24 * 60 * 60 * 1000;

const PERIOD_DAYS: Record<string, number | null> = {
  '7d': 7,
  '30d': 30,
  '90d': 90,
  [PERIOD_ALL]: null,
};

/** Tanggal terbaru dari daftar ISO (bandingkan sebagai teks - format ISO sebanding). */
export function newestDate(isoDates: readonly string[]): string {
  return isoDates.reduce((newest, current) => (current > newest ? current : newest), '');
}

/** True kalau `isoDate` masuk jendela periode relatif ke `anchor`. */
export function withinPeriod(isoDate: string, anchor: string, period: string): boolean {
  const days = PERIOD_DAYS[period] ?? null;
  if (days === null || anchor.length === 0) return true;

  const limit = new Date(anchor).getTime() - days * MS_PER_DAY;

  return new Date(isoDate).getTime() >= limit;
}

/** Jumlah titik chart yang ditampilkan untuk periode ini (dipakai halaman WIP). */
export function periodPointCount(period: string, available: number): number {
  if (period === '7d') return Math.min(1, available);
  if (period === '30d') return Math.min(4, available);
  if (period === '90d') return Math.min(13, available);

  return available;
}
