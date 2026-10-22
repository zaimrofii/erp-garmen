// REAL — antrean HITL AI (S.3). Endpoint: /api/v1/ai/hitl/
import type { ApiClient } from '@/integrations/api-client';
import { unwrap } from '../client';
import type {
  HitlQueuePage,
  HitlQueueParams,
  HitlQueueRow,
} from '@/types/hitl-queue';
import {
  buildQueryPath,
  getParsed,
  isRecord,
  readListPage,
  readNullableNum,
  readNum,
  readStr,
} from './_shape';

export const HITL_QUEUE_PATH = '/ai/hitl/queue/';

function readProposedAction(raw: unknown): HitlQueueRow['proposed_action'] {
  const data = isRecord(raw) ? raw : {};
  const actions = Array.isArray(data['actions'])
    ? data['actions'].filter(isRecord).map((item) => ({
        action: readStr(item['action']),
        impact: readStr(item['impact']) || 'LOW',
        confidence: readNum(item['confidence']),
        reason: readStr(item['reason']),
      }))
    : [];

  return {
    type: readStr(data['type']),
    problem: readStr(data['problem']),
    actions,
    count: readNum(data['count']),
  };
}

export function parseHitlQueueRow(raw: unknown): HitlQueueRow | null {
  if (!isRecord(raw)) return null;
  const id = readNum(raw['id']);
  if (id <= 0) return null;

  return {
    id,
    decision_log_id: readNullableNum(raw['decision_log_id']),
    risk_level: readStr(raw['risk_level']),
    proposed_action: readProposedAction(raw['proposed_action']),
    required_approver_role: readStr(raw['required_approver_role']),
    channel: readStr(raw['channel']),
    status: readStr(raw['status']),
    query_text: readStr(raw['query_text']),
    intent: readStr(raw['intent']),
    confidence_score: readNullableNum(raw['confidence_score']),
    expires_at: raw['expires_at'] === null ? null : readStr(raw['expires_at']) || null,
    created_at: raw['created_at'] === null ? null : readStr(raw['created_at']) || null,
    decided_by: raw['decided_by'] === null ? null : readStr(raw['decided_by']) || null,
    decided_at: raw['decided_at'] === null ? null : readStr(raw['decided_at']) || null,
    rejection_reason: readStr(raw['rejection_reason']),
  };
}

export function parseHitlQueue(raw: unknown): HitlQueuePage | null {
  return readListPage(raw, parseHitlQueueRow);
}

export async function fetchHitlQueue(
  client: ApiClient,
  params: HitlQueueParams = {},
): Promise<HitlQueuePage> {
  const path = buildQueryPath(HITL_QUEUE_PATH, {
    status: params.status,
    risk_level: params.risk,
    limit: params.limit,
    offset: params.offset,
  });
  return getParsed(client, path, parseHitlQueue, 'antrean HITL');
}

export async function approveHitl(
  client: ApiClient,
  id: number,
  note = '',
): Promise<HitlQueueRow | null> {
  const raw = unwrap(await client.post<unknown>(`/ai/hitl/${id}/approve/`, { note }));
  return parseHitlQueueRow(raw);
}

export async function rejectHitl(
  client: ApiClient,
  id: number,
  reason: string,
): Promise<HitlQueueRow | null> {
  const raw = unwrap(
    await client.post<unknown>(`/ai/hitl/${id}/reject/`, { reason }),
  );
  return parseHitlQueueRow(raw);
}
