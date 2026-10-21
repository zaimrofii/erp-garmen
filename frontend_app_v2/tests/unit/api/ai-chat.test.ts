import { describe, expect, it, vi } from 'vitest';
import type { ApiClient } from '@/integrations/api-client';
import { parseChatResponse, sendChatMessage, AI_CHAT_PATH } from '@/api/aiChat';

/**
 * Sprint E.1 — adapter chat AI (`/ai/chat`, kontrak §2–§3).
 * Fake ApiClient: tidak ada HTTP nyata, hanya memeriksa path/body yang dikirim.
 */

function fakeClient(data: unknown, ok = true, status = 200): ApiClient {
  return {
    post: vi.fn(async () => ({ ok, status, data })),
  } as unknown as ApiClient;
}

const FULL_RESPONSE = {
  ok: true,
  answer: 'Scrap naik 2,1 poin.',
  tool_calls: [
    {
      tool: 'mcp-analytics',
      input: { metric_id: 'garment.scrap_rate' },
      output_summary: 'scrap_rate=5.8%',
    },
  ],
  confidence_score: 0.92,
  impact_score: 'LOW',
  hitl_required: false,
  hitl_request_id: null,
  decision_gate_result: 'RULE_HIT',
  tokens: { prompt: 0, completion: 0, total_cost_usd: 0 },
  cache_hit: false,
  latency_ms: 12,
};

describe('Sprint E.1 — sendChatMessage', () => {
  it('parse response ok:true lengkap', async () => {
    const client = fakeClient(FULL_RESPONSE);
    const result = await sendChatMessage(client, { message: 'kenapa scrap naik?' });

    expect(result.ok).toBe(true);
    if (!result.ok) return;

    expect(result.answer).toBe('Scrap naik 2,1 poin.');
    expect(result.tool_calls).toHaveLength(1);
    expect(result.tool_calls[0]?.tool).toBe('mcp-analytics');
    expect(result.confidence_score).toBe(0.92);
    expect(result.tokens.total_cost_usd).toBe(0);
    expect(result.decision_gate_result).toBe('RULE_HIT');
    expect(result.latency_ms).toBe(12);
  });

  it('POST ke /ai/chat dengan channel default DESKTOP', async () => {
    const client = fakeClient(FULL_RESPONSE);
    await sendChatMessage(client, { message: '  halo  ' });

    expect(client.post).toHaveBeenCalledWith(AI_CHAT_PATH, {
      message: 'halo',
      channel: 'DESKTOP',
    });
  });

  it('parse response ok:false (not_implemented)', async () => {
    const client = fakeClient({
      ok: false,
      reason: 'not_implemented',
      schema_version: '1.0',
    });
    const result = await sendChatMessage(client, { message: 'halo' });

    expect(result).toEqual({ ok: false, error: 'not_implemented' });
  });

  it('ok:false dengan error+detail', async () => {
    const client = fakeClient({ ok: false, error: 'bad_context', detail: 'resource_id' });
    const result = await sendChatMessage(client, { message: 'halo' });

    expect(result).toEqual({ ok: false, error: 'bad_context', detail: 'resource_id' });
  });

  it('kegagalan jaringan menjadi network_error (tidak throw)', async () => {
    const client = {
      post: vi.fn(async () => ({
        ok: false,
        status: 0,
        error: { kind: 'network', message: 'offline' },
      })),
    } as unknown as ApiClient;

    await expect(sendChatMessage(client, { message: 'halo' })).resolves.toEqual({
      ok: false,
      error: 'network_error',
      detail: 'offline',
    });
  });

  it('parseChatResponse menolak bentuk asing', () => {
    expect(parseChatResponse(null)).toBeNull();
    expect(parseChatResponse({ ok: false })).toBeNull();
  });
});
