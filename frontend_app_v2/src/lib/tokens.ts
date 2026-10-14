/**
 * tokens.ts - konstanta design system (Visual Design System v1.0 bagian 1.8, disalin persis).
 *
 * Semua warna HANYA lewat token OKLCH di `styles/tailwind.css`:
 * tanpa hex/rgb, tanpa palet warna bawaan Tailwind, dan tanpa utility varian
 * tema gelap berbasis prefix (tema di-swap lewat token).
 *
 * Dipakai ulang oleh atom/molecule Fase 15+ supaya kelas tidak ditulis ulang per halaman.
 */

export const CARD = 'glass-card rounded-card p-6';

export const BADGE =
  'inline-flex items-center gap-1.5 rounded-pill px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wider';

export const PILL = 'inline-flex items-center justify-center rounded-pill transition-colors';

export const PILL_PRIMARY = `${PILL} bg-primary text-primary-foreground shadow-pill hover:opacity-90`;

export const PILL_SECONDARY = `${PILL} border border-border/80 bg-card hover:bg-muted`;

export const PILL_GHOST = `${PILL} text-muted-foreground hover:text-foreground`;

export const TABLE_HEAD =
  'h-10 px-4 py-2 text-left text-[11px] font-semibold uppercase tracking-wider text-muted-foreground/80';

export const TABLE_CELL =
  'h-12 border-t border-border/40 px-4 py-3 text-sm text-foreground tabular-nums';
