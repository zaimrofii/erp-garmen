// Tipe antrean HITL AI (S.3) — konsisten dengan serialisasi backend.
import type { ListPage } from '@/api/real/_shape';

export type HitlStatus = 'PENDING' | 'APPROVED' | 'REJECTED' | 'EXPIRED';
export type HitlRisk = 'LOW' | 'MEDIUM' | 'HIGH';

export interface HitlAction {
  action: string;
  impact: HitlRisk | string;
  confidence: number;
  reason: string;
}

export interface HitlProposedAction {
  type?: string;
  problem?: string;
  actions?: HitlAction[];
  count?: number;
}

export interface HitlQueueRow {
  id: number;
  decision_log_id: number | null;
  risk_level: string;
  proposed_action: HitlProposedAction;
  required_approver_role: string;
  channel: string;
  status: HitlStatus | string;
  query_text: string;
  intent: string;
  confidence_score: number | null;
  expires_at: string | null;
  created_at: string | null;
  decided_by: string | null;
  decided_at: string | null;
  rejection_reason: string;
}

export interface HitlQueueParams {
  status?: string;
  risk?: string;
  limit?: number;
  offset?: number;
}

export type HitlQueuePage = ListPage<HitlQueueRow>;
