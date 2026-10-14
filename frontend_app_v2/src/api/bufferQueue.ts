// ADAPTER - satu-satunya pintu data Buffer Queue (TANPA logic domain).
//
// F2C.2: MODE `bufferQueue` === 'real' (`GET /api/v1/production/buffer-queue/`, B2 + G2).
import { pickAdapter } from './_adapter';
import * as real from './real/bufferQueue';

/** Antrean buffer per work center (DashboardPage / BufferQueuePage). */
export const fetchBufferQueue = pickAdapter(
  'bufferQueue',
  real.fetchBufferQueue,
  real.fetchBufferQueue,
);

export { BUFFER_QUEUE_PATH, readBufferQueueSummary } from './real/bufferQueue';
export type { BufferQueueBundle, BufferQueueSummary, BufferQueueWcRow } from './real/bufferQueue';

