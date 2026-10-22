import { createElement } from 'react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { ChatMessageList } from '@/components/molecules/ChatMessageList';
import { parseChatResponse } from '@/api/real/aiChat';
import { htmlOf, textOf } from '../../helpers/react-tree';
import type { AIChatResponse, AIChatUiMessage } from '@/types/ai-chat';

const RESPONSE: AIChatResponse = {
  ok: true,
  answer: '**Masalah:** Scrap naik ke 21%',
  tool_calls: [],
  confidence_score: 0.82,
  impact_score: 'LOW',
  hitl_required: false,
  hitl_request_id: null,
  decision_gate_result: 'LLM_NEEDED',
  tokens: { prompt: 10, completion: 20, total_cost_usd: 0 },
  cache_hit: false,
  latency_ms: 5,
  chart_data: {
    type: 'line',
    title: 'Tren Scrap',
    unit: '%',
    data: [
      { label: '18 Okt', value: 1.6 },
      { label: '20 Okt', value: 21 },
    ],
  },
};

const SUGGEST_TEXT = `**Masalah:** Scrap SEWING-2 naik ke 21%

**Usulan aksi:**

1. 🟡 **rework BND-A-12**
   - Prioritas: MEDIUM (keyakinan 82%)
2. 🟢 **pindah BND-A-14 ke SEWING-1**
   - Prioritas: LOW (keyakinan 60%)

_Semua aksi menunggu persetujuan manusia (HITL)._`;

function render(messages: AIChatUiMessage[]): { html: string; text: string } {
  const tree = createElement(
    MemoryRouter,
    null,
    createElement(ChatMessageList, { messages }),
  );

  return { html: htmlOf(tree), text: textOf(tree) };
}

const SUGGEST_MESSAGE: AIChatUiMessage = {
  id: 'm1',
  role: 'assistant',
  content: SUGGEST_TEXT,
  response: RESPONSE,
};

describe('Fix #18 — format jawaban chat', () => {
  it('SUGGEST_ACTION tampil sebagai bullet, bukan JSON', () => {
    const { html, text } = render([SUGGEST_MESSAGE]);

    expect(text).toContain('Usulan aksi');
    expect(text).toContain('rework BND-A-12');
    expect(text).toContain('82%');
    expect(html).not.toContain('{"problem"');
    expect(html).not.toContain('proposed_actions');
  });

  it('chart_data dirender sebagai AIChart', () => {
    const { html, text } = render([SUGGEST_MESSAGE]);

    expect(html).toContain('data-testid="ai-chart"');
    expect(text).toContain('Tren Scrap');
  });

  it('tanpa chart_data tidak merender chart', () => {
    const message: AIChatUiMessage = {
      ...SUGGEST_MESSAGE,
      response: { ...RESPONSE, chart_data: null },
    };

    expect(render([message]).html).not.toContain('data-testid="ai-chart"');
  });

  it('adapter parse chart_data dengan benar', () => {
    const parsed = parseChatResponse({
      ok: true,
      answer: 'Scrap naik.',
      chart_data: {
        type: 'line',
        title: 'Tren Scrap',
        unit: '%',
        data: [
          { label: '18 Okt', value: 1.6 },
          { label: '20 Okt', value: 21 },
        ],
      },
    });

    expect(parsed?.chart_data?.title).toBe('Tren Scrap');
    expect(parsed?.chart_data?.data).toHaveLength(2);
    expect(parsed?.chart_data?.unit).toBe('%');
  });

  it('chart_data rusak → null (tidak crash)', () => {
    const parsed = parseChatResponse({ ok: true, answer: 'x', chart_data: { data: [] } });

    expect(parsed?.chart_data).toBeNull();
  });

  it('blockquote markdown dirender (highlight)', () => {
    const message: AIChatUiMessage = {
      id: 'm2',
      role: 'assistant',
      content: '> Scrap naik tajam kemarin.\n\nCek SEWING-2.',
    };
    const { html } = render([message]);

    expect(html).toContain('<blockquote');
  });
});
