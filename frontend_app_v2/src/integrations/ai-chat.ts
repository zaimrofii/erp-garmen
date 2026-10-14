import { generateUUID } from '@/lib/uuid';
import type { ApiClient } from './api-client';

/**
 * ai-chat.ts — klien AI Chat (Fase 3 §3.4; disambungkan ke backend di Fase F).
 *
 * Backend kini punya `POST /api/v1/ai/chat` (**stub Fase F**) yang selalu membalas
 * 200 dengan:
 *
 *     {"ok": false, "reason": "not_implemented", "schema_version": "1.0"}
 *
 * Kontrak `send()` tidak berubah: ia **selalu** mengembalikan `AiChatMessage`
 * (tidak pernah throw). Kalau backend menjawab `ok:false` — atau endpoint tidak
 * bisa dihubungi — jawabannya pesan asisten yang menyebut alasannya, sehingga UI
 * tetap punya balasan untuk ditampilkan.
 *
 * TODO(Fase 7+): saat LLM nyata tersedia, `ok:true` + `content` dari backend
 * dipakai langsung; `stream()` (SSE/WebSocket) menyusul.
 */

export const AI_CHAT_PATH = '/ai/chat';
export const STUB_PREFIX = '[STUB]';
export const FALLBACK_REASON = 'not_implemented';

export interface AiChatMessage {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  created_at: string;
}

export interface AiChatClient {
  send(message: string, context?: Record<string, unknown>): Promise<AiChatMessage>;
  stream?(message: string, onChunk: (chunk: string) => void): Promise<void>;
}

interface ParsedReply {
  ok: boolean;
  content: string | null;
  reason: string;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/** PURE — baca body `ai/chat`: kontrak `{ok, content?, reason?, schema_version}`. */
export function parseAiReply(raw: unknown): ParsedReply {
  if (!isRecord(raw)) return { ok: false, content: null, reason: 'invalid_response' };

  const content = raw['content'];
  const reason = raw['reason'];

  return {
    ok: raw['ok'] === true,
    content: typeof content === 'string' && content.trim().length > 0 ? content.trim() : null,
    reason: typeof reason === 'string' && reason.trim().length > 0 ? reason : FALLBACK_REASON,
  };
}

/** PURE — susun balasan asisten saat backend belum punya jawaban nyata. */
export function stubReply(
  question: string,
  contextKeys: readonly string[],
  reason: string
): string {
  const parts = [`${STUB_PREFIX} AI Chat belum tersedia (reason: ${reason}).`];
  if (question.length > 0) parts.push(`Pertanyaanmu: "${question}".`);
  if (contextKeys.length > 0) parts.push(`Konteks diterima: ${contextKeys.join(', ')}.`);

  return parts.join(' ');
}

export function createAiChatClient(apiClient: ApiClient): AiChatClient {
  return {
    async send(message: string, context?: Record<string, unknown>): Promise<AiChatMessage> {
      const question = message.trim();
      const contextKeys = context === undefined ? [] : Object.keys(context);

      let content: string | null = null;

      try {
        const response = await apiClient.post<unknown>(AI_CHAT_PATH, {
          message: question,
          ...(context === undefined ? {} : { context }),
        });
        const reply = parseAiReply(response.data);
        content = reply.ok ? reply.content : stubReply(question, contextKeys, reply.reason);
      } catch {
        // `api-client` tidak melempar; tapi kalau ada lapisan lain yang melempar,
        // UI tetap harus dapat balasan (jangan sampai chat mati).
        content = stubReply(question, contextKeys, 'network_error');
      }

      return {
        id: generateUUID(),
        role: 'assistant',
        content: content ?? stubReply(question, contextKeys, FALLBACK_REASON),
        created_at: new Date().toISOString(),
      };
    },
  };
}
