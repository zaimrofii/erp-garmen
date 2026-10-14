/**
 * download.ts - helper unduhan berkas (H4.8) — **PURE-injectable**.
 *
 * Dipakai `ExportButton` & `api/real/export.ts`: respons binary dari
 * `POST /api/v1/export/<report>/` ditulis ke disk lewat `<a download>` sementara
 * (BUKAN `window.open`, supaya cookie sesi tetap dipakai lewat POST dari ApiClient).
 *
 * Catatan lingkungan: vitest berjalan `environment: 'node'` (tanpa DOM), jadi
 * dependensi DOM **disuntikkan** (`DownloadDeps`) supaya fungsi ini bisa diuji
 * tanpa jsdom — pola sama dengan `tests/helpers/react-tree.ts` (tanpa DOM).
 */

export interface DownloadDeps {
  /** Default `URL.createObjectURL` (browser). */
  createObjectURL?: (blob: Blob) => string;
  /** Default `URL.revokeObjectURL` (browser). */
  revokeObjectURL?: (url: string) => void;
  /** Default `document` (browser). */
  document?: Document;
}

/** Nama berkas dari header `Content-Disposition` (menerima RFC 5987 `filename*`). */
export function readFilenameFromDisposition(value: string | null): string | null {
  if (value === null || value === '') return null;

  const encoded = /filename\*=(?:UTF-8'')?([^;]+)/i.exec(value);
  if (encoded !== null) {
    const raw = encoded[1].trim().replace(/^"|"$/g, '');
    try {
      return decodeURIComponent(raw);
    } catch {
      return raw;
    }
  }

  const plain = /filename=([^;]+)/i.exec(value);
  if (plain === null) return null;

  const name = plain[1].trim().replace(/^"|"$/g, '');
  return name === '' ? null : name;
}

/**
 * Tulis `blob` ke disk sebagai `filename`; return object URL yang dipakai
 * (sudah di-`revoke` sebelum fungsi selesai — jejak DOM dibersihkan).
 */
export function downloadBlob(blob: Blob, filename: string, deps: DownloadDeps = {}): string {
  const createObjectURL = deps.createObjectURL ?? ((value: Blob) => URL.createObjectURL(value));
  const revokeObjectURL = deps.revokeObjectURL ?? ((value: string) => URL.revokeObjectURL(value));
  const documentRef = deps.document ?? document;

  const url = createObjectURL(blob);
  const anchor = documentRef.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.rel = 'noopener';
  documentRef.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  revokeObjectURL(url);

  return url;
}
