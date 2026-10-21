import { readFileSync } from 'node:fs';
import path from 'node:path';
import { createElement } from 'react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { AIChatPage } from '@/pages/ai/AIChatPage';
import { buildChatRequest, historyFromMessages } from '@/lib/ai-context';
import {
  chatReducer,
  createInitialChatState,
  INITIAL_AI_CHAT_STATE,
} from '@/hooks/useAIChat';
import { htmlOf, textOf } from '../../helpers/react-tree';
import type { AIChatResponse, AIChatUiMessage } from '@/types/ai-chat';

/**
 * Sprint E.2 — halaman `/ai/chat` (channel DESKTOP).
 *
 * Render nyata lewat `react-dom/server` (tanpa jsdom) + uji PURE untuk state/history.
 * Event browser (klik) tidak diklaim — wiring form diverifikasi dari SUMBER halaman,
 * pola yang sama dengan test halaman lain di repo ini.
 */

const ROOT = path.resolve(import.meta.dirname, '../../..');
const PAGE = readFileSync(path.join(ROOT, 'src/pages/ai/AIChatPage.tsx'), 'utf8');

function render(initialMessages: AIChatUiMessage[] = []): { html: string; text: string } {
  const tree = createElement(
    MemoryRouter,
    { initialEntries: ['/ai/chat'] },
    createElement(AIChatPage, { initialMessages }),
  );

  return { html: htmlOf(tree), text: textOf(tree) };
}

const RESPONSE: AIChatResponse = {
  ok: true,
  answer: 'Scrap di Cutting naik 2,1 poin.',
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

function assistant(response: AIChatResponse): AIChatUiMessage {
  return {
    id: 'a1',
    role: 'assistant',
    content: response.answer,
    response,
  };
}

describe('Sprint E.2 — render halaman', () => {
  it('welcome tampil saat percakapan kosong', () => {
    const { text } = render();

    expect(text).toMatch(/Halo! Ada yang bisa saya bantu\?/);
    expect(text).toContain('produk, order, bundle, stok, metrik produksi');
  });

  it('welcome hilang setelah ada pesan', () => {
    const { text } = render([assistant(RESPONSE)]);

    expect(text).not.toContain('Halo! Ada yang bisa saya bantu?');
    expect(text).toContain('Scrap di Cutting naik 2,1 poin.');
  });

  it('welcome tidak masuk history payload', () => {
    expect(historyFromMessages([])).toEqual([]);
    expect(historyFromMessages([{ id: 'u1', role: 'user', content: 'halo' }])).toEqual([
      { role: 'user', content: 'halo' },
    ]);
  });

  it('form + input + tombol Kirim tampil', () => {
    const { html, text } = render();

    expect(html).toContain('<form');
    expect(html).toContain('placeholder="Tanya tentang produksi..."');
    expect(html).toContain('>Kirim<');
    expect(text).toContain('Kanal DESKTOP');
  });

  it('answer response tampil', () => {
    const { text } = render([assistant(RESPONSE)]);

    expect(text).toContain('Scrap di Cutting naik 2,1 poin.');
  });

  it('tool_calls dirender sebagai collapsible', () => {
    const { html, text } = render([assistant(RESPONSE)]);

    expect(html).toContain('<details');
    expect(text).toMatch(/Tool dipanggil\s*\(\s*1\s*\)/);
    expect(text).toContain('mcp-analytics');
    expect(text).toContain('scrap_rate=5.8%');
  });

  it('confidence 0.92 → badge hijau (text-success)', () => {
    const { html, text } = render([assistant(RESPONSE)]);

    expect(text).toMatch(/confidence\s+0\.92/);
    expect(html).toContain('text-success');
  });

  it('hitl_required=true → banner persetujuan', () => {
    const { text } = render([
      assistant({ ...RESPONSE, hitl_required: true, hitl_request_id: 7 }),
    ]);

    expect(text).toContain('Perlu persetujuan');
    expect(text).toContain('#7');
  });

  it('cache_hit=true → badge "dari cache"', () => {
    const { text } = render([assistant({ ...RESPONSE, cache_hit: true })]);

    expect(text).toContain('dari cache');
  });

  it('badge decision gate tampil + 0 tokens', () => {
    const { text } = render([assistant(RESPONSE)]);

    expect(text).toContain('RULE_HIT');
    expect(text).toMatch(/0\s+tokens/);
  });
});

describe('Sprint E.2 — wiring request', () => {
  it('halaman memakai channel DESKTOP + konteks minimal', () => {
    expect(PAGE).toMatch(/chat\.sendMessage\(message, context, ["']DESKTOP["']\)/);
    expect(PAGE).toContain('minimalContext');
    expect(PAGE).toContain('validateContextForSubmit');
  });

  it('fokus input dikembalikan setelah submit selesai', () => {
    expect(PAGE).toContain('useRef');
    expect(PAGE).toContain('ref={inputRef}');
    expect(PAGE).toMatch(/inputRef\.current\?\.focus\(\)/);
    expect(PAGE).toMatch(/\[chat\.loading\]/);
  });

  it('history terkirim pada request kedua (state reducer)', () => {
    let state = createInitialChatState();

    state = chatReducer(state, {
      type: 'send_start',
      message: { id: 'u1', role: 'user', content: 'kenapa scrap naik?' },
      channel: 'DESKTOP',
    });
    state = chatReducer(state, {
      type: 'assistant',
      message: assistant(RESPONSE),
    });

    const history = historyFromMessages(state.messages);
    const request = buildChatRequest('dan rework?', history, null, 'DESKTOP');

    expect(request.history).toHaveLength(2);
    expect(request.history?.[0]).toEqual({ role: 'user', content: 'kenapa scrap naik?' });
    expect(request.history?.[1]?.role).toBe('assistant');
    expect(request.channel).toBe('DESKTOP');
  });

  it('error backend dipetakan ke pesan ramah', () => {
    const state = chatReducer(INITIAL_AI_CHAT_STATE, {
      type: 'error',
      error: 'forbidden_context',
      message: {
        id: 'e1',
        role: 'assistant',
        content:
          'Anda tidak berhak melihat data konteks ini. Ajukan pertanyaan tanpa konteks atau hubungi supervisor.',
        error: 'forbidden_context',
      },
    });

    expect(state.error).toBe('forbidden_context');
    expect(state.loading).toBe(false);
    expect(state.messages.at(-1)?.content).toContain('tidak berhak');
  });
});
