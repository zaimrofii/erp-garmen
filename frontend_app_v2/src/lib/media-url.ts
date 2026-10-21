/**
 * media-url.ts — PURE helper URL media backend (K5.5).
 *
 * **Masalah yang diperbaiki:** backend mengirim URL media **relatif**
 * (`/media/products/2026/10/x.jpg`, dari `MEDIA_URL="/media/"`), sedangkan frontend
 * dev berjalan di origin lain (`http://localhost:5173`). Akibatnya
 * `<img src="/media/...">` meminta ke origin FRONTEND → Vite membalas HTML (SPA
 * fallback) dengan status 200 → gambar tampak kosong (bukan 404 yang jelas).
 *
 * **Solusi:** turunkan ORIGIN backend dari `VITE_API_BASE_URL`
 * (`http://localhost:8000/api/v1` → `http://localhost:8000`) lalu tempelkan ke URL
 * relatif. URL absolut (`http`/`https`), `data:`, `blob:`, dan protocol-relative
 * (`//host/...`) dibiarkan apa adanya.
 *
 * Semua fungsi murni (tanpa DOM) sehingga bisa diuji tanpa jsdom.
 */
import { readApiBaseUrl } from '@/app/config';

/** PURE — `true` untuk URL yang sudah mandiri (tidak butuh origin backend). */
export function isAbsoluteMediaUrl(value: string): boolean {
  return /^(https?:|data:|blob:)/i.test(value.trim());
}

/**
 * PURE — origin dari base URL API. Base URL relatif/tidak valid → `''`
 * (pemanggil memakai path apa adanya, perilaku lama).
 */
export function mediaOrigin(baseUrl: string): string {
  const trimmed = String(baseUrl ?? '').trim();
  if (trimmed.length === 0) return '';

  try {
    return new URL(trimmed).origin;
  } catch {
    return '';
  }
}

/**
 * PURE — URL media siap pakai untuk `<img src>`.
 *
 * `null`/`undefined`/kosong → `undefined` (komponen memakai ikon pengganti).
 */
export function resolveMediaUrl(
  path: string | null | undefined,
  baseUrl: string,
): string | undefined {
  if (typeof path !== 'string') return undefined;

  const trimmed = path.trim();
  if (trimmed.length === 0) return undefined;
  if (isAbsoluteMediaUrl(trimmed) || trimmed.startsWith('//')) return trimmed;

  const origin = mediaOrigin(baseUrl);
  if (origin.length === 0) return trimmed;

  return trimmed.startsWith('/') ? `${origin}${trimmed}` : `${origin}/${trimmed}`;
}

/**
 * Versi praktis — origin diambil dari `VITE_API_BASE_URL` (`readApiBaseUrl()`).
 * Parameter `baseUrl` bisa diisi eksplisit (dipakai test & lingkungan khusus).
 */
export function mediaUrl(
  path: string | null | undefined,
  baseUrl: string = readApiBaseUrl(),
): string | undefined {
  return resolveMediaUrl(path, baseUrl);
}
