import { useCallback, useEffect, useState } from 'react';

/**
 * use-theme-mode.ts - dark/light mode lewat TOKEN swap.
 *
 * Tema gelap di `styles/tailwind.css` aktif saat `<html class="dark">`, jadi hook ini
 * hanya menyalakan/mematikan kelas itu - TIDAK ada utility varian tema gelap berbasis
 * prefix di komponen dan `tailwind.css` tidak disentuh (Aturan Mutlak #2 & #3).
 *
 * Prioritas nilai awal: `localStorage['mes-theme']` -> `prefers-color-scheme`.
 * Semua akses `window`/`document` dijaga (`typeof ... === 'undefined'`) supaya aman
 * dipanggil di luar browser (test/build) dan tidak pernah throw.
 *
 * Seam: nanti bisa dipindah ke React Context kalau tema perlu dibaca banyak komponen.
 */

export type ThemeMode = 'light' | 'dark';

export const THEME_STORAGE_KEY = 'mes-theme';
export const DARK_CLASS = 'dark';

function isThemeMode(value: unknown): value is ThemeMode {
  return value === 'light' || value === 'dark';
}

function readStoredTheme(): ThemeMode | null {
  if (typeof window === 'undefined') return null;

  try {
    const raw = window.localStorage.getItem(THEME_STORAGE_KEY);

    return isThemeMode(raw) ? raw : null;
  } catch {
    return null;
  }
}

function readPreferredTheme(): ThemeMode {
  if (typeof window === 'undefined') return 'light';
  if (typeof window.matchMedia !== 'function') return 'light';

  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

/** PURE (kecuali baca storage/OS) - tema awal: preferensi tersimpan menang. */
export function resolveInitialTheme(): ThemeMode {
  const stored = readStoredTheme();

  return stored ?? readPreferredTheme();
}

/** Terapkan tema ke `<html>`; no-op kalau tidak ada DOM. */
export function applyThemeMode(mode: ThemeMode): void {
  if (typeof document === 'undefined') return;

  document.documentElement.classList.toggle(DARK_CLASS, mode === 'dark');
}

export function persistThemeMode(mode: ThemeMode): void {
  if (typeof window === 'undefined') return;

  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, mode);
  } catch {
    /* diabaikan dengan sengaja */
  }
}

export interface UseThemeModeResult {
  mode: ThemeMode;
  isDark: boolean;
  toggle: () => void;
  setMode: (mode: ThemeMode) => void;
}

export function useThemeMode(): UseThemeModeResult {
  const [mode, setModeState] = useState<ThemeMode>(() => resolveInitialTheme());

  // Efek = sinkronisasi dengan sistem eksternal (class di <html> + localStorage).
  useEffect(() => {
    applyThemeMode(mode);
    persistThemeMode(mode);
  }, [mode]);

  const setMode = useCallback((next: ThemeMode): void => {
    setModeState(next);
  }, []);

  const toggle = useCallback((): void => {
    setModeState((current) => (current === 'dark' ? 'light' : 'dark'));
  }, []);

  return { mode, isDark: mode === 'dark', toggle, setMode };
}
