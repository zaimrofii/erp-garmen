// SHARED (K5.3) — pembaca + pemanggil endpoint gambar master.
//
// Dipakai `real/masterProducts.ts` dan `real/masterPartners.ts` (kedua endpoint
// gambar punya bentuk response yang SAMA):
//   * `POST /master/<resource>/<id>/image/`   — multipart field `image`;
//   * `DELETE /master/<resource>/<id>/image/` — idempotent (200 walau belum ada gambar).
//
// `ApiClient.request` mendeteksi `FormData` (tanpa `Content-Type: application/json`),
// jadi tidak perlu method khusus — sama seperti pola PUT/DELETE di repo ini.
import type { ApiClient, ApiResponse } from '@/integrations/api-client';
import { toImageFormData } from '@/lib/image-upload';
import type { MasterImagePayload } from '@/types/master-image';
import { unwrap } from '../client';
import { isRecord, readNullableStr, readStr } from './_shape';

/** PURE - path endpoint gambar, mis. `('/master/products/', 7)` → `/master/products/7/image/`. */
export function masterImagePath(basePath: string, id: number): string {
  return `${basePath}${String(id)}/image/`;
}

/** PURE - response 200 endpoint gambar (null kalau `id` tidak dikenali). */
export function readMasterImagePayload(raw: unknown): MasterImagePayload | null {
  if (!isRecord(raw)) return null;

  const id = raw['id'];
  if (typeof id !== 'number' || !Number.isFinite(id)) return null;

  const payload: MasterImagePayload = {
    id,
    image_file_url: readNullableStr(raw['image_file_url']),
    image_display_url: readNullableStr(raw['image_display_url']),
    image_thumbnail_url: readNullableStr(raw['image_thumbnail_url']),
    message: readStr(raw['message']),
  };
  const warning = readNullableStr(raw['warning']);
  if (warning !== null) payload.warning = warning;

  const deletedFiles = Array.isArray(raw['deleted_files'])
    ? raw['deleted_files'].map((value) => String(value))
    : null;
  if (deletedFiles !== null) payload.deleted_files = deletedFiles;

  return payload;
}

function readPayload(res: ApiResponse<unknown>, label: string): MasterImagePayload {
  const payload = readMasterImagePayload(unwrap(res));
  if (payload === null) {
    throw new Error(`Bentuk respons ${label} tidak dikenali.`);
  }

  return payload;
}

/** Unggah gambar (multipart) ke `path` — pesan error backend dilempar apa adanya. */
export async function postMasterImage(
  client: ApiClient,
  path: string,
  file: File,
): Promise<MasterImagePayload> {
  return readPayload(
    await client.request<unknown>(path, { method: 'POST', body: toImageFormData(file) }),
    'unggah gambar',
  );
}

/** Hapus gambar di `path` (idempotent; balasan memuat `deleted_files`). */
export async function deleteMasterImage(
  client: ApiClient,
  path: string,
): Promise<MasterImagePayload> {
  return readPayload(
    await client.request<unknown>(path, { method: 'DELETE' }),
    'hapus gambar',
  );
}
