/**
 * uuid — generator UUID v4 dengan fallback 3-level (§1.2).
 *
 * Kenapa tidak `crypto.randomUUID()` langsung? Karena API itu **mati di HTTP non-secure**
 * (non-HTTPS/non-localhost) — larangan prototype §12.3. Padahal frontend shopfloor sering
 * dibuka via IP lokal (kios/HP): `http://192.168.x.x`. Fungsi ini dipakai untuk
 * `Idempotency-Key` dan `OfflineAction.id`.
 *
 * Urutan fallback:
 *   1. `crypto.randomUUID()`          → paling cepat & acak kuat.
 *   2. `crypto.getRandomValues()`     → tetap CSPRNG, jalan di insecure context.
 *   3. `Math.random()`                → lingkungan sangat tua (dev/test saja).
 */

/** Bentuk minimal Web Crypto yang dibutuhkan (tanpa `any`). */
interface CryptoLike {
  randomUUID?: () => string;
  getRandomValues?: (array: Uint8Array) => Uint8Array;
}

/** Regex UUID v4: versi wajib `4`, varian wajib `8|9|a|b`. */
export const UUID_V4_REGEX =
  /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

function resolveCrypto(): CryptoLike | null {
  const holder = globalThis as { crypto?: CryptoLike };
  return holder.crypto ?? null;
}

/** Set bit versi (4) & varian (10xx) sesuai RFC 4122. */
function applyVersionAndVariant(bytes: Uint8Array): void {
  bytes[6] = ((bytes[6] ?? 0) & 0x0f) | 0x40;
  bytes[8] = ((bytes[8] ?? 0) & 0x3f) | 0x80;
}

function formatBytes(bytes: Uint8Array): string {
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('');
  return [
    hex.slice(0, 8),
    hex.slice(8, 12),
    hex.slice(12, 16),
    hex.slice(16, 20),
    hex.slice(20, 32),
  ].join('-');
}

function uuidFromGetRandomValues(source: CryptoLike): string | null {
  const getRandomValues = source.getRandomValues;
  if (typeof getRandomValues !== 'function') return null;

  const bytes = new Uint8Array(16);
  // WAJIB di-bind ke crypto-nya, kalau tidak browser melempar "Illegal invocation".
  getRandomValues.call(source, bytes);
  applyVersionAndVariant(bytes);
  return formatBytes(bytes);
}

function uuidFromMathRandom(): string {
  const bytes = new Uint8Array(16);
  for (let index = 0; index < bytes.length; index += 1) {
    bytes[index] = Math.floor(Math.random() * 256);
  }
  applyVersionAndVariant(bytes);
  return formatBytes(bytes);
}

/**
 * Generate UUID v4 yang tetap valid di lingkungan HTTP non-secure.
 * Satu-satunya fungsi di Fase 1 yang boleh tidak deterministik (menghasilkan nilai acak).
 */
export function generateUUID(): string {
  const source = resolveCrypto();

  const native = source?.randomUUID;
  if (source && typeof native === 'function') {
    const generated = native.call(source);
    if (typeof generated === 'string' && UUID_V4_REGEX.test(generated)) {
      return generated;
    }
  }

  if (source) {
    const fallback = uuidFromGetRandomValues(source);
    if (fallback !== null) return fallback;
  }

  return uuidFromMathRandom();
}

/** Helper murni untuk test / validasi cepat. */
export function isUUIDV4(value: string): boolean {
  return UUID_V4_REGEX.test(value);
}
