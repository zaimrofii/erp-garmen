import type { ActionMode } from './schemas/action.schema';

/**
 * transition-rules.ts — `TRANSITION_MODE` = source of truth optimistic vs pessimistic (§7.2).
 *
 * Prioritas (larangan §12.3 — metadata `action.mode` TIDAK BOLEH menimpa ini):
 *   1. `TRANSITION_MODE[actionId]`   ← source of truth
 *   2. `action.mode` dari metadata   ← fallback
 *   3. `'pessimistic'`               ← safe default
 */

export type TransitionMode = ActionMode;

export const TRANSITION_MODE: Record<string, TransitionMode> = {
  // Optimistic — idempotent + reversible + low-risk + fast (§7.2)
  BUNDLE_START: 'optimistic',
  BUNDLE_FINISH: 'optimistic',
  QC_PASS: 'optimistic',
  PACKING_START: 'optimistic',
  PACKING_FINISH: 'optimistic',
  BUNDLE_HOLD: 'optimistic',

  // Pessimistic — irreversible / butuh validasi server / high-risk / slow (§7.2)
  BUNDLE_SCRAP: 'pessimistic',
  BUNDLE_REWORK: 'pessimistic',
  QC_REJECT: 'pessimistic',
  WO_CLOSE: 'pessimistic',
  ODOO_SYNC: 'pessimistic',
  LINE_REASSIGN: 'pessimistic',
  PRIORITY_CHANGE: 'pessimistic',
};

/** Fallback terakhir: pessimistic = aman (UI tidak berubah sebelum server mengonfirmasi). */
export const DEFAULT_TRANSITION_MODE: TransitionMode = 'pessimistic';

export function resolveTransitionMode(
  actionId: string,
  metadataMode?: TransitionMode
): TransitionMode {
  return TRANSITION_MODE[actionId] ?? metadataMode ?? DEFAULT_TRANSITION_MODE;
}
