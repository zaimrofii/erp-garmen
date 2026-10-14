import { generateUUID } from '@/lib/uuid';

/**
 * device-identity.ts — identitas perangkat untuk header & binding (Fase G).
 *
 * **Sumber identitas sebenarnya adalah cookie** `device_token` yang di-set
 * backend saat `POST /api/v1/devices/bind`. Cookie itu `HttpOnly`, jadi:
 *   * browser mengirimnya otomatis di setiap request (tanpa kode di klien);
 *   * JavaScript **tidak bisa** membacanya — dan itu disengaja (XSS tidak bisa
 *     mencuri token device).
 *
 * Karena itu modul ini hanya menyiapkan dua nilai yang memang boleh dibaca klien:
 *
 *   * `readAccessToken()` — token login user (`localStorage['mes-access-token']`),
 *     dikirim sebagai `Authorization: Bearer`. Belum ada login di frontend
 *     (Fase I), jadi sekarang `null` → header tidak dikirim (seam hidup, bukan mati);
 *   * `ensureDeviceId()` — id perangkat **opaque** untuk header `X-Device-Id`
 *     (diagnosa/audit di backend). Dibuat sekali lalu disimpan di localStorage.
 *
 * Semua fungsi aman di runtime tanpa DOM (SSR/test): `document`/`localStorage`
 * yang tidak ada hanya menghasilkan `null`/no-op, tanpa throw.
 */

export const ACCESS_TOKEN_KEY = 'mes-access-token';
export const DEVICE_ID_KEY = 'mes-device-id';

/** Nama cookie binding (samakan dengan `DEVICE_COOKIE_NAME` backend). */
export const DEVICE_COOKIE_NAME = 'device_token';

interface StorageLike {
  getItem: (key: string) => string | null;
  setItem: (key: string, value: string) => void;
}

function readCookieString(): string {
  const doc = (globalThis as { document?: { cookie?: string } }).document;
  return typeof doc?.cookie === 'string' ? doc.cookie : '';
}

function getStorage(): StorageLike | null {
  const candidate = (globalThis as { localStorage?: StorageLike }).localStorage;
  return candidate ?? null;
}

function normalize(value: unknown): string | null {
  if (typeof value !== 'string') return null;

  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

/** PURE — ambil nilai cookie dari string `document.cookie` (tanpa decode aneh). */
export function readCookieValue(name: string, cookieString: string = readCookieString()): string | null {
  if (cookieString.length === 0) return null;

  for (const part of cookieString.split(';')) {
    const separator = part.indexOf('=');
    if (separator < 0) continue;

    if (part.slice(0, separator).trim() === name) {
      return normalize(decodeURIComponent(part.slice(separator + 1)));
    }
  }

  return null;
}

/** Baca nilai localStorage (tanpa throw di runtime tanpa storage). */
export function readStorageValue(key: string, storage: StorageLike | null = getStorage()): string | null {
  if (storage === null) return null;

  try {
    return normalize(storage.getItem(key));
  } catch {
    return null;
  }
}

/** Tulis nilai localStorage (gagal → diabaikan, bukan error fatal). */
export function writeStorageValue(
  key: string,
  value: string,
  storage: StorageLike | null = getStorage()
): boolean {
  if (storage === null) return false;

  try {
    storage.setItem(key, value);
    return true;
  } catch {
    return false;
  }
}

/** Token login user; `null` selama belum ada login (Fase I). */
export function readAccessToken(): string | null {
  return readStorageValue(ACCESS_TOKEN_KEY);
}

/**
 * Id perangkat stabil untuk header `X-Device-Id` (dibuat sekali, lalu dipakai
 * terus). Bukan rahasia & bukan bukti identitas — hanya penanda diagnosa.
 */
export function ensureDeviceId(): string | null {
  const existing = readStorageValue(DEVICE_ID_KEY);
  if (existing !== null) return existing;

  const created = generateUUID();
  return writeStorageValue(DEVICE_ID_KEY, created) ? created : created;
}

/** `true` kalau cookie binding terlihat di `document.cookie` (biasanya `false`: HttpOnly). */
export function hasReadableDeviceCookie(): boolean {
  return readCookieValue(DEVICE_COOKIE_NAME) !== null;
}
