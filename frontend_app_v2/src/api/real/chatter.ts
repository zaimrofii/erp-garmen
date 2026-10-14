// REAL - wrap integration engine v2 (api-client + ws-chatter). Endpoint: GET /chatter/{resource}/{id}/
//
// Dua sisi chatter digabung di lapisan adapter ini:
//  1. REST (paginasi preview) - lewat `integrations/api-client.ts`;
//  2. real-time (event WebSocket) - lewat `integrations/ws-chatter.ts` (fungsi murni).
import type { ApiClient } from '@/integrations/api-client';
import { buildChatterQuery } from '@/lib/chatter-merge';
import type { ChatterPage } from '@/lib/schemas/chatter.schema';
import { unwrap } from '../client';

/** Path relatif terhadap `VITE_API_BASE_URL`; `{resource}`/`{id}` relatif terhadap base. */
export const CHATTER_PATH = '/chatter/';

/**
 * Halaman chatter (cursor paginasi, kontrak v4.3 §3.3).
 *
 * F1 (D4): `limit` default **20** + `cursor` opsional dihitung `buildChatterQuery`
 * (satu sumber kebenaran dengan merge/`ChatterBox`), jadi pemanggil boleh tidak mengirim
 * `limit` sama sekali.
 */
export async function getChatter(
  client: ApiClient,
  resource: string,
  id: number | string,
  params: { limit?: number | null; cursor?: string | null } = {},
): Promise<ChatterPage> {
  const query = buildChatterQuery(params);
  const qs = new URLSearchParams();
  qs.set('limit', String(query.limit));
  if (query.cursor !== undefined) qs.set('cursor', query.cursor);

  const res = await client.get<ChatterPage>(`${CHATTER_PATH}${resource}/${id}/?${qs.toString()}`);
  return unwrap(res);
}

// Real-time (Fase E) - re-export apa adanya, JANGAN diubah.
export {
  readWsChatterEvent,
  mergeWsChatter,
  countNewEvents,
  mergeWsEventsIntoMetadata,
} from '@/integrations/ws-chatter';
