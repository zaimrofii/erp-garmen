import { readFileSync } from 'node:fs';
import path from 'node:path';
import { createElement } from 'react';
import { describe, expect, it } from 'vitest';
import { FloatingAIAssistant } from '@/components/organisms/FloatingAIAssistant';
import { htmlOf, textOf } from '../../helpers/react-tree';
import type { AIChatContext, AIChatResponse, AIChatUiMessage } from '@/types/ai-chat';

/**
 * Sprint E.3 — FloatingAIAssistant (drawer, bukan redirect).
 * SSR + SOURCE: event klik tidak dijalankan (tanpa jsdom); wiring diverifikasi
 * dari sumber komponen (pola yang sama dengan test komponen lain).
 */

const ROOT = path.resolve(import.meta.dirname, '../../..');
const SOURCE = readFileSync(
  path.join(ROOT, 'src/components/organisms/FloatingAIAssistant.tsx'),
  'utf8',
);

const PRODUCT_CONTEXT: AIChatContext = {
  page_type: 'detail',
  route: '/master/products/123',
  resource_type: 'product',
  resource_id: '123',
  filters: {},
  visible_fields_snapshot: { name: 'Kaos Polos', code: 'KTS-001' },
};

const RESPONSE: AIChatResponse = {
  ok: true,
  answer: 'Harga jual produk ini Rp15.000.',
  tool_calls: [],
  confidence_score: 0.92,
  impact_score: 'LOW',
  hitl_required: false,
  hitl_request_id: null,
  decision_gate_result: 'RULE_HIT',
  tokens: { prompt: 0, completion: 0, total_cost_usd: 0 },
  cache_hit: false,
  latency_ms: 8,
};

function render(options: {
  context?: AIChatContext | null;
  open?: boolean;
  disabled?: boolean;
  messages?: AIChatUiMessage[];
} = {}): { html: string; text: string } {
  const tree = createElement(FloatingAIAssistant, {
    context: options.context === undefined ? PRODUCT_CONTEXT : options.context,
    initialOpen: options.open ?? false,
    disabled: options.disabled,
    initialMessages: options.messages,
  });

  return { html: htmlOf(tree), text: textOf(tree) };
}

describe('Sprint E.3 — ikon & drawer', () => {
  it('ikon fixed pojok kanan-bawah + pulse saat idle', () => {
    const { html } = render();

    expect(html).toContain('fixed bottom-6 right-6');
    expect(html).toContain('animate-pulse');
    expect(html).toContain('aria-expanded="false"');
    expect(html).not.toContain('role="dialog"');
  });

  it('klik ikon membuka panel (aria-expanded=true)', () => {
    const { html } = render({ open: true });

    expect(html).toContain('aria-expanded="true"');
    expect(html).toContain('role="dialog"');
    expect(SOURCE).toContain('setOpen(true)');
  });

  it('ESC menutup panel (listener keydown)', () => {
    expect(SOURCE).toContain('window.addEventListener("keydown"');
    expect(SOURCE).toContain('event.key === "Escape"');
    expect(SOURCE).toContain('setOpen(false)');
  });

  it('tombol Tutup menutup panel', () => {
    const { text } = render({ open: true });

    expect(text).toContain('Tutup');
    expect(SOURCE).toContain('aria-label="Tutup"');
  });

  it('panel TIDAK navigate ke /ai/chat', () => {
    expect(SOURCE).not.toContain('navigate(');
    expect(SOURCE).not.toContain('/ai/chat');
  });
});

describe('Sprint E.3 — konteks & pengiriman', () => {
  it('welcome tampil saat drawer kosong', () => {
    const { text } = render({ open: true });

    expect(text).toMatch(/Halo! Ada yang bisa saya bantu\?/);
  });

  it('welcome hilang saat sudah ada pesan', () => {
    const { text } = render({
      open: true,
      messages: [{ id: 'u1', role: 'user', content: 'halo' }],
    });

    expect(text).not.toContain('Halo! Ada yang bisa saya bantu?');
  });

  it('header menampilkan konteks produk', () => {
    const { text } = render({ open: true });

    expect(text).toContain('Asisten AI');
    expect(text).toContain('Produk: Kaos Polos');
  });

  it('context null → konteks minimal', () => {
    const { text } = render({ context: null, open: true });

    expect(text).toContain('Tanpa konteks');
    expect(SOURCE).toContain('minimalContext(pathname)');
  });

  it('mengirim channel FLOATING', () => {
    expect(SOURCE).toContain('chat.sendMessage(message, effectiveContext, "FLOATING")');
  });

  it('fokus input dikembalikan setelah submit selesai', () => {
    expect(SOURCE).toContain('useRef');
    expect(SOURCE).toContain('ref={inputRef}');
    expect(SOURCE).toMatch(/finally\s*\{[\s\S]{0,120}inputRef\.current\?\.focus\(\)/);
  });

  it('answer tampil di panel', () => {
    const { text } = render({
      open: true,
      messages: [
        {
          id: 'a1',
          role: 'assistant',
          content: RESPONSE.answer,
          response: RESPONSE,
        },
      ],
    });

    expect(text).toContain('Harga jual produk ini Rp15.000.');
  });

  it('disabled → ikon tidak dirender', () => {
    const { html } = render({ disabled: true });

    expect(html).toBe('');
  });
});
