import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { readEnvString } from '@/app/runtime-env';
import { createApiClient, type ApiClient } from './api-client';
import {
  createOfflineQueue,
  type FlushOutcome,
  type FlushResult,
  type OfflineAction,
  type OfflineQueue,
} from './offline-queue';

/**
 * use-offline-sync.ts — jembatan offline queue ↔ React (Fase 3 §3.3).
 *
 * Aturan:
 * - **Tanpa polling**: hanya listener `online`/`offline` + `flush()` manual.
 * - Queue dibuat **internal via `useRef`** (bukan disuntik), DB dibuka lazy → aman dirender tanpa DOM.
 * - Hook ini TIDAK merender apa pun.
 */

export interface EventTargetLike {
  addEventListener(type: 'online' | 'offline', listener: () => void): void;
  removeEventListener(type: 'online' | 'offline', listener: () => void): void;
}

/**
 * PURE — dipasang/dilepas oleh hook, dan diuji langsung dengan `EventTargetLike` palsu
 * (tanpa DOM/jsdom, sesuai catatan Fase 2).
 */
export function attachNetworkListeners(
  target: EventTargetLike,
  handlers: { onOnline: () => void; onOffline: () => void }
): () => void {
  const onOnline = (): void => handlers.onOnline();
  const onOffline = (): void => handlers.onOffline();

  target.addEventListener('online', onOnline);
  target.addEventListener('offline', onOffline);

  return () => {
    target.removeEventListener('online', onOnline);
    target.removeEventListener('offline', onOffline);
  };
}

export interface UseOfflineSyncOptions {
  /** Default: dibuat dari `VITE_API_BASE_URL`. */
  apiClient?: ApiClient;
  dbName?: string;
  /** Default true — flush otomatis saat event `online`. */
  autoFlushOnOnline?: boolean;
  /** Fase 4: `queryClient.invalidateQueries({ queryKey: [resource] })`. */
  onInvalidate?: (resource: string) => void;
  onMismatch?: (action: OfflineAction, outcome: FlushOutcome) => void;
  onConflict?: (action: OfflineAction, outcome: FlushOutcome) => void;
  /** Seam test. Default `window`. */
  eventTarget?: EventTargetLike;
  /** Seam test. Default `navigator.onLine`. */
  isOnlineProvider?: () => boolean;
}

export interface UseOfflineSyncResult {
  enqueue: OfflineQueue['enqueue'];
  flush: () => Promise<FlushResult>;
  isOnline: boolean;
  pendingCount: number;
  /**
   * Queue itu sendiri (Fase D): dibutuhkan `FormView`/`ActionBar` supaya submit aksi memakai
   * jalur queue penuh (Idempotency-Key, `expected_result`, conflict policy).
   * Aman dibaca saat render — DB IndexedDB dibuka **lazy**, jadi pembuatan objek ini tanpa
   * side effect (test "render aman walau `indexedDB` tidak tersedia" menjaga sifat ini).
   */
  queue: OfflineQueue;
}

function readIsOnline(provider?: () => boolean): boolean {
  if (provider !== undefined) return provider();

  const navigatorLike = globalThis as { navigator?: { onLine?: boolean } };
  return navigatorLike.navigator?.onLine !== false;
}

function resolveEventTarget(override?: EventTargetLike): EventTargetLike | null {
  if (override !== undefined) return override;

  const windowLike = globalThis as { window?: EventTargetLike };
  return windowLike.window ?? null;
}

function createDefaultApiClient(): ApiClient {
  return createApiClient({ baseUrl: readEnvString('VITE_API_BASE_URL') ?? '' });
}

export function useOfflineSync(options: UseOfflineSyncOptions = {}): UseOfflineSyncResult {
  // Callback selalu dibaca dari render terakhir (queue dibuat sekali, callback bisa berganti).
  const latestOptions = useRef(options);

  // Queue dibuat SEKALI secara lazy via useRef; ref-nya hanya dibaca dari callback/effect
  // (bukan saat render) supaya React Compiler tidak kehilangan optimasi.
  const queueRef = useRef<OfflineQueue | null>(null);

  const getQueue = useCallback((): OfflineQueue => {
    let queue = queueRef.current;

    if (queue === null) {
      queue = createOfflineQueue({
        apiClient: options.apiClient ?? createDefaultApiClient(),
        dbName: options.dbName,
        onMismatch: (action, outcome) => latestOptions.current.onMismatch?.(action, outcome),
        onConflict: (action, outcome) => latestOptions.current.onConflict?.(action, outcome),
      });
      queueRef.current = queue;
    }

    return queue;
  }, [options.apiClient, options.dbName]);

  /**
   * Objek queue **stabil** untuk view (Fase D: `FormView`/`ActionBar`).
   *
   * Boleh dibaca saat render karena tidak menyentuh ref: method-nya mendelegasi ke queue asli
   * saat DIPANGGIL (queue dibuat lazy → render aman walau `indexedDB` tidak tersedia).
   */
  const queue: OfflineQueue = useMemo(
    () => ({
      enqueue: (input) => getQueue().enqueue(input),
      size: () => getQueue().size(),
      list: () => getQueue().list(),
      get: (id) => getQueue().get(id),
      remove: (id) => getQueue().remove(id),
      clear: () => getQueue().clear(),
      flush: () => getQueue().flush(),
    }),
    [getQueue]
  );

  const [isOnline, setIsOnline] = useState<boolean>(() => readIsOnline(options.isOnlineProvider));
  const [pendingCount, setPendingCount] = useState(0);

  const refreshPendingCount = useCallback(async (): Promise<void> => {
    setPendingCount(await queue.size());
  }, [queue]);

  const flush = useCallback(async (): Promise<FlushResult> => {
    const result = await queue.flush();

    setIsOnline(!result.offline);
    setPendingCount(result.pendingAfter);

    // "Lupakan invalidate setelah flush" = larangan §12.3 → selalu invalidate resource yang touched.
    const invalidate = latestOptions.current.onInvalidate;
    if (invalidate !== undefined) {
      for (const resource of result.touchedResources) invalidate(resource);
    }

    return result;
  }, [queue]);

  const enqueue = useCallback(
    async (input: Parameters<OfflineQueue['enqueue']>[0]): Promise<string> => {
      const id = await queue.enqueue(input);
      await refreshPendingCount();
      return id;
    },
    [queue, refreshPendingCount]
  );

  // Listener dipasang sekali; handler membaca `flush` terbaru dari ref (tanpa pasang-ulang tiap render).
  const flushRef = useRef(flush);

  useEffect(() => {
    latestOptions.current = options;
    flushRef.current = flush;
  });

  useEffect(() => {
    const target = resolveEventTarget(options.eventTarget);
    if (target === null) return undefined;

    return attachNetworkListeners(target, {
      onOnline: () => {
        setIsOnline(true);
        if (latestOptions.current.autoFlushOnOnline ?? true) void flushRef.current();
      },
      onOffline: () => {
        setIsOnline(false);
      },
    });
  }, [options.eventTarget]);

  // Sinkronisasi dengan sistem eksternal (IndexedDB) → setState di effect memang disengaja di sini.
  useEffect(() => {
    void refreshPendingCount();
  }, [refreshPendingCount]);

  return { enqueue, flush, isOnline, pendingCount, queue };
}
