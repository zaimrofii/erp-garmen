// REAL — adapter chat AI (Sprint E.1). Endpoint: /api/v1/ai/chat
// Kontrak: docs/ai/CHAT-CONTRACT.md §2–§3.
import type { ApiClient } from '@/integrations/api-client';
import type {
  AIChatContext,
  AIChatError,
  AIChatHistoryItem,
  AIChatImpactScore,
  AIChatRequest,
  AIChatResponse,
  AIChatResult,
  AIChatToolCall,
} from '@/types/ai-chat';

export const AI_CHAT_PATH = '/ai/chat';

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function readStr(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

function readNum(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0;
}

function readImpact(value: unknown): AIChatImpactScore {
  return value === 'MEDIUM' || value === 'HIGH' ? value : 'LOW';
}

function readGate(value: unknown): AIChatResponse['decision_gate_result'] {
  return value === 'LLM_NEEDED' || value === 'BLOCKED' ? value : 'RULE_HIT';
}

function readToolCall(raw: unknown): AIChatToolCall | null {
  if (!isRecord(raw)) return null;

  const tool = readStr(raw['tool']);
  if (tool.length === 0) return null;

  return {
    tool,
    input: isRecord(raw['input']) ? raw['input'] : {},
    output_summary: readStr(raw['output_summary']),
  };
}

/** PURE — respons mentah `{ok:true,...}` → AIChatResponse (defensif). */
export function parseChatResponse(raw: unknown): AIChatResponse | null {
  if (!isRecord(raw) || raw['ok'] !== true) return null;

  const tokens = isRecord(raw['tokens']) ? raw['tokens'] : {};
  const toolCalls = Array.isArray(raw['tool_calls'])
    ? raw['tool_calls']
        .map(readToolCall)
        .filter((call): call is AIChatToolCall => call !== null)
    : [];

  const confidence = raw['confidence_score'];

  return {
    ok: true,
    answer: readStr(raw['answer']),
    tool_calls: toolCalls,
    confidence_score:
      typeof confidence === 'number' && Number.isFinite(confidence) ? confidence : null,
    impact_score: readImpact(raw['impact_score']),
    hitl_required: raw['hitl_required'] === true,
    hitl_request_id:
      typeof raw['hitl_request_id'] === 'number' ? raw['hitl_request_id'] : null,
    decision_gate_result: readGate(raw['decision_gate_result']),
    tokens: {
      prompt: readNum(tokens['prompt']),
      completion: readNum(tokens['completion']),
      total_cost_usd: readNum(tokens['total_cost_usd']),
    },
    cache_hit: raw['cache_hit'] === true,
    latency_ms: readNum(raw['latency_ms']),
  };
}

function readErrorMessage(raw: unknown): AIChatError {
  if (!isRecord(raw)) return { ok: false, error: 'invalid_response' };

  const error = readStr(raw['error']) || readStr(raw['reason']) || 'unknown_error';
  const detail = readStr(raw['detail']);

  return detail.length > 0 ? { ok: false, error, detail } : { ok: false, error };
}

/**
 * Kirim pesan chat. **Tidak pernah throw** — kegagalan jaringan menjadi
 * `{ok:false, error:"network_error"}` agar UI tetap bisa menampilkan pesan.
 */
export async function sendChatMessage(
  client: ApiClient,
  payload: AIChatRequest,
): Promise<AIChatResult> {
  const body: AIChatRequest = {
    message: payload.message.trim(),
    ...(payload.context === undefined ? {} : { context: payload.context }),
    ...(payload.history === undefined ? {} : { history: payload.history }),
    channel: payload.channel ?? 'DESKTOP',
  };

  const response = await client.post<unknown>(AI_CHAT_PATH, body);
  if (!response.ok) {
    const detail = response.error?.message;
    return detail === undefined
      ? { ok: false, error: 'network_error' }
      : { ok: false, error: 'network_error', detail };
  }

  const parsed = parseChatResponse(response.data);
  return parsed ?? readErrorMessage(response.data);
}

export type { AIChatContext, AIChatHistoryItem, AIChatRequest };
