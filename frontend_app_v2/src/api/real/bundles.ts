// REAL - wrap integration engine v2 (api-client). Endpoint: GET /garmen/bundles/, GET /garmen/bundles/{id}/
//
// Logic fetch TIDAK ditulis ulang di sini: semua lewat `integrations/api-client.ts`
// (satu-satunya pintu keluar HTTP - sabuk pengaman #1). Yang ditambahkan hanya
// signature adapter + helper aksi bundle.
import type { ApiClient } from '@/integrations/api-client';
import type { ListPage } from '@/lib/schemas/list.schema';
import type { BundleDetail } from '@/types/bundle';
import { unwrap } from '../client';

/** Path relatif terhadap `VITE_API_BASE_URL`. */
export const BUNDLES_PATH = '/garmen/bundles/';

/**
 * Hasil aksi bundle dari backend (mis. `POST /garmen/bundles/42/start/`).
 * Bentuknya sengaja longgar-meniru kontrak `{ok,state,version}` supaya halaman
 * detail bisa memakai `version` untuk optimistic lock.
 */
export interface BundleActionOutcome {
  ok: boolean;
  state: string;
  version: string;
  message?: string;
}

export async function getBundles(
  client: ApiClient,
  params: { limit?: number; offset?: number } = {},
): Promise<ListPage> {
  const qs = new URLSearchParams();
  if (params.limit != null) qs.set('limit', String(params.limit));
  if (params.offset != null) qs.set('offset', String(params.offset));
  const suffix = qs.toString() ? `?${qs}` : '';
  const res = await client.get<ListPage>(`${BUNDLES_PATH}${suffix}`);
  return unwrap(res);
}

export async function getBundle(client: ApiClient, id: number | string): Promise<BundleDetail> {
  const res = await client.get<BundleDetail>(`${BUNDLES_PATH}${id}/`);
  return unwrap(res);
}

/** Alias eksplisit untuk halaman detail (lapisan v3 memakai awalan `fetch*`). */
export async function fetchBundleDetail(
  client: ApiClient,
  id: number | string,
): Promise<BundleDetail> {
  return getBundle(client, id);
}

/**
 * Opsi aksi online (semua opsional):
 *  - `idempotencyKey` -> header `Idempotency-Key` (anti dobel klik / retry aman);
 *  - `baseVersion`    -> header `X-Base-Version` (optimistic lock; 409 kalau basi).
 */
export interface BundleActionOptions {
  idempotencyKey?: string;
  baseVersion?: string;
}

/**
 * Kirim satu aksi bundle: `POST /garmen/bundles/{id}/{action}/` dengan `action`
 * APA ADANYA (`BUNDLE_START`, bukan slug `start` - kontrak backend bagian 6).
 *
 * Jalur ini untuk aksi online-only (halaman detail). Aksi operator yang harus tahan
 * offline tetap lewat `submitAction` + `offline-queue` - jangan diseragamkan.
 * Gagal -> melempar Error (`unwrap`); 409 ditangani pemanggil via `apiClient` langsung.
 */
export async function submitBundleAction(
  client: ApiClient,
  id: number | string,
  actionId: string,
  payload: Record<string, unknown> = {},
  options: BundleActionOptions = {},
): Promise<BundleActionOutcome> {
  // PENTING (kontrak backend bagian 6): segment action dikirim APA ADANYA
  // (`/garmen/bundles/42/BUNDLE_START/`), BUKAN slug (`start` -> 400).
  const res = await client.post<BundleActionOutcome>(
    `${BUNDLES_PATH}${id}/${encodeURIComponent(actionId)}/`,
    payload,
    options,
  );
  return unwrap(res);
}

export type { BundleRow, BundleDetail } from '@/types/bundle';
