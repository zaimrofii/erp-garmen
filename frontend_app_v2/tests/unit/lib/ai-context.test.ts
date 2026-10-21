import { describe, expect, it } from 'vitest';
import {
  buildChatContext,
  buildChatRequest,
  chatErrorMessage,
  contextLabel,
  filtersFromSearch,
  historyFromMessages,
  minimalContext,
  validateContextForSubmit,
} from '@/lib/ai-context';
import type { AIChatUiMessage } from '@/types/ai-chat';

/**
 * Sprint E.1 — helper konteks chat (kontrak §4–§5). PURE, tanpa DOM.
 */

const DETAIL_LOCATION = { pathname: '/master/products/123', search: '' };
const LIST_LOCATION = { pathname: '/master/products', search: '?search=kaos&active=true' };

describe('Sprint E.1 — buildChatContext', () => {
  it('detail → resource_id selalu string', () => {
    const context = buildChatContext(
      DETAIL_LOCATION,
      { id: '123' },
      'detail',
      'product',
      {},
      { code: 'KTS-001', name: 'Kaos Polos' },
    );

    expect(context?.page_type).toBe('detail');
    expect(context?.resource_id).toBe('123');
    expect(context?.visible_fields_snapshot).toEqual({
      code: 'KTS-001',
      name: 'Kaos Polos',
    });
  });

  it('detail tanpa id → null (caller pakai konteks minimal)', () => {
    expect(
      buildChatContext({ pathname: '/master/products', search: '' }, {}, 'detail', 'product'),
    ).toBeNull();
  });

  it('list → filters dari query string', () => {
    const context = buildChatContext(LIST_LOCATION, {}, 'list', 'product');

    expect(context?.page_type).toBe('list');
    expect(context?.resource_id).toBeNull();
    expect(context?.filters).toEqual({ search: 'kaos', active: 'true' });
    expect(context?.visible_fields_snapshot).toEqual({});
  });

  it('form new → resource_id null, resource_type terisi', () => {
    const context = buildChatContext(
      { pathname: '/master/products/new', search: '' },
      {},
      'form',
      'product',
      {},
      { code: '', name: '' },
    );

    expect(context?.resource_id).toBeNull();
    expect(context?.resource_type).toBe('product');
  });

  it('report → filters period dari search', () => {
    const context = buildChatContext(
      { pathname: '/reports/sales', search: '?period=2026-10' },
      {},
      'report',
      'report',
    );

    expect(context?.filters).toEqual({ period: '2026-10' });
  });
});

describe('Sprint E.1 — validateContextForSubmit', () => {
  it('detail + resource_id null + resource_type terisi → ok:false', () => {
    const result = validateContextForSubmit({
      page_type: 'detail',
      route: '/master/products',
      resource_type: 'product',
      resource_id: null,
      filters: {},
      visible_fields_snapshot: {},
    });

    expect(result.ok).toBe(false);
    expect(result.reason).toContain('resource_type');
  });

  it('list exempt (resource_type terisi, id null) → ok:true', () => {
    const result = validateContextForSubmit({
      page_type: 'list',
      route: '/master/products',
      resource_type: 'product',
      resource_id: null,
      filters: {},
      visible_fields_snapshot: {},
    });

    expect(result).toEqual({ ok: true });
  });

  it('form new (resource_type terisi, id null) → ditolak', () => {
    const result = validateContextForSubmit({
      page_type: 'form',
      route: '/master/products/new',
      resource_type: 'product',
      resource_id: null,
      filters: {},
      visible_fields_snapshot: {},
    });

    expect(result.ok).toBe(false);
  });

  it('detail valid → ok:true', () => {
    const context = buildChatContext(DETAIL_LOCATION, { id: '1' }, 'detail', 'product');

    expect(validateContextForSubmit(context)).toEqual({ ok: true });
  });

  it('resource_id tanpa resource_type → ditolak', () => {
    expect(
      validateContextForSubmit({
        page_type: 'detail',
        route: '/x',
        resource_type: null,
        resource_id: '1',
        filters: {},
        visible_fields_snapshot: {},
      }).ok,
    ).toBe(false);
  });

  it('context null → ok:true (tanpa konteks)', () => {
    expect(validateContextForSubmit(null)).toEqual({ ok: true });
  });
});

describe('Sprint E.1 — helper pendukung', () => {
  it('filtersFromSearch melewati nilai kosong', () => {
    expect(filtersFromSearch('?a=1&b=&c=x')).toEqual({ a: '1', c: 'x' });
  });

  it('minimalContext sesuai §4 baris terakhir', () => {
    expect(minimalContext('/foo')).toEqual({
      page_type: null,
      route: '/foo',
      resource_type: null,
      resource_id: null,
      filters: {},
      visible_fields_snapshot: {},
    });
  });

  it('historyFromMessages memotong 10 item terakhir', () => {
    const messages: AIChatUiMessage[] = Array.from({ length: 12 }, (_, index) => ({
      id: String(index),
      role: index % 2 === 0 ? 'user' : 'assistant',
      content: `pesan ${index}`,
    }));

    const history = historyFromMessages(messages);

    expect(history).toHaveLength(10);
    expect(history[0]?.content).toBe('pesan 2');
    expect(history[9]?.content).toBe('pesan 11');
  });

  it('buildChatRequest memakai channel & context', () => {
    const context = minimalContext('/master/products/1');
    const request = buildChatRequest('  halo  ', [], context, 'FLOATING');

    expect(request.message).toBe('halo');
    expect(request.channel).toBe('FLOATING');
    expect(request.context).toBe(context);
  });

  it('contextLabel memakai nama snapshot', () => {
    const context = buildChatContext(
      DETAIL_LOCATION,
      { id: '123' },
      'detail',
      'product',
      {},
      { name: 'Kaos Polos' },
    );

    expect(contextLabel(context)).toBe('Produk: Kaos Polos');
    expect(contextLabel(null)).toBe('Tanpa konteks');
  });

  it('chatErrorMessage memetakan forbidden_context & not_implemented', () => {
    expect(chatErrorMessage('forbidden_context')).toContain('tidak berhak');
    expect(chatErrorMessage('not_implemented')).toContain('LLM');
    expect(chatErrorMessage('not_implemented')).not.toContain('AI_AGENT_ENABLED');
  });
});
