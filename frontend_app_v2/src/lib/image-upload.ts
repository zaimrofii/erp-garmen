/**
 * image-upload.ts - helper PURE unggah gambar master (K5.3).
 *
 * Dipakai `components/molecules/ImageUpload.tsx` + adapter produk/partner. Semua
 * fungsi di sini murni (tanpa DOM/React) supaya bisa diuji tanpa jsdom.
 *
 * Aturan validasi KLIEN ini mencerminkan `master/image_services.py` (backend tetap
 * memverifikasi ulang isi berkas lewat Pillow):
 *   * ekstensi jpg/jpeg/png/webp;
 *   * maks 5 MB (`IMAGE_MAX_BYTES`);
 *   * berkas 0 byte ditolak.
 */

/** `accept` untuk `<input type="file">` (MIME resmi ketiga format). */
export const IMAGE_ACCEPT = 'image/jpeg,image/png,image/webp';

/** Ekstensi yang diterima (backend: `ALLOWED_EXTENSIONS`). */
export const IMAGE_ALLOWED_EXTENSIONS = ['.jpg', '.jpeg', '.png', '.webp'] as const;

/** Batas ukuran berkas = `MAX_IMAGE_BYTES` backend (5 MB). */
export const IMAGE_MAX_BYTES = 5 * 1024 * 1024;

/** Label batas ukuran untuk pesan UI. */
export const IMAGE_MAX_LABEL = '5 MB';

/** Nama field multipart yang dibaca backend (`request.FILES['image']`). */
export const IMAGE_FIELD_NAME = 'image';

export type ImageValidation = { ok: true } | { ok: false; error: string };

/** Bentuk minimal berkas yang dibutuhkan validasi (memudahkan test tanpa `File`). */
export interface ImageFileLike {
  name: string;
  size: number;
}

/** Hasil satu percobaan memilih berkas: diterima / ditolak / tidak ada berkas. */
export type ImagePickResult = 'accepted' | 'rejected' | 'empty';

function extensionOf(name: string): string {
  const dot = name.lastIndexOf('.');

  return dot < 0 ? '' : name.slice(dot).toLowerCase();
}

/** PURE - validasi berkas di klien; pesan error sama nada dengan pesan backend. */
export function validateImageFile(file: ImageFileLike | null | undefined): ImageValidation {
  if (file === null || file === undefined) {
    return { ok: false, error: 'Tidak ada berkas yang dipilih.' };
  }

  const extension = extensionOf(String(file.name ?? ''));
  if (!(IMAGE_ALLOWED_EXTENSIONS as readonly string[]).includes(extension)) {
    return {
      ok: false,
      error: `Format tidak didukung. Gunakan ${IMAGE_ALLOWED_EXTENSIONS.join(', ')}.`,
    };
  }

  if (!Number.isFinite(file.size) || file.size <= 0) {
    return { ok: false, error: 'Berkas kosong.' };
  }

  if (file.size > IMAGE_MAX_BYTES) {
    return { ok: false, error: `Ukuran berkas melebihi ${IMAGE_MAX_LABEL}.` };
  }

  return { ok: true };
}

/** Duck-typing `File` (aman diuji tanpa DOM; bun punya `File` global). */
function asFile(value: unknown): File | null {
  if (typeof value !== 'object' || value === null) return null;

  const candidate = value as { name?: unknown; size?: unknown };
  if (typeof candidate.name !== 'string' || typeof candidate.size !== 'number') return null;

  return value as File;
}

/** PURE - berkas PERTAMA dari `FileList`/array/objek ber-index; `null` kalau kosong. */
export function firstFileFrom(container: unknown): File | null {
  if (typeof container !== 'object' || container === null) return null;

  const list = container as { length?: unknown; [index: number]: unknown };
  const length = typeof list.length === 'number' ? list.length : 0;
  if (length <= 0) return null;

  return asFile(list[0]);
}

/** PURE - berkas dari event `<input type="file">` (`event.target.files`). */
export function fileFromInputEvent(event: unknown): File | null {
  if (typeof event !== 'object' || event === null) return null;

  const target = (event as { target?: unknown }).target;
  if (typeof target !== 'object' || target === null) return null;

  return firstFileFrom((target as { files?: unknown }).files);
}

/** PURE - berkas dari event drop (`event.dataTransfer.files`). */
export function fileFromDropEvent(event: unknown): File | null {
  if (typeof event !== 'object' || event === null) return null;

  const transfer = (event as { dataTransfer?: unknown }).dataTransfer;
  if (typeof transfer !== 'object' || transfer === null) return null;

  return firstFileFrom((transfer as { files?: unknown }).files);
}

/**
 * PURE - validasi lalu teruskan berkas ke `onAccept`; berkas cacat TIDAK pernah
 * memanggil `onAccept` (dilaporkan lewat `onReject`).
 */
export function pickImageFile(
  file: File | null,
  handlers: { onAccept: (file: File) => void; onReject: (error: string) => void },
): ImagePickResult {
  if (file === null) return 'empty';

  const verdict = validateImageFile(file);
  if (!verdict.ok) {
    handlers.onReject(verdict.error);

    return 'rejected';
  }

  handlers.onAccept(file);

  return 'accepted';
}

/** PURE - `FormData` multipart untuk endpoint gambar (field `image`). */
export function toImageFormData(file: File, field: string = IMAGE_FIELD_NAME): FormData {
  const formData = new FormData();
  formData.append(field, file, file.name);

  return formData;
}
