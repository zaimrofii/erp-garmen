import { describe, expect, it } from 'vitest';
import {
  isAbsoluteMediaUrl,
  mediaOrigin,
  mediaUrl,
  resolveMediaUrl,
} from '@/lib/media-url';

/**
 * FASE K5.5 — `lib/media-url` (PURE).
 *
 * Konteks bug: backend mengirim `/media/...` (relatif) sementara frontend dev ada di
 * origin lain (:5173) — `<img src="/media/...">` meminta ke Vite → balasan HTML, bukan
 * gambar. Helper ini menempelkan origin backend dari `VITE_API_BASE_URL`.
 */

const BASE = 'http://localhost:8000/api/v1';

describe('K5.5 — mediaUrl/isAbsoluteMediaUrl/mediaOrigin (PURE)', () => {
  it('URL absolut (http/https) & data/blob → apa adanya', () => {
    for (const url of [
      'http://cdn.klien.com/kaos.png',
      'https://cdn.klien.com/kaos.png',
      'data:image/png;base64,AAA',
      'blob:http://localhost:5173/1234',
    ]) {
      expect(isAbsoluteMediaUrl(url), url).toBe(true);
      expect(resolveMediaUrl(url, BASE), url).toBe(url);
    }
  });

  it('URL relatif `/media/...` → origin backend + path', () => {
    expect(resolveMediaUrl('/media/products/2026/10/kaos.jpg', BASE)).toBe(
      'http://localhost:8000/media/products/2026/10/kaos.jpg',
    );
  });

  it('base URL tanpa path / dengan trailing slash → TIDAK muncul slash ganda', () => {
    expect(resolveMediaUrl('/media/x.jpg', 'http://localhost:8000/')).toBe(
      'http://localhost:8000/media/x.jpg',
    );
    expect(resolveMediaUrl('/media/x.jpg', 'http://localhost:8000')).toBe(
      'http://localhost:8000/media/x.jpg',
    );
  });

  it('relatif TANPA leading slash → tetap ditempel dengan satu slash', () => {
    expect(resolveMediaUrl('media/x.jpg', BASE)).toBe('http://localhost:8000/media/x.jpg');
  });

  it('port non-standar dipertahankan; path panjang tidak mengubah origin', () => {
    expect(mediaOrigin('http://192.168.1.5:8080/api/v1')).toBe('http://192.168.1.5:8080');
    expect(resolveMediaUrl('/media/a.jpg', 'http://192.168.1.5:8080/api/v1')).toBe(
      'http://192.168.1.5:8080/media/a.jpg',
    );
  });

  it('null/undefined/string kosong/spasi → undefined (pakai ikon pengganti)', () => {
    for (const value of [null, undefined, '', '   ']) {
      expect(mediaUrl(value, BASE)).toBeUndefined();
    }
  });

  it('protocol-relative `//host/...` dibiarkan; base URL relatif → path apa adanya', () => {
    expect(mediaUrl('//cdn.klien.com/kaos.png', BASE)).toBe('//cdn.klien.com/kaos.png');
    expect(mediaOrigin('')).toBe('');
    expect(mediaOrigin('/api/v1')).toBe('');
    expect(mediaUrl('/media/x.jpg', '/api/v1')).toBe('/media/x.jpg');
  });

  it('base URL default dari VITE_API_BASE_URL (test env) tetap aman', () => {
    // Di test, `VITE_API_BASE_URL` bisa kosong → helper mengembalikan path apa adanya.
    expect(mediaUrl('/media/x.jpg', '')).toBe('/media/x.jpg');
    expect(typeof mediaUrl('/media/x.jpg')).toBe('string');
  });
});
