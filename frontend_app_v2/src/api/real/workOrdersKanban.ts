// REAL - papan kanban WORK ORDER (FASE K2 backend, `/garmen/work-orders/kanban/`).
//
// Kartu WO memakai kunci yang SAMA dengan kartu bundle (kontrak K2): `work_order_code`
// = kode WO itu sendiri, `size` = null, `qty` = qty_planned.
import type { ApiClient } from '@/integrations/api-client';
import type { KanbanQuery, KanbanResponse } from '@/types/kanban';
import { buildKanbanPath, fetchKanban } from './kanban';

/** Path relatif `VITE_API_BASE_URL`. */
export const WORK_ORDERS_KANBAN_PATH = '/garmen/work-orders/kanban/';

/** PURE - path + query param terisi (`search`/`state`/`limit`; param WC/line diabaikan backend). */
export function buildWorkOrdersKanbanPath(params: KanbanQuery = {}): string {
  return buildKanbanPath(WORK_ORDERS_KANBAN_PATH, params);
}

/** GET papan kanban work order (IsAuthenticated - anonim 403 di backend). */
export async function fetchWorkOrdersKanban(
  client: ApiClient,
  params: KanbanQuery = {},
): Promise<KanbanResponse> {
  return fetchKanban(client, WORK_ORDERS_KANBAN_PATH, params);
}

export type { KanbanQuery, KanbanResponse } from '@/types/kanban';
