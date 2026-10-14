/**
 * conflict-policy.ts — strategi resolve konflik 409 per aksi (§8.2).
 *
 * - `last_write_wins` : operator melihat kondisi fisik (START/FINISH/QC_PASS)
 * - `server_wins`     : server lebih akurat (SCRAP/REWORK/WO_CLOSE/ODOO_SYNC)
 * - `manual`          : butuh resolve manual (LINE_REASSIGN/PRIORITY_CHANGE)
 */

export type ConflictPolicy = 'last_write_wins' | 'server_wins' | 'manual';

export const CONFLICT_POLICY: Record<string, ConflictPolicy> = {
  // last_write_wins — operator lihat fisik (§8.2)
  BUNDLE_START: 'last_write_wins',
  BUNDLE_FINISH: 'last_write_wins',
  QC_PASS: 'last_write_wins',

  // server_wins — server lebih akurat (§8.2)
  BUNDLE_SCRAP: 'server_wins',
  BUNDLE_REWORK: 'server_wins',
  QC_REJECT: 'server_wins',
  WO_CLOSE: 'server_wins',
  ODOO_SYNC: 'server_wins',

  // manual — butuh resolve manual (§8.2)
  LINE_REASSIGN: 'manual',
  PRIORITY_CHANGE: 'manual',
};

/** Default paling aman: jangan auto-resolve kalau aksi tidak dikenal. */
export const DEFAULT_CONFLICT_POLICY: ConflictPolicy = 'manual';

export function resolveConflictPolicy(actionId: string): ConflictPolicy {
  return CONFLICT_POLICY[actionId] ?? DEFAULT_CONFLICT_POLICY;
}
