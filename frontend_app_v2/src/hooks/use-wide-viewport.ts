import { useEffect, useState } from 'react';

/**
 * use-wide-viewport.ts - true kalau viewport >= breakpoint `lg` (1024px).
 *
 * Dipakai halaman operator untuk memilih ukuran tombol yang tidak bisa diubah lewat CSS:
 * HP = `hp` (min-h-12 / 48px), Kios tablet & desktop = `kiosk` (min-h-14 / 56px).
 * Tata letaknya sendiri sudah responsif lewat class Tailwind (`lg:grid lg:grid-cols-12`).
 */

const WIDE_QUERY = '(min-width: 1024px)';

function readIsWide(): boolean {
  if (typeof window === 'undefined') return false;
  if (typeof window.matchMedia !== 'function') return false;

  return window.matchMedia(WIDE_QUERY).matches;
}

export function useWideViewport(): boolean {
  const [isWide, setIsWide] = useState<boolean>(() => readIsWide());

  useEffect(() => {
    if (typeof window === 'undefined') return undefined;
    if (typeof window.matchMedia !== 'function') return undefined;

    const mediaQuery = window.matchMedia(WIDE_QUERY);
    const handleChange = (event: MediaQueryListEvent): void => {
      setIsWide(event.matches);
    };

    mediaQuery.addEventListener('change', handleChange);

    return () => {
      mediaQuery.removeEventListener('change', handleChange);
    };
  }, []);

  return isWide;
}
