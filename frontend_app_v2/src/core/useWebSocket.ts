import { useCallback, useEffect, useRef, useState } from 'react';
import { readEnvString } from '@/app/runtime-env';

/**
 * useWebSocket.ts — event bus real-time (§4 backend-contract: `WS /ws/events/`).
 *
 * **Anti-polling** (§12.1): hanya WebSocket + reconnect backoff — TIDAK ADA `setInterval`.
 * Setiap event valid → `onInvalidate(resource)` (Fase 5: `queryClient.invalidateQueries`).
 *
 * Seam test: `WebSocketImpl` bisa di-inject (mock) sehingga seluruh state machine koneksi
 * (connect → message → close → reconnect backoff) teruji **tanpa DOM**.
 */

export interface WsEvent {
  resource: string;
  event_type: string;
  payload: Record<string, unknown>;
  /** Id instance (Fase E: envelope `bundle_event` mengirim `id`). */
  id?: string;
  /** Event chatter (§8) apa adanya — dipakai prepend preview chatter. */
  event?: Record<string, unknown>;
}

export interface WsError {
  kind: string;
  message: string;
}

export interface WsState {
  isConnected: boolean;
  reconnectAttempts: number;
  error?: WsError;
}

export interface UseWebSocketOptions {
  /** Default dari `import.meta.env.VITE_WS_URL`. */
  url?: string;
  onEvent?: (event: WsEvent) => void;
  onInvalidate?: (resource: string) => void;
  /** default true */
  reconnect?: boolean;
  /** default 1000 ms */
  reconnectDelayMs?: number;
  /** default 30000 ms */
  maxReconnectDelayMs?: number;
  /** default true */
  enabled?: boolean;
  /** Seam test. */
  WebSocketImpl?: typeof WebSocket;
}

export interface UseWebSocketResult {
  isConnected: boolean;
  lastEvent?: WsEvent;
  error?: WsError;
  reconnectAttempts: number;
  disconnect: () => void;
  reconnect: () => void;
}

export interface WsConnectionOptions {
  url: string;
  WebSocketImpl?: typeof WebSocket;
  onEvent?: (event: WsEvent) => void;
  onInvalidate?: (resource: string) => void;
  onStateChange?: (state: WsState) => void;
  reconnect?: boolean;
  reconnectDelayMs?: number;
  maxReconnectDelayMs?: number;
}

export interface WsConnection {
  start: () => void;
  disconnect: () => void;
  getState: () => WsState;
}

export const DEFAULT_RECONNECT_DELAY_MS = 1000;
export const DEFAULT_MAX_RECONNECT_DELAY_MS = 30000;

/** Path endpoint event bus backend (Fase E): `WS /ws/events/` (§4 backend-contract). */
export const WS_EVENTS_PATH = '/events/';

/**
 * PURE — URL WebSocket event bus dari `VITE_WS_URL`.
 *
 * `VITE_WS_URL` menyebut **host/path dasar** (mis. `ws://localhost:8000/ws`),
 * sedangkan consumer backend ada di `ws/events/` — jadi path `/events/` dipasang
 * di sini supaya base URL tetap satu tempat konfigurasi (dan tidak ada klien yang
 * menebak path). URL kosong → `''` (hook dianggap tidak punya tujuan, sama
 * seperti sebelumnya).
 */
export function resolveWsEventsUrl(baseUrl: string): string {
  const trimmed = baseUrl.trim();
  if (trimmed === '') return '';

  const withoutTrailingSlash = trimmed.replace(/\/+$/, '');
  if (withoutTrailingSlash.endsWith('/events')) return `${withoutTrailingSlash}/`;

  return `${withoutTrailingSlash}${WS_EVENTS_PATH}`;
}

/** Nama `type` envelope consumer yang membawa event domain (bukan kontrol). */
export const ENVELOPE_EVENT_TYPES: readonly string[] = ['bundle_event', 'work_order_event'];

