// ADAPTER — antrean HITL AI (S.3). Mode REAL.
import { pickAdapter } from './_adapter';
import * as real from './real/hitlQueue';

export const fetchHitlQueue = pickAdapter(
  'hitlQueue',
  real.fetchHitlQueue,
  real.fetchHitlQueue,
);

export const approveHitl = pickAdapter(
  'hitlQueue',
  real.approveHitl,
  real.approveHitl,
);

export const rejectHitl = pickAdapter(
  'hitlQueue',
  real.rejectHitl,
  real.rejectHitl,
);

export { HITL_QUEUE_PATH, parseHitlQueue, parseHitlQueueRow } from './real/hitlQueue';
export type { HitlQueuePage, HitlQueueRow } from '@/types/hitl-queue';
