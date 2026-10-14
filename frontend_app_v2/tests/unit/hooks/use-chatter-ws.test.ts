import { describe, expect, it } from 'vitest';
import { computeReconnectDelay } from '@/core/useWebSocket';
import {
  applyWsMessageToChatter,
  buildChatterWsUrl,
  isChatterWsEnabled,
  mergeChatterWsEvent,
} from '@/hooks/useChatterWs';
import { mergeChatterPreview } from '@/lib/chatter-merge';
import type { ChatterEvent } from '@/lib/schemas/chatter.schema';

/** F4 — hook chatter real-time: langganan (query param), prepend, dedup, no-op saat WS mati. */

const BASE = 'ws://localhost:8000/ws';

function chatterEvent(id: string, createdAt: string, summary = `event ${id}`): ChatterEvent {
  return {
    id,
    actor: { id: 'op-1', name: 'Operator Satu' },
    type: 'BUNDLE_STATE_CHANGED',
    summary,
    payload: { to: 'CUTTING' },
    created_at: createdAt,
  };
}

/** Envelope NYATA backend (`core/event_bus/websocket.py::channel_message`). */
function envelope(event: ChatterEvent, resource = 'bundles', id: number | string = 16): unknown {
  return {
    type: 'bundle_event',
    resource,
    id,
    event_name: event.type,
    occurred_at: '2026-10-08T10:00:00Z',
    event,
  };
}

const PREVIEW = [
  chatterEvent('evt-2', '2026-10-08T09:00:00Z'),
  chatterEvent('evt-1', '2026-10-08T08:00:00Z'),
];

describe('F4/4.1 — buildChatterWsUrl (langganan lewat query param)', () => {
  it('host polos → path /events/ + resource & id', () => {
    expect(buildChatterWsUrl(BASE, 'bundles', 16)).toBe(
      'ws://localhost:8000/ws/events/?resource=bundles&id=16'
    );
  });

  it('work-orders memakai nama resource REST (backend → group `work_order.<id>`)', () => {
    expect(buildChatterWsUrl(BASE, 'work-orders', 5)).toBe(
      'ws://localhost:8000/ws/events/?resource=work-orders&id=5'
    );
  });

  it('idempoten walau base sudah ber-path /events/', () => {
    expect(buildChatterWsUrl('ws://localhost:8000/ws/events/', 'bundles', 16)).toBe(
      'ws://localhost:8000/ws/events/?resource=bundles&id=16'
    );
  });

  it('base kosong / target belum valid → string kosong (jangan connect)', () => {
    expect(buildChatterWsUrl('', 'bundles', 16)).toBe('');
    expect(buildChatterWsUrl(BASE, 'bundles', undefined)).toBe('');
    expect(buildChatterWsUrl(BASE, 'bundles', '')).toBe('');
  });
});

describe('F4/4.4 — isChatterWsEnabled (WS_ENABLED=false → no-op, tanpa error)', () => {
  it('VITE_WS_ENABLED=false → tidak langganan', () => {
    expect(isChatterWsEnabled({ wsEnabled: false, resource: 'bundles', id: 16 })).toBe(false);
  });

  it('resource belum dimuat (id undefined) → tidak langganan', () => {
    expect(isChatterWsEnabled({ wsEnabled: true, resource: 'bundles', id: undefined })).toBe(false);
  });

  it('WS aktif + target valid → langganan', () => {
    expect(isChatterWsEnabled({ wsEnabled: true, resource: 'bundles', id: 16 })).toBe(true);
    expect(isChatterWsEnabled({ wsEnabled: true, resource: 'bundles', id: '16' })).toBe(true);
  });

  it('resource kosong → tidak langganan', () => {
    expect(isChatterWsEnabled({ wsEnabled: true, resource: '   ', id: 16 })).toBe(false);
  });
});

