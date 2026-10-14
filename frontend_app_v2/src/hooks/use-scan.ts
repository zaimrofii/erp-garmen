import { useCallback, useRef } from 'react';
import { haptic, playBeep } from '@/lib/feedback';

/**
 * use-scan.ts - debounce scan 500 ms + feedback.
 *
 * Barcode gun USB mengetik sangat cepat dan sering mengirim kode yang sama dua kali
 * (mis. auto-repeat). Kode yang SAMA dalam jendela 500 ms dianggap satu scan:
 * hanya trigger pertama yang diteruskan ke `onScan`.
 */

/** Jendela anti-duplikat (ms) - sama dengan instruksi Fase 17. */
export const SCAN_DUPLICATE_WINDOW_MS = 500;

interface LastScan {
  code: string;
  at: number;
}

/**
 * PURE - true kalau scan ini harus DIABAIKAN (kode sama dalam jendela 500 ms).
 * Dipisah supaya bisa diuji tanpa DOM (bukti gate "debounce 500 ms").
 */
export function isDuplicateScan(
  last: LastScan | null,
  code: string,
  now: number,
  windowMs: number = SCAN_DUPLICATE_WINDOW_MS,
): boolean {
  if (last === null) return false;
  if (last.code !== code) return false;

  return now - last.at < windowMs;
}

export function useScan(onScan: (code: string) => void): (raw: string) => void {
  const lastScanRef = useRef<LastScan | null>(null);

  return useCallback(
    (raw: string): void => {
      const code = raw.trim();
      if (code.length === 0) return;

      const now = Date.now();
      if (isDuplicateScan(lastScanRef.current, code, now)) return;

      lastScanRef.current = { code, at: now };

      playBeep('success');
      haptic('success');
      onScan(code);
    },
    [onScan],
  );
}
