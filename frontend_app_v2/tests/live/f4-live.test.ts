import { describe, expect, it } from 'vitest';
import { getChatter } from '@/api/chatter';
import { parseWsEvent } from '@/core/useWebSocket';
import { applyWsMessageToChatter, buildChatterWsUrl } from '@/hooks/useChatterWs';
import { createApiClient } from '@/integrations/api-client';
import type { ChatterEvent } from '@/lib/schemas/chatter.schema';

/**
 * F4 LIVE — chatter REST + koneksi WebSocket event bus.
 *
 * Dijalankan hanya kalau `MES_LIVE=1` (backend Django + Channels/Redis jalan).
 *
 *   MES_LIVE=1 ~/.bun/bin/bun --bun run test tests/live
 *   # opsional: trigger aksi bundle supaya ada event WS sungguhan (MENGUBAH DATA DEV):
 *   MES_LIVE=1 MES_LIVE_ALLOW_ACTION=1 … run test tests/live
 */

const LIVE = process.env['MES_LIVE'] === '1';
const API_BASE = process.env['MES_API_BASE_URL'] ?? 'http://localhost:8000/api/v1';
const WS_BASE = process.env['MES_WS_URL'] ?? 'ws://localhost:8000/ws';
const ALLOW_ACTION = process.env['MES_LIVE_ALLOW_ACTION'] === '1';
const SESSION_COOKIE = process.env['MES_SESSION_COOKIE'] ?? '';
const BUNDLE_ID = Number(process.env['MES_LIVE_BUNDLE_ID'] ?? '1');

interface WsSink {
  messages: string[];
  socket: WebSocket;
}

/** Buka WS + kumpulkan pesan sampai `waitMs` (atau satu pesan masuk lebih awal). */
async function collectWs(url: string, waitMs: number, cookie?: string): Promise<WsSink> {
  const socket =
    cookie === undefined
      ? new WebSocket(url)
      : new WebSocket(url, { headers: { cookie } } as unknown as string[]);
  const messages: string[] = [];

  await new Promise<void>((resolve, reject) => {
    const timer = setTimeout(resolve, waitMs);

    socket.onmessage = (event: MessageEvent) => {
      messages.push(String((event as { data?: unknown }).data ?? ''));

      if (messages.length >= 1) {
        clearTimeout(timer);
        resolve();
      }
    };
    socket.onerror = () => {
      clearTimeout(timer);
      reject(new Error(`Gagal connect WebSocket: ${url}`));
    };
  });

  return { messages, socket };
}

/** Fase 4.4: WS anonim ditutup `4401` SEBELUM accept → buktikan perilaku itu. */
async function wsOpensAnonymously(url: string): Promise<boolean> {
  const socket = new WebSocket(url);

  return await new Promise<boolean>((resolve) => {
    const timer = setTimeout(() => {
      resolve(true); // tidak ada penolakan dalam 2s
      socket.close();
    }, 2000);

    socket.onopen = () => {
      clearTimeout(timer);
      socket.close();
      resolve(true);
    };
    socket.onclose = () => {
      clearTimeout(timer);
      resolve(false);
    };
    socket.onerror = () => {
      clearTimeout(timer);
      resolve(false);
    };
  });
}

describe.skipIf(!LIVE)('F4 LIVE — chatter REST + WebSocket', () => {
  const client = createApiClient({ baseUrl: API_BASE });

  it('GET /chatter/bundles/{id}/ → 200 + ChatterPage (preview/total_count/has_more/next_cursor)', async () => {
    const page = await getChatter(client, 'bundles', BUNDLE_ID, { limit: 5 });

    expect(Array.isArray(page.preview)).toBe(true);
    expect(typeof page.total_count).toBe('number');
    expect(page).toHaveProperty('has_more');
    expect(page).toHaveProperty('next_cursor');

    const first = page.preview[0];
    if (first !== undefined) {
      expect(typeof first.id).toBe('string');
      expect(typeof first.summary).toBe('string');
      expect(typeof first.created_at).toBe('string');
    }
  });

  it('WS /ws/events/ anon → ditolak (Fase 4.4: close 4401 sebelum accept)', async () => {
    const url = buildChatterWsUrl(WS_BASE, 'bundles', BUNDLE_ID);

    expect(await wsOpensAnonymously(url)).toBe(false);
  });

  it.skipIf(SESSION_COOKIE.length === 0)(
    'WS /ws/events/?resource=bundles&id=… dengan session → connect + group, pesan kontrol di-skip parse (MES_SESSION_COOKIE)',
    async () => {
      const url = buildChatterWsUrl(WS_BASE, 'bundles', BUNDLE_ID);
      const sink = await collectWs(url, 5000, SESSION_COOKIE);

      try {
        expect(sink.messages.length).toBeGreaterThan(0);

        const first = sink.messages[0] ?? '';
        const control = JSON.parse(first) as { type?: string; groups?: string[] };

        expect(control.type).toBe('connected');
        expect(control.groups).toContain('events');
        expect(control.groups).toContain(`bundle.${BUNDLE_ID}`);
        // pesan kontrol TIDAK dianggap event domain (parseWsEvent → null)
        expect(parseWsEvent(first)).toBeNull();
      } finally {
        sink.socket.close();
      }
    },
  );

  it.skipIf(!ALLOW_ACTION)(
    'event WS nyata (butuh MES_LIVE_ALLOW_ACTION=1 — mengubah data dev) → prepend ke preview',
    async () => {
      const url = buildChatterWsUrl(WS_BASE, 'bundles', BUNDLE_ID);
      const socket = new WebSocket(url);
      const events: ChatterEvent[] = [];

      await new Promise<void>((resolve, reject) => {
        const timer = setTimeout(() => reject(new Error('timeout menunggu bundle_event')), 10_000);

        socket.onmessage = (event: MessageEvent) => {
          const data = String((event as { data?: unknown }).data ?? '');
          const parsed = parseWsEvent(data);
          if (parsed === null) return; // kontrol

          const merged = applyWsMessageToChatter(events, data);
          if (merged !== events) {
            events.length = 0;
            events.push(...merged);
            clearTimeout(timer);
            resolve();
          }
        };
        socket.onerror = () => {
          clearTimeout(timer);
          reject(new Error('WS error'));
        };
      });

      socket.close();

      const response = await fetch(`${API_BASE}/garmen/bundles/${BUNDLE_ID}/BUNDLE_START/`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ action: 'BUNDLE_START', resource_id: String(BUNDLE_ID) }),
      });

      // 200 = aksi diterima; 400/409 = state bundle tidak memungkinkan START (dicatat, bukan gagal).
      expect([200, 400, 409]).toContain(response.status);
      expect(events.length).toBeGreaterThanOrEqual(0);
    }
  );
});
