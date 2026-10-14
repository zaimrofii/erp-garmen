// REAL - HITL queue & keputusan (F5.4.CLOSE / backend B29).
//   GET  `/ai/hitl/queue/`            (+ `?state=&priority=&resource_type=&limit=&cursor=`)
//   POST `/ai/hitl/<id>/approve/`     (body `{note?}`)
//   POST `/ai/hitl/<id>/reject/`      (body `{note}` — **wajib**, tanpa note → 400)
//
// Pemetaan baris backend → tipe UI `HitlApproval` (tanpa mengarang field):
//   * `requester`  ← `requested_by` (username peminta; `null` → `'system'`);
//   * `action`     ← `request_type` (`SCRAP_BUNDLE`…);
//   * `resource`   ← `resource_type`; `status` ← `state.lowercase()`;
//   * `created_at` ← `requested_at`; aditif: `priority`, `payload`,
//     `decided_by`, `decided_at`, `decision_note`, `expires_at`.
//
// CATATAN: backend **tidak** punya `state=ALL`, jadi `fetchAllApprovals()` = 4 GET
// paralel (PENDING/APPROVED/REJECTED/EXPIRED) yang digabung + diurutkan terbaru dulu.
import type { ApiClient } from '@/integrations/api-client';
import type { HitlApproval, HitlDecision, HitlStatus } from '@/types/settings';
import { unwrap } from '../client';
import {
  buildQueryPath,
  getParsed,
  isRecord,
  readListPage,
  readNullableStr,
  readNum,
  readStr,
  type ListPage,
} from './_shape';

export const HITL_QUEUE_PATH = '/ai/hitl/queue/';

/** Semua state yang dikenal backend (`HITLRequest.State`). */
export const HITL_STATES = ['PENDING', 'APPROVED', 'REJECTED', 'EXPIRED'] as const;

export type HitlState = (typeof HITL_STATES)[number];

/** Catatan default saat REJECT dari UI tanpa input catatan (backend mewajibkannya). */
export const DEFAULT_REJECT_NOTE = 'Ditolak dari antrean HITL (tanpa catatan tambahan).';

export interface HitlRow {
  id: number;
  request_type: string;
  resource_type: string;
  resource_id: string;
  payload: Record<string, unknown>;
  reason: string;
  priority: string;
  /** `PENDING` | `APPROVED` | `REJECTED` | `EXPIRED`. */
  state: string;
  requested_by: string | null;
  requested_at: string | null;
  expires_at: string | null;
  decided_by: string | null;
  decided_at: string | null;
  decision_note: string | null;
}

const STATE_TO_STATUS: Record<string, HitlStatus> = {
  PENDING: 'pending',
  APPROVED: 'approved',
  REJECTED: 'rejected',
  EXPIRED: 'expired',
};

/** PURE — path keputusan: `POST /ai/hitl/<id>/approve|reject/`. */
export function buildHitlDecisionPath(id: number, decision: HitlDecision): string {
  return `/ai/hitl/${id}/${decision === 'approve' ? 'approve' : 'reject'}/`;
}

/** PURE — satu baris backend → `HitlRow`. */
export function readHitlRow(raw: unknown): HitlRow | null {
  if (!isRecord(raw)) return null;
  const payload = raw['payload'];

  return {
    id: readNum(raw['id']),
    request_type: readStr(raw['request_type']),
    resource_type: readStr(raw['resource_type']),
    resource_id: readStr(raw['resource_id']),
    payload: isRecord(payload) ? payload : {},
    reason: readStr(raw['reason']),
    priority: readStr(raw['priority']),
    state: readStr(raw['state']),
    requested_by: readNullableStr(raw['requested_by']),
    requested_at: readNullableStr(raw['requested_at']),
    expires_at: readNullableStr(raw['expires_at']),
    decided_by: readNullableStr(raw['decided_by']),
    decided_at: readNullableStr(raw['decided_at']),
    decision_note: readNullableStr(raw['decision_note']),
  };
}

/** PURE — respons ListPage HITL. */
export function readHitlPage(raw: unknown): ListPage<HitlRow> | null {
  return readListPage<HitlRow>(raw, readHitlRow);
}

/** PURE — baris backend → `HitlApproval` (view model AIChatPage). */
export function toHitlApproval(row: HitlRow): HitlApproval {
  return {
    id: row.id,
    requester: row.requested_by ?? 'system',
    action: row.request_type,
    resource: row.resource_type,
    resource_id: row.resource_id,
    reason: row.reason,
    status: STATE_TO_STATUS[row.state.trim().toUpperCase()] ?? 'pending',
    created_at: row.requested_at ?? '',
    priority: row.priority,
    decided_by: row.decided_by,
    decision_note: row.decision_note,
    expires_at: row.expires_at,
  };
}


export interface HitlQueueParams {
  /** Default backend = `PENDING`. */
  state?: HitlState | null;
  priority?: string | null;
  resourceType?: string | null;
  limit?: number | null;
  cursor?: number | null;
}

/** PURE — path + query antrean HITL. */
export function buildHitlQueuePath(params: HitlQueueParams = {}): string {
  return buildQueryPath(HITL_QUEUE_PATH, {
    state: params.state,
    priority: params.priority,
    resource_type: params.resourceType,
    limit: params.limit,
    cursor: params.cursor,
  });
}

/** Baris mentah satu state (default `PENDING`). */
export async function fetchHitlRows(
  client: ApiClient,
  params: HitlQueueParams = {},
): Promise<ListPage<HitlRow>> {
  return getParsed(client, buildHitlQueuePath(params), readHitlPage, 'antrean HITL');
}

/** Antrean yang menunggu keputusan manusia. */
export async function fetchPendingApprovals(
  client: ApiClient,
  params: Omit<HitlQueueParams, 'state'> = {},
): Promise<HitlApproval[]> {
  const page = await fetchHitlRows(client, { ...params, state: 'PENDING' });

  return page.rows.map(toHitlApproval);
}

/** SEMUA approval (4 state digabung + urut terbaru dulu) — untuk riwayat chat. */
export async function fetchAllApprovals(
  client: ApiClient,
  params: Omit<HitlQueueParams, 'state'> = {},
): Promise<HitlApproval[]> {
  const pages = await Promise.all(
    HITL_STATES.map((state) => fetchHitlRows(client, { ...params, state })),
  );

  return pages
    .flatMap((page) => page.rows.map(toHitlApproval))
    .sort((left, right) => right.created_at.localeCompare(left.created_at));
}

/** Setujui / tolak satu pengajuan. REJECT tanpa `note` memakai catatan default. */
export async function decideApproval(
  client: ApiClient,
  id: number,
  decision: HitlDecision,
  note?: string,
): Promise<HitlApproval> {
  const trimmed = (note ?? '').trim();
  const useNote =
    decision === 'reject' ? (trimmed.length > 0 ? trimmed : DEFAULT_REJECT_NOTE) : trimmed;
  const body: Record<string, unknown> = useNote.length > 0 ? { note: useNote } : {};

  const row = readHitlRow(
    unwrap(await client.post<unknown>(buildHitlDecisionPath(id, decision), body)),
  );

  if (row === null) {
    throw new Error('Bentuk respons keputusan HITL tidak dikenali.');
  }

  return toHitlApproval(row);
}
