import { readFileSync } from 'node:fs';
import path from 'node:path';
import { createElement } from 'react';
import { describe, expect, it } from 'vitest';
import {
  ChatMessageList,
} from '@/components/molecules/ChatMessageList';
import { confidenceClass } from '@/lib/ai-chat-display';
import { htmlOf, textOf } from '../../helpers/react-tree';
import type { AIChatResponse, AIChatUiMessage } from '@/types/ai-chat';

/** Sprint E.3 — ChatMessageList (bubble + metadata §3), SSR tanpa jsdom. */

const ROOT = path.resolve(import.meta.dirname, '../../..');
const SOURCE = readFileSync(
  path.join(ROOT, 'src/components/molecules/ChatMessageList.tsx'),
  'utf8',
);

const RESPONSE: AIChatResponse = {
  ok: true,
  answer: 'Scrap naik.',
  tool_calls: [
    { tool: 'mcp-analytics', input: {}, output_summary: 'scrap_rate=5.8%' },
  ],
  confidence_score: 0.7,
  impact_score: 'LOW',
  hitl_required: true,
  hitl_request_id: 3,
  decision_gate_result: 'LLM_NEEDED',
  tokens: { prompt: 10, completion: 20, total_cost_usd: 0.001 },
  cache_hit: true,
  latency_ms: 9,
};

function render(messages: AIChatUiMessage[], loading = false): { html: string; text: string } {
  const tree = createElement(ChatMessageList, { messages, loading });
  return { html: htmlOf(tree), text: textOf(tree) };
}

describe('Sprint E.3 — ChatMessageList', () => {
  it('bubble user', () => {
    const { html, text } = render([
      { id: 'u1', role: 'user', content: 'kenapa scrap naik?' },
    ]);

    expect(html).toContain('data-testid="ai-message-user"');
    expect(html).toContain('bg-primary');
    expect(text).toContain('kenapa scrap naik?');
  });

  it('bubble assistant + tool_calls collapsible', () => {
    const { html, text } = render([
      { id: 'a1', role: 'assistant', content: RESPONSE.answer, response: RESPONSE },
    ]);

    expect(html).toContain('data-testid="ai-message-assistant"');
    expect(html).toContain('<details');
    expect(text).toContain('mcp-analytics');
    expect(text).toContain('scrap_rate=5.8%');
  });

  it('loading → spinner role=status', () => {
    const { html, text } = render([], true);

    expect(html).toContain('role="status"');
    expect(text).toContain('menyusun jawaban');
  });

  it('hitl_required → banner persetujuan', () => {
    const { text } = render([
      { id: 'a1', role: 'assistant', content: 'x', response: RESPONSE },
    ]);

    expect(text).toContain('Perlu persetujuan');
    expect(text).toContain('#3');
  });

  it('confidenceClass: hijau/kuning/merah', () => {
    expect(confidenceClass(0.92)).toBe('text-success');
    expect(confidenceClass(0.7)).toBe('text-warning');
    expect(confidenceClass(0.4)).toBe('text-danger');
    expect(confidenceClass(null)).toBe('text-muted-foreground');
  });

  it('cache_hit + token footer tampil', () => {
    const { text } = render([
      { id: 'a1', role: 'assistant', content: 'x', response: RESPONSE },
    ]);

    expect(text).toContain('dari cache');
    expect(text).toMatch(/30\s+tokens/);
  });

  it('assistant markdown **bold** dirender <strong>', () => {
    const { html } = render([
      {
        id: 'a-markdown',
        role: 'assistant',
        content: 'Scrap **naik** di SEWING-2.',
        response: RESPONSE,
      },
    ]);

    expect(html).toContain('<strong>naik</strong>');
  });

  it('user markdown tetap plain text (tidak dirender)', () => {
    const { html, text } = render([
      { id: 'u-markdown', role: 'user', content: 'Scrap **naik**?' },
    ]);

    expect(html).not.toContain('<strong>');
    expect(text).toContain('**naik**');
  });

  it('auto-scroll ke bawah saat jumlah pesan berubah', () => {
    const { html } = render([
      { id: 'u1', role: 'user', content: 'halo' },
    ]);

    expect(html).toContain('data-testid="chat-bottom-sentinel"');
    expect(SOURCE).toContain('scrollIntoView({ behavior: "smooth" })');
    expect(SOURCE).toContain('[messages.length]');
  });
});
