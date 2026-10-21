import { describe, expect, it } from 'vitest';
import {
  chatReducer,
  createInitialChatState,
  INITIAL_AI_CHAT_STATE,
} from '@/hooks/useAIChat';
import { historyFromMessages } from '@/lib/ai-context';
import type { AIChatResponse } from '@/types/ai-chat';

/**
 * Sprint E.3 — state `useAIChat` (PURE reducer). Hook sendiri hanya merangkai
 * reducer + `sendChatMessage`, sehingga transisi di bawah = perilaku hook.
 */

const RESPONSE: AIChatResponse = {
  ok: true,
  answer: 'Jawaban',
  tool_calls: [],
  confidence_score: 0.9,
  impact_score: 'LOW',
  hitl_required: false,
  hitl_request_id: null,
  decision_gate_result: 'RULE_HIT',
  tokens: { prompt: 0, completion: 0, total_cost_usd: 0 },
  cache_hit: false,
  latency_ms: 5,
};

describe('Sprint E.3 — useAIChat reducer', () => {
  it('sendMessage menambah pesan user + loading', () => {
    const state = chatReducer(INITIAL_AI_CHAT_STATE, {
      type: 'send_start',
      message: { id: 'u1', role: 'user', content: 'halo' },
      channel: 'FLOATING',
    });

    expect(state.messages).toHaveLength(1);
    expect(state.messages[0]?.role).toBe('user');
    expect(state.loading).toBe(true);
    expect(state.lastMessage).toBe('halo');
    expect(state.lastChannel).toBe('FLOATING');
  });

  it('assistant menambah jawaban + loading false', () => {
    let state = createInitialChatState([
      { id: 'u1', role: 'user', content: 'halo' },
    ]);
    state = chatReducer(state, {
      type: 'assistant',
      message: { id: 'a1', role: 'assistant', content: 'Jawaban', response: RESPONSE },
    });

    expect(state.messages).toHaveLength(2);
    expect(state.messages[1]?.response?.answer).toBe('Jawaban');
    expect(state.loading).toBe(false);
  });

  it('error mengisi state error + pesan asisten', () => {
    const state = chatReducer(INITIAL_AI_CHAT_STATE, {
      type: 'error',
      error: 'not_implemented',
      message: { id: 'e1', role: 'assistant', content: 'Fitur AI belum aktif.' },
    });

    expect(state.error).toBe('not_implemented');
    expect(state.messages.at(-1)?.content).toContain('belum aktif');
    expect(state.loading).toBe(false);
  });

  it('reset mengosongkan messages', () => {
    const filled = createInitialChatState([
      { id: 'u1', role: 'user', content: 'halo' },
    ]);

    expect(chatReducer(filled, { type: 'reset' })).toEqual(INITIAL_AI_CHAT_STATE);
  });

  it('history untuk request berikutnya berisi percakapan sebelumnya', () => {
    let state = createInitialChatState();
    state = chatReducer(state, {
      type: 'send_start',
      message: { id: 'u1', role: 'user', content: 'halo' },
      channel: 'FLOATING',
    });
    state = chatReducer(state, {
      type: 'assistant',
      message: { id: 'a1', role: 'assistant', content: 'Jawaban', response: RESPONSE },
    });

    const history = historyFromMessages(state.messages);

    expect(history).toEqual([
      { role: 'user', content: 'halo' },
      { role: 'assistant', content: 'Jawaban' },
    ]);
  });

  it('createInitialChatState menerima riwayat awal', () => {
    const state = createInitialChatState([
      { id: 'a0', role: 'assistant', content: 'riwayat' },
    ]);

    expect(state.messages).toHaveLength(1);
    expect(state.loading).toBe(false);
  });
});
