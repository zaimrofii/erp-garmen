/**
 * apply-theme.ts — token tema per-client (§ theming OKLCH).
 *
 * Aturan:
 * - **Hanya OKLCH** — nilai non-OKLCH ditolak dan token-nya tidak di-set (biarkan token
 *   `src/styles/tailwind.css` yang berlaku sebagai default). File tailwind.css TIDAK diubah.
 * - `resolveThemeTokens()` MURNI (bisa diuji tanpa DOM); `applyTheme()` menulis ke
 *   `document.documentElement.style` dan **SSR-safe** (`typeof document === 'undefined'` → no-op).
 * - Tidak pernah throw (config invalid → fallback).
 */

/** Cukup `{ primary }` — `ClientConfig` (app/config.ts) memenuhi bentuk ini tanpa impor silang. */
export interface ThemeSource {
  primary?: string;
}

export interface ParsedOklch {
  l: number;
  c: number;
  h: number;
}

export interface ThemeRoot {
  style: { setProperty: (name: string, value: string) => void };
}

export const THEME_TOKEN_KEYS = [
  '--color-primary',
  '--color-primary-foreground',
  '--color-ring',
  '--color-accent-blue',
] as const;

/** Ambang lightness: di bawah ini pakai foreground terang, di atas pakai gelap. */
const LIGHT_FOREGROUND_THRESHOLD = 0.62;

/** `oklch(0.6 0.15 250)` / `oklch(60% 0.15 250)` → `{ l, c, h }`; tidak valid → `null`. */
export function parseOklch(value: unknown): ParsedOklch | null {
  if (typeof value !== 'string') return null;

  const match = /^oklch\(\s*([\d.]+)(%?)\s+([\d.]+)\s+([\d.]+)/i.exec(value.trim());
  if (match === null) return null;

  const rawLightness = Number(match[1]);
  const lightness = match[2] === '%' ? rawLightness / 100 : rawLightness;
  const chroma = Number(match[3]);
  const hue = Number(match[4]);

  if (!Number.isFinite(lightness) || !Number.isFinite(chroma) || !Number.isFinite(hue)) return null;

  return { l: lightness, c: chroma, h: hue };
}

function formatToken({ l, c, h }: ParsedOklch): string {
  return `oklch(${l.toFixed(3)} ${c.toFixed(3)} ${h.toFixed(1)})`;
}

/** Foreground turunan: kontras terhadap lightness brand. */
export function derivePrimaryForeground(primary: string): string | null {
  const parsed = parseOklch(primary);
  if (parsed === null) return null;

  return parsed.l < LIGHT_FOREGROUND_THRESHOLD
    ? formatToken({ l: 0.99, c: 0.01, h: parsed.h })
    : formatToken({ l: 0.22, c: 0.03, h: parsed.h });
}

/**
 * Token CSS dari config client. `primary` tidak valid → map kosong (pakai default tailwind.css).
 * Semua nilai berupa OKLCH.
 */
export function resolveThemeTokens(source: ThemeSource): Record<string, string> {
  const primary = source.primary;
  const parsed = parseOklch(primary);
  const foreground = isOklchString(primary) ? derivePrimaryForeground(primary) : null;

  if (parsed === null || foreground === null) return {};

  const normalized = formatToken(parsed);

  return {
    '--color-primary': normalized,
    '--color-primary-foreground': foreground,
    '--color-ring': normalized,
    '--color-accent-blue': normalized,
  };
}

function isOklchString(value: unknown): value is string {
  return parseOklch(value) !== null;
}

function resolveRoot(override?: ThemeRoot): ThemeRoot | null {
  if (override !== undefined) return override;

  const globalLike = globalThis as { document?: { documentElement?: ThemeRoot } };

  return globalLike.document?.documentElement ?? null;
}

/**
 * Terapkan token ke CSS custom properties di root dokumen.
 * Tanpa `document` (SSR/test) → no-op. Tidak pernah throw.
 */
export function applyTheme(tokens: Record<string, string>, root?: ThemeRoot): void {
  const target = resolveRoot(root);

  if (target === null) return;

  try {
    for (const [name, value] of Object.entries(tokens)) {
      target.style.setProperty(name, value);
    }
  } catch {
    /* diabaikan dengan sengaja — theming tidak boleh menjatuhkan aplikasi */
  }
}
