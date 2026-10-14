import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import {
  FeedbackRuntimeContext,
  OfflineRuntimeContext,
  type FeedbackRuntime,
  type OfflineRuntime,
} from '@/app/app-runtime';
import { ActionFeedback, type ActionFeedbackKind } from '@/components/molecules/ActionFeedback';
import { useApiClient } from '@/hooks/useApiClient';
import { useOfflineSync } from '@/integrations/use-offline-sync';

/**
 * AppRuntimeProvider - pemilik tunggal "runtime" aplikasi (Fase 17):
 *
 *  1. **offline sync** - SATU queue untuk seluruh aplikasi (`useOfflineSync` membuat queue
 *     per-instance, jadi tidak boleh dipanggil di dua tempat);
 *  2. **feedback** - state flash global yang dirender sekali sebagai `<ActionFeedback>`
 *     (beep + haptic + overlay kedip), dipicu `useFeedback().trigger()`.
 *
 * Dipasang sekali di `main.tsx`, di dalam `BrowserRouter`.
 */

/** Lama overlay flash sebelum di-reset (ms) - mengikuti animasi `ActionFeedback`. */
const FLASH_RESET_MS = 300;

interface AppRuntimeProviderProps {
  children: ReactNode;
}

export function AppRuntimeProvider({ children }: AppRuntimeProviderProps) {
  const apiClient = useApiClient();
  const offlineSync = useOfflineSync({ apiClient });

  const [flash, setFlash] = useState<ActionFeedbackKind | null>(null);
  const timerRef = useRef<number | null>(null);

  const clear = useCallback((): void => {
    setFlash(null);
  }, []);

  const trigger = useCallback((kind: ActionFeedbackKind): void => {
    setFlash(kind);

    if (timerRef.current !== null) window.clearTimeout(timerRef.current);
    timerRef.current = window.setTimeout(() => {
      timerRef.current = null;
      setFlash(null);
    }, FLASH_RESET_MS);
  }, []);

  useEffect(() => {
    return () => {
      if (timerRef.current !== null) window.clearTimeout(timerRef.current);
    };
  }, []);

  const feedback = useMemo<FeedbackRuntime>(
    () => ({ flash, trigger, clear }),
    [flash, trigger, clear],
  );

  const offline = useMemo<OfflineRuntime>(
    () => ({
      queue: offlineSync.queue,
      isOnline: offlineSync.isOnline,
      pendingCount: offlineSync.pendingCount,
    }),
    [offlineSync.queue, offlineSync.isOnline, offlineSync.pendingCount],
  );

  return (
    <FeedbackRuntimeContext.Provider value={feedback}>
      <OfflineRuntimeContext.Provider value={offline}>
        {children}
        {/* `kind` wajib diisi; saat tidak aktif overlay tidak dirender (AnimatePresence). */}
        <ActionFeedback kind={flash ?? 'success'} active={flash !== null} />
      </OfflineRuntimeContext.Provider>
    </FeedbackRuntimeContext.Provider>
  );
}