/**
 * PURE — parse payload event bus.
 *
 * Dua bentuk diterima:
 *   * **Fase E (envelope consumer)** — `{type:'bundle_event', resource, id,
 *     event_name, event:{…}}`: `event_name` → `event_type`, `event` → `payload`
 *     (bentuk chatter §8). Pesan kontrol (`connected`/`subscribed`/`pong`/`error`)
 *     tidak punya `resource` → `null` (di-skip).
 *   * **Fase 3 (lama)** — `{resource, event_type, payload}`.
 *
 * Menerima object maupun JSON string; apa pun yang tidak sesuai → `null`
 * (event di-skip, jangan sampai bikin crash).
 */
export function parseWsEvent(raw: unknown): WsEvent | null {
  let candidate = raw;

  if (typeof raw === 'string') {
    try {
      candidate = JSON.parse(raw) as unknown;
    } catch {
      return null;
    }
  }

  if (typeof candidate !== 'object' || candidate === null || Array.isArray(candidate)) return null;

  const record = candidate as Record<string, unknown>;
  const resource = record['resource'];
  if (typeof resource !== 'string' || resource.trim().length === 0) return null;

  const envelopeKind = typeof record['type'] === 'string' ? record['type'].trim() : '';
  if (ENVELOPE_EVENT_TYPES.includes(envelopeKind)) {
    const domainEvent = record['event'];
    if (typeof domainEvent !== 'object' || domainEvent === null || Array.isArray(domainEvent)) {
      return null;
    }

    const rawName = record['event_name'];
    const eventName =
      typeof rawName === 'string' && rawName.trim().length > 0 ? rawName.trim() : envelopeKind;
    const rawId = record['id'];

    return {
      resource,
      event_type: eventName,
      payload: domainEvent as Record<string, unknown>,
      ...(typeof rawId === 'string' || typeof rawId === 'number' ? { id: String(rawId) } : {}),
      event: domainEvent as Record<string, unknown>,
    };
  }

  const eventType = record['event_type'];
  const payload = record['payload'];

  if (typeof eventType !== 'string' || eventType.trim().length === 0) return null;
  if (typeof payload !== 'object' || payload === null || Array.isArray(payload)) return null;

  return { resource, event_type: eventType, payload: payload as Record<string, unknown> };
}

/** PURE — `min(baseMs * 2^attempts, maxMs)` (§4.3), exponential backoff. */
export function computeReconnectDelay(
  attempts: number,
  baseMs: number = DEFAULT_RECONNECT_DELAY_MS,
  maxMs: number = DEFAULT_MAX_RECONNECT_DELAY_MS
): number {
  const normalized = Number.isFinite(attempts) && attempts > 0 ? Math.floor(attempts) : 0;
  return Math.min(baseMs * 2 ** normalized, maxMs);
}

export function createWsConnection(options: WsConnectionOptions): WsConnection {
  const impl = options.WebSocketImpl ?? (globalThis as { WebSocket?: typeof WebSocket }).WebSocket;
  const reconnectEnabled = options.reconnect ?? true;
  const baseDelayMs = options.reconnectDelayMs ?? DEFAULT_RECONNECT_DELAY_MS;
  const maxDelayMs = options.maxReconnectDelayMs ?? DEFAULT_MAX_RECONNECT_DELAY_MS;

  let socket: WebSocket | null = null;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let attempts = 0;
  let stopped = false;
  let state: WsState = { isConnected: false, reconnectAttempts: 0 };

  function emit(): void {
    options.onStateChange?.(state);
  }

  function handleMessage(raw: unknown): void {
    const event = parseWsEvent(raw);
    if (event === null) return; // event invalid → skip (jangan crash)

    options.onEvent?.(event);
    options.onInvalidate?.(event.resource);
  }

  function scheduleReconnect(): void {
    if (!reconnectEnabled || stopped) return;

    const delay = computeReconnectDelay(attempts, baseDelayMs, maxDelayMs);
    attempts += 1;
    state = { isConnected: false, reconnectAttempts: attempts };
    emit();

    timer = setTimeout(() => {
      timer = null;
      open();
    }, delay);
  }

  function open(): void {
    if (impl === undefined) {
      state = {
        isConnected: false,
        reconnectAttempts: attempts,
        error: {
          kind: 'websocket_unavailable',
          message: 'WebSocket tidak tersedia di lingkungan ini.',
        },
      };
      emit();
      return;
    }

    const ws = new impl(options.url);
    socket = ws;

    ws.onopen = () => {
      attempts = 0;
      state = { isConnected: true, reconnectAttempts: 0 };
      emit();
    };

    ws.onmessage = (messageEvent: MessageEvent) => {
      handleMessage((messageEvent as { data?: unknown }).data);
    };

    ws.onerror = () => {
      state = {
        isConnected: false,
        reconnectAttempts: attempts,
        error: { kind: 'websocket_error', message: 'Terjadi error pada koneksi WebSocket.' },
      };
      emit();
    };

    ws.onclose = () => {
      socket = null;
      scheduleReconnect();
    };
  }

  return {
    start(): void {
      stopped = false;
      open();
    },
    disconnect(): void {
      stopped = true;

      if (timer !== null) {
        clearTimeout(timer);
        timer = null;
      }

      if (socket !== null) {
        const current = socket;
        socket = null;
        // Close yang disengaja TIDAK boleh memicu reconnect.
        current.onclose = null;
        current.close();
      }

      state = { isConnected: false, reconnectAttempts: 0 };
      emit();
    },
    getState(): WsState {
      return state;
    },
  };
}

