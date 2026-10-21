// Tipe chat AI — kontrak docs/ai/CHAT-CONTRACT.md §2–§3.

export type AIChatChannel = 'DESKTOP' | 'FLOATING' | 'WA';

export type AIChatPageType = 'detail' | 'list' | 'form' | 'report';

export type AIChatDecisionGateResult = 'RULE_HIT' | 'LLM_NEEDED' | 'BLOCKED';

export type AIChatImpactScore = 'LOW' | 'MEDIUM' | 'HIGH';

export interface AIChatHistoryItem {
  role: 'user' | 'assistant';
  content: string;
}

export interface AIChatContext {
  page_type: AIChatPageType | null;
  route: string | null;
  resource_type: string | null;
  /** SELALU string (UUID/int aman) — kontrak §2. */
  resource_id: string | null;
  filters: Record<string, string | number | boolean>;
  visible_fields_snapshot: Record<string, string | number | boolean>;
}

export interface AIChatRequest {
  message: string;
  context?: AIChatContext;
  history?: AIChatHistoryItem[];
  channel?: AIChatChannel;
}

export interface AIChatToolCall {
  tool: string;
  input: Record<string, unknown>;
  output_summary: string;
}

export interface AIChatTokens {
  prompt: number;
  completion: number;
  total_cost_usd: number;
}

export interface AIChatResponse {
  ok: true;
  answer: string;
  tool_calls: AIChatToolCall[];
  confidence_score: number | null;
  impact_score: AIChatImpactScore;
  hitl_required: boolean;
  hitl_request_id: number | null;
  decision_gate_result: AIChatDecisionGateResult;
  tokens: AIChatTokens;
  cache_hit: boolean;
  latency_ms: number;
}

export interface AIChatError {
  ok: false;
  error: string;
  detail?: string;
}

export type AIChatResult = AIChatResponse | AIChatError;

/** Pesan UI (state lokal halaman/panel) — metadata response ikut disimpan. */
export interface AIChatUiMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  response?: AIChatResponse;
  error?: string;
}
