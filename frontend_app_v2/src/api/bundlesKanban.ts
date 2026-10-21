// ADAPTER - satu-satunya pintu data papan kanban BUNDLE (FASE K3).
//
// Halaman/hook HANYA boleh mengimpor dari `@/api/bundlesKanban` - JANGAN dari
// `./real/*`. Implementasi ada di `api/real/bundlesKanban.ts`
// (MODE.bundlesKanban === 'real' di `api/_adapter.ts`) - endpoint K2 sudah ada,
// jadi tidak ada implementasi dummy untuk resource ini.
import { pickAdapter } from './_adapter';
import * as real from './real/bundlesKanban';

/** Papan kanban bundle (`GET /garmen/bundles/kanban/`) - REAL (K2). */
export const fetchBundlesKanban = pickAdapter(
  'bundlesKanban',
  real.fetchBundlesKanban,
  real.fetchBundlesKanban,
);

export { buildBundlesKanbanPath, BUNDLES_KANBAN_PATH } from './real/bundlesKanban';
export type { KanbanQuery, KanbanResponse } from '@/types/kanban';
