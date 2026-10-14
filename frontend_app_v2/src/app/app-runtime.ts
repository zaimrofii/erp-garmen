import { createContext, useContext } from 'react';
import type { ActionFeedbackKind } from '@/components/molecules/ActionFeedback';
import type { OfflineQueue } from '@/integrations/offline-queue';

/**
 * app-runtime.ts - context runtime aplikasi (feedback global + offline sync).
 *
 * Kenapa satu file .ts (bukan `.tsx`)? Supaya tidak ada KOMPONEN di sini - file yang
 * mengekspor komponen + fungsi non-komponen melanggar `react/only-export-components`
 * (fast-refresh). Provider-nya ada di `app/AppRuntimeProvider.tsx`.
 *
 * Kenapa offline sync lewat context? `useOfflineSync()` membuat queue **per-instance hook**
 * (`useRef` internal). Kalau AppShell dan ShopFloorPage memanggilnya masing-masing, akan ada
 * DUA queue/flush loop pada IndexedDB yang sama. Jadi satu provider memiliki satu queue,
 * dan halaman memakai queue yang sama lewat `useOffline()`.
 */

export interface FeedbackRuntime {
  /** Jenis flash yang sedang aktif (null = tidak ada). */
  flash: ActionFeedbackKind | null;
  /** Picu flash + beep + haptic hasil aksi (dieksekusi `ActionFeedback`). */
  trigger: (kind: ActionFeedbackKind) => void;
  clear: () => void;
}

export interface OfflineRuntime {
  /** Queue offline TUNGGAL aplikasi (dipakai `submitAction`). */
  queue: OfflineQueue;
  isOnline: boolean;
  pendingCount: number;
}

export const FeedbackRuntimeContext = createContext<FeedbackRuntime | null>(null);
export const OfflineRuntimeContext = createContext<OfflineRuntime | null>(null);

const MISSING_PROVIDER =
  'Provider runtime belum dipasang. Bungkus aplikasi dengan <AppRuntimeProvider> di main.tsx.';

export function useFeedback(): FeedbackRuntime {
  const value = useContext(FeedbackRuntimeContext);
  if (value === null) throw new Error(`useFeedback: ${MISSING_PROVIDER}`);

  return value;
}

export function useOffline(): OfflineRuntime {
  const value = useContext(OfflineRuntimeContext);
  if (value === null) throw new Error(`useOffline: ${MISSING_PROVIDER}`);

  return value;
}