/**
 * Default URL event bus untuk hook: `VITE_WS_URL` (host polos, mis.
 * `ws://localhost:8000/ws`) + path `/events/` (endpoint consumer backend).
 *
 * **Publik** supaya bisa diuji dan dipakai ulang `app/config.readWsUrl()` —
 * jadi hanya ada SATU tempat menambahkan `/events/`. `resolveWsEventsUrl`
 * idempoten, jadi memanggilnya berulang aman.
 */
export function readEnvWsEventsUrl(): string {
  return resolveWsEventsUrl(readEnvString('VITE_WS_URL') ?? '');
}

export function useWebSocket(options: UseWebSocketOptions = {}): UseWebSocketResult {
  const [state, setState] = useState<WsState>({ isConnected: false, reconnectAttempts: 0 });
  const [lastEvent, setLastEvent] = useState<WsEvent | undefined>(undefined);

  const connectionRef = useRef<WsConnection | null>(null);
  const latestOptions = useRef(options);

  // Callback selalu dibaca dari render terakhir (koneksi dibuat sekali).
  useEffect(() => {
    latestOptions.current = options;
  });

  const enabled = options.enabled ?? true;
  // `options.url` (kalau diisi pemanggil) dipakai APA ADANYA — pastikan sudah
  // lewat `resolveWsEventsUrl` (lihat `app/config.readWsUrl()` + `App.tsx`).
  const url = options.url ?? readEnvWsEventsUrl();
  const {
    WebSocketImpl,
    reconnect: reconnectEnabled,
    reconnectDelayMs,
    maxReconnectDelayMs,
  } = options;

  useEffect(() => {
    if (!enabled) return undefined;

    const connection = createWsConnection({
      url,
      WebSocketImpl,
      reconnect: reconnectEnabled,
      reconnectDelayMs,
      maxReconnectDelayMs,
      onEvent: (event) => {
        latestOptions.current.onEvent?.(event);
        setLastEvent(event);
      },
      onInvalidate: (resource) => {
        latestOptions.current.onInvalidate?.(resource);
      },
      onStateChange: (next) => {
        setState(next);
      },
    });

    connectionRef.current = connection;
    connection.start();

    return () => {
      connection.disconnect();
      connectionRef.current = null;
    };
  }, [enabled, url, WebSocketImpl, reconnectEnabled, reconnectDelayMs, maxReconnectDelayMs]);

  const disconnect = useCallback((): void => {
    connectionRef.current?.disconnect();
  }, []);

  const reconnectNow = useCallback((): void => {
    const connection = connectionRef.current;
    if (connection === null) return;

    connection.disconnect();
    connection.start();
  }, []);

  return {
    isConnected: state.isConnected,
    reconnectAttempts: state.reconnectAttempts,
    disconnect,
    reconnect: reconnectNow,
    ...(lastEvent === undefined ? {} : { lastEvent }),
    ...(state.error === undefined ? {} : { error: state.error }),
  };
}
