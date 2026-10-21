// ADAPTER - satu-satunya pintu data papan kanban WORK ORDER (FASE K3).
//
// Halaman/hook HANYA boleh mengimpor dari `@/api/workOrdersKanban` - JANGAN dari
// `./real/*`. Implementasi ada di `api/real/workOrdersKanban.ts`
// (MODE.workOrdersKanban === 'real' di `api/_adapter.ts`).
import { pickAdapter } from './_adapter';
import * as real from './real/workOrdersKanban';

/** Papan kanban work order (`GET /garmen/work-orders/kanban/`) - REAL (K2). */
export const fetchWorkOrdersKanban = pickAdapter(
  'workOrdersKanban',
  real.fetchWorkOrdersKanban,
  real.fetchWorkOrdersKanban,
);

export { buildWorkOrdersKanbanPath, WORK_ORDERS_KANBAN_PATH } from './real/workOrdersKanban';
export type { KanbanQuery, KanbanResponse } from '@/types/kanban';
