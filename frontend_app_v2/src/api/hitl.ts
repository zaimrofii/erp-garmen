// ADAPTER - satu-satunya pintu data HITL approval (TANPA logic domain).
//
// Halaman AIChatPage WAJIB mengimpor dari sini - JANGAN dari `./dummy/*`.
// F5.4.CLOSE: MODE.hitl === 'real' (B29) → `api/dummy/hitl.ts` dihapus.
import { pickAdapter } from './_adapter';
import * as real from './real/hitl';

/** Antrean persetujuan yang menunggu keputusan manusia (`?state=PENDING`). */
export const fetchPendingApprovals = pickAdapter(
  'hitl',
  real.fetchPendingApprovals,
  real.fetchPendingApprovals,
);

/** Semua approval (4 state digabung) - untuk riwayat. */
export const fetchAllApprovals = pickAdapter(
  'hitl',
  real.fetchAllApprovals,
  real.fetchAllApprovals,
);

/** Setujui / tolak satu pengajuan agen. */
export const decideApproval = pickAdapter('hitl', real.decideApproval, real.decideApproval);

export {
  buildHitlDecisionPath,
  buildHitlQueuePath,
  DEFAULT_REJECT_NOTE,
  HITL_QUEUE_PATH,
  HITL_STATES,
  fetchHitlRows,
  readHitlPage,
  readHitlRow,
  toHitlApproval,
} from './real/hitl';
export type { HitlQueueParams, HitlRow, HitlState } from './real/hitl';
