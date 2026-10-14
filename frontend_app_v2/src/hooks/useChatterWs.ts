import { useCallback, useState } from 'react';
import { readWsEnabled } from '@/app/config';
import { parseWsEvent, readEnvWsEventsUrl, resolveWsEventsUrl, useWebSocket, type WsEvent } from '@/core/useWebSocket';
import { readWsChatterEvent } from '@/integrations/ws-chatter';
import { mergeChatterPreview } from '@/lib/chatter-merge';
import type { ChatterEvent } from '@/lib/schemas/chatter.schema';

/**
 * useChatterWs.ts — langganan chatter real-time (F4).
 *
 * Alur: `WS /ws/events/` → engine `core/useWebSocket.ts` (reconnect backoff
 * `computeReconnectDelay`, parse `parseWsEvent`) → `readWsChatterEvent`
 * (`ChatterEventSchema`) → `mergeChatterPreview` (prepend + dedup + potong 5).
 *
 * Kontrak backend (`django_app/core/event_bus/consumers.py` + `websocket.py`):
 * - langganan lewat **query param** saat connect: `ws://…/ws/events/?resource=bundles&id=16`
 *   → klien join group default `events` **dan** group spesifik (`bundle.16` /
 *   `work_order.<id>`; pemetaan resource→prefix ada di backend `RESOURCE_GROUP_PREFIXES`);
 * - envelope event: `{type:'bundle_event', resource, id, event_name, occurred_at, event}`
 *   dengan `event` = chatter §8 (`{id, actor, type, summary, payload, created_at}`);
 * - pesan kontrol (`connected`/`subscribed`/`pong`/`error`) tidak punya `resource` →
 *   `parseWsEvent` mengembalikan `null` (di-skip, bukan crash).
 *
 * Logika murni diekspor terpisah (hook hanya shell tipis) supaya bisa diuji tanpa DOM:
 * `isChatterWsEnabled`, `buildChatterWsUrl`, `mergeChatterWsEvent`, `applyWsMessageToChatter`.
 */

export interface ChatterWsTarget {
  /** Nama resource REST backend (`bundles` | `work-orders`). */
  resource: string;
  /** Id instance; `undefined` (mis. detail belum dimuat) → tidak langganan. */
  id: number | string | undefined;
}

export interface ChatterWsResult {
  /** Event real-time (maks 5, terbaru dulu) — gabungkan dengan hasil fetch lewat `mergeChatterPreview`. */
  events: ChatterEvent[];
  isConnected: boolean;
  /** false = tidak men-subscribe (WS_ENABLED=false / target belum valid) — bukan error. */
  enabled: boolean;
  error: string | null;
}

/**
 * PURE — boleh langganan? (4.4) `VITE_WS_ENABLED !== 'true'` → **false** (tanpa error,
 * chatter tetap dirender dari hasil fetch awal).
 */
export function isChatterWsEnabled(input: {
  wsEnabled: boolean;
  resource: string;
  id: number | string | undefined;
}): boolean {
  if (!input.wsEnabled) return false;
  if (input.resource.trim().length === 0) return false;

  const id = input.id;
  if (id === undefined || id === null) return false;

  return String(id).trim().length > 0;
}

/**
 * PURE — URL langganan chatter: `ws://…/ws/events/?resource=bundles&id=16`.
 * `''` kalau base URL kosong atau target tidak valid (pemanggil tidak boleh connect).
 */
export function buildChatterWsUrl(
  baseUrl: string,
  resource: string,
  id: number | string | undefined,
): string {
  const base = resolveWsEventsUrl(baseUrl);
  if (base.length === 0) return '';
  if (!isChatterWsEnabled({ wsEnabled: true, resource, id })) return '';

  const params = new URLSearchParams({ resource: resource.trim(), id: String(id) });

  return `${base}?${params.toString()}`;
}

/**
 * PURE — satu event WS (sudah diparse engine) ke daftar chatter.
 * Event non-chatter / kontrol → array `previous` APA ADANYA (React bail-out, tidak re-render).
 */
export function mergeChatterWsEvent(previous: ChatterEvent[], wsEvent: WsEvent): ChatterEvent[] {
  const chatter = readWsChatterEvent(wsEvent);
  if (chatter === null) return previous;

  return mergeChatterPreview(previous, chatter);
}

/** PURE — pesan WS MENTAH (string JSON / objek) → daftar chatter baru; pesan rusak/kontrol di-skip. */
export function applyWsMessageToChatter(previous: ChatterEvent[], data: unknown): ChatterEvent[] {
  const wsEvent = parseWsEvent(data);
  if (wsEvent === null) return previous;

  return mergeChatterWsEvent(previous, wsEvent);
}

interface ChatterWsState {
  /** Kunci target supaya event bundle A tidak bocor ke bundle B (halaman ganti id). */
  key: string;
  events: ChatterEvent[];
}

export function useChatterWs(target: ChatterWsTarget): ChatterWsResult {
  const { resource, id } = target;

  const wantSubscription = isChatterWsEnabled({ wsEnabled: readWsEnabled(), resource, id });
  const url = wantSubscription ? buildChatterWsUrl(readEnvWsEventsUrl(), resource, id) : '';
  const enabled = wantSubscription && url.length > 0;
  const key = enabled ? `${resource}:${String(id)}` : '';

  const [state, setState] = useState<ChatterWsState>({ key: '', events: [] });

  const handleEvent = useCallback(
    (wsEvent: WsEvent): void => {
      setState((previous) => {
        const current = previous.key === key ? previous.events : [];
        const merged = mergeChatterWsEvent(current, wsEvent);

        // Tidak ada perubahan → kembalikan state lama (React tidak re-render).
        if (merged === current && previous.key === key) return previous;

        return { key, events: merged };
      });
    },
    [key],
  );

  const ws = useWebSocket({ url, enabled, onEvent: handleEvent });

  return {
    // Target berganti → event lama tidak dipakai (dibaca saat render, TANPA effect).
    events: state.key === key ? state.events : [],
    isConnected: ws.isConnected,
    enabled,
    error: ws.error?.message ?? null,
  };
}
