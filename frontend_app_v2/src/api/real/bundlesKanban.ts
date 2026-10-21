// REAL - papan kanban BUNDLE (FASE K2 backend, `/garmen/bundles/kanban/`).
//
// Satu request = semua kolom (kontrak K2 `columns[]/transitions[]`), jadi papan TIDAK
// lagi memanggil list berkali-kali dengan `?state=` (pola lama N request per kolom).
// Parsing bentuk response ada di `real/kanban.ts` (dipakai bersama work-orders).
import type { ApiClient } from '@/integrations/api-client';
import type { KanbanQuery, KanbanResponse } from '@/types/kanban';
import { buildKanbanPath, fetchKanban } from './kanban';

/** Path relatif `VITE_API_BASE_URL`. */
export const BUNDLES_KANBAN_PATH = '/garmen/bundles/kanban/';

/** PURE - path + query param terisi (`search`/`state`/`work_center_id`/`line_id`/`limit`). */
export function buildBundlesKanbanPath(params: KanbanQuery = {}): string {
  return buildKanbanPath(BUNDLES_KANBAN_PATH, params);
}

/** GET papan kanban bundle (IsAuthenticated - anonim 403 di backend). */
export async function fetchBundlesKanban(
  client: ApiClient,
  params: KanbanQuery = {},
): Promise<KanbanResponse> {
  return fetchKanban(client, BUNDLES_KANBAN_PATH, params);
}

export type { KanbanQuery, KanbanResponse } from '@/types/kanban';
