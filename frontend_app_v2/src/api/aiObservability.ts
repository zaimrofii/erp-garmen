// ADAPTER — observability AI (Sprint F.3.4). Mode REAL.
import { pickAdapter } from './_adapter';
import * as real from './real/aiObservability';

export const fetchAIObservability = pickAdapter(
  'aiObservability',
  real.fetchAIObservability,
  real.fetchAIObservability,
);

export { AI_OBSERVABILITY_PATH, parseAIObservability } from './real/aiObservability';
export type { AIObservabilityStats } from '@/types/ai-observability';