describe('F4/4.2 — applyWsMessageToChatter (prepend + dedup + skip)', () => {
  it('envelope `bundle_event` → event chatter di-prepend ke depan', () => {
    const merged = applyWsMessageToChatter(
      PREVIEW,
      JSON.stringify(envelope(chatterEvent('evt-3', '2026-10-08T10:00:00Z')))
    );

    expect(merged.map((item) => item.id)).toEqual(['evt-3', 'evt-2', 'evt-1']);
    expect(merged[0]?.summary).toBe('event evt-3');
  });

  it('envelope `work_order_event` juga diproses', () => {
    const merged = applyWsMessageToChatter(
      [],
      envelope(chatterEvent('wo-1', '2026-10-08T10:00:00Z'), 'work-orders', 5)
    );

    expect(merged.map((item) => item.id)).toEqual(['wo-1']);
  });

  it('pesan kontrol (connected/subscribed/pong) → array SAMA (tidak men-trigger render)', () => {
    const connected = JSON.stringify({ type: 'connected', groups: ['events', 'bundle.16'] });

    expect(applyWsMessageToChatter(PREVIEW, connected)).toBe(PREVIEW);
    expect(applyWsMessageToChatter(PREVIEW, JSON.stringify({ type: 'pong' }))).toBe(PREVIEW);
  });

  it('JSON rusak / event bukan chatter → array SAMA (fail-safe, bukan crash)', () => {
    const notChatter = JSON.stringify({
      type: 'bundle_event',
      resource: 'bundles',
      id: 16,
      event_name: 'X',
      event: { bukan: 'chatter' },
    });

    expect(applyWsMessageToChatter(PREVIEW, '{bukan-json')).toBe(PREVIEW);
    expect(applyWsMessageToChatter(PREVIEW, notChatter)).toBe(PREVIEW);
    expect(applyWsMessageToChatter(PREVIEW, null)).toBe(PREVIEW);
  });

  it('dedup by id — event yang sudah tampil tidak dobel', () => {
    const merged = applyWsMessageToChatter(
      PREVIEW,
      envelope(chatterEvent('evt-2', '2026-10-08T09:30:00Z', 'evt-2 diperbarui'))
    );

    expect(merged.map((item) => item.id)).toEqual(['evt-2', 'evt-1']);
    expect(merged).toHaveLength(2);
  });

  it('dipotong CHATTER_PREVIEW_LIMIT (5) walau event mengalir terus', () => {
    let accumulated: ChatterEvent[] = [];

    for (let index = 0; index < 7; index += 1) {
      accumulated = applyWsMessageToChatter(
        accumulated,
        envelope(chatterEvent(`ws-${index}`, `2026-10-08T1${index}:00:00Z`))
      );
    }

    expect(accumulated).toHaveLength(5);
    expect(accumulated[0]?.id).toBe('ws-6');
  });

  it('mergeChatterWsEvent menerima WsEvent yang SUDAH diparse engine', () => {
    const chatter = chatterEvent('evt-9', '2026-10-08T11:00:00Z');
    const merged = mergeChatterWsEvent(PREVIEW, {
      resource: 'bundles',
      event_type: 'BUNDLE_STATE_CHANGED',
      payload: chatter as unknown as Record<string, unknown>,
      id: '16',
      event: chatter as unknown as Record<string, unknown>,
    });

    expect(merged[0]?.id).toBe('evt-9');
  });
});

describe('F4/4.2 — gabung dengan hasil fetch (fallback WS mati)', () => {
  it('tanpa event WS → preview hasil fetch utuh (4.4)', () => {
    expect(mergeChatterPreview(PREVIEW, [])).toEqual(PREVIEW);
  });

  it('event WS terbaru di depan hasil fetch', () => {
    const merged = mergeChatterPreview(PREVIEW, [chatterEvent('evt-3', '2026-10-08T10:00:00Z')]);

    expect(merged.map((item) => item.id)).toEqual(['evt-3', 'evt-2', 'evt-1']);
  });
});

describe('F4/4.5 — reconnect memakai computeReconnectDelay (engine, tanpa implementasi baru)', () => {
  it('backoff eksponensial 1s → 2s → 4s, dibatasi 30s', () => {
    expect(computeReconnectDelay(0)).toBe(1000);
    expect(computeReconnectDelay(1)).toBe(2000);
    expect(computeReconnectDelay(2)).toBe(4000);
    expect(computeReconnectDelay(4)).toBe(16000);
    expect(computeReconnectDelay(5)).toBe(30000);
    expect(computeReconnectDelay(50)).toBe(30000);
  });
});
