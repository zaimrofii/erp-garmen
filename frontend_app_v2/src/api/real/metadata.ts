// REAL - wrap integration engine v2 (api-client). Endpoint: GET /metadata/{resource}/
//
// `industry` dikirim sebagai query HANYA kalau bukan default ('garmen'), sesuai
// kontrak backend: `GET /metadata/bundles/` / `GET /metadata/bundles/?id=42`.
import type { ApiClient } from '@/integrations/api-client';
import { unwrap } from '../client';

export const DEFAULT_INDUSTRY = 'garmen';
export const METADATA_PATH = '/metadata/';

/**
 * PURE - bangun path metadata.
 * `id` kosong -> metadata instance pertama dari backend.
 */
export function buildMetadataPath(
  resource: string,
  id?: string | number | null,
  industry: string = DEFAULT_INDUSTRY,
): string {
  const params: string[] = [];
  const encodedId = id === undefined || id === null ? '' : String(id).trim();
  if (encodedId.length > 0) params.push(`id=${encodeURIComponent(encodedId)}`);

  const normalizedIndustry = industry.trim().toLowerCase();
  if (normalizedIndustry.length > 0 && normalizedIndustry !== DEFAULT_INDUSTRY) {
    params.push(`industry=${encodeURIComponent(normalizedIndustry)}`);
  }

  const base = `${METADATA_PATH}${encodeURIComponent(resource.trim())}/`;

  return params.length === 0 ? base : `${base}?${params.join('&')}`;
}

/**
 * Metadata mentah (BELUM divalidasi - bentuk per `view_type` baru dibaca lapisan view).
 * Gagal HTTP -> melempar Error (`unwrap`).
 */
export async function fetchResourceMetadata(
  client: ApiClient,
  resource: string,
  id?: string | number | null,
  industry?: string,
): Promise<unknown> {
  const res = await client.get<unknown>(buildMetadataPath(resource, id, industry));
  return unwrap(res);
}
