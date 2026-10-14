import { useCallback, useMemo, useState } from 'react';
import { generateUUID } from '@/lib/uuid';
import type { DefectEntry } from '@/types/qc';

/**
 * useQCDefects - state form defect QC (multi-entry + multi-qty).
 *
 * Draft memakai `id` frontend (`generateUUID()`) supaya daftar bisa dirender dengan
 * `key={id}` (larangan `key={index}`). `id` DIBUANG saat kirim (`toPayload()`), karena
 * kontrak backend hanya mengenal `type`/`qty`/`location`/`photo`.
 *
 * Semua update immutable (spread), handler dibungkus `useCallback`.
 */

/** Draft defect di form: `DefectEntry` + `id` frontend. */
export interface QCDefectDraft extends DefectEntry {
  id: string;
}

/** Input tambah entry; `qty` opsional (default 1). */
export interface QCDefectInput {
  type: DefectEntry['type'];
  location: DefectEntry['location'];
  qty?: number;
  photo?: string;
}

export interface UseQCDefectsResult {
  entries: QCDefectDraft[];
  addEntry: (input: QCDefectInput) => void;
  removeEntry: (id: string) => void;
  updateEntry: (id: string, patch: Partial<Omit<QCDefectDraft, 'id'>>) => void;
  setQty: (id: string, qty: number) => void;
  /** Ganti qty entry TERAKHIR dengan lokasi+jenis yang sama (kalau ada) atau tambah baru. */
  upsertEntry: (input: QCDefectInput) => void;
  clear: () => void;
  totalQty: number;
  isEmpty: boolean;
  /** Payload bersih untuk backend (`id` frontend dibuang). */
  toPayload: () => DefectEntry[];
}

export function useQCDefects(initial: QCDefectDraft[] = []): UseQCDefectsResult {
  const [entries, setEntries] = useState<QCDefectDraft[]>(initial);

  const addEntry = useCallback((input: QCDefectInput): void => {
    const next: QCDefectDraft = {
      id: generateUUID(),
      type: input.type,
      location: input.location,
      qty: input.qty ?? 1,
      ...(input.photo === undefined ? {} : { photo: input.photo }),
    };

    setEntries((current) => [...current, next]);
  }, []);

  const removeEntry = useCallback((id: string): void => {
    setEntries((current) => current.filter((entry) => entry.id !== id));
  }, []);

  const updateEntry = useCallback(
    (id: string, patch: Partial<Omit<QCDefectDraft, 'id'>>): void => {
      setEntries((current) =>
        current.map((entry) => (entry.id === id ? { ...entry, ...patch, id: entry.id } : entry)),
      );
    },
    [],
  );

  const setQty = useCallback((id: string, qty: number): void => {
    const safeQty = Number.isFinite(qty) ? Math.max(0, Math.trunc(qty)) : 0;

    setEntries((current) =>
      current.map((entry) => (entry.id === id ? { ...entry, qty: safeQty } : entry)),
    );
  }, []);

  const upsertEntry = useCallback((input: QCDefectInput): void => {
    setEntries((current) => {
      const index = current.findIndex(
        (entry) => entry.type === input.type && entry.location === input.location,
      );

      if (index < 0) {
        return [
          ...current,
          {
            id: generateUUID(),
            type: input.type,
            location: input.location,
            qty: input.qty ?? 1,
            ...(input.photo === undefined ? {} : { photo: input.photo }),
          },
        ];
      }

      return current.map((entry, position) =>
        position === index ? { ...entry, qty: entry.qty + (input.qty ?? 1) } : entry,
      );
    });
  }, []);

  const clear = useCallback((): void => {
    setEntries([]);
  }, []);

  const totalQty = useMemo(
    () => entries.reduce((total, entry) => total + entry.qty, 0),
    [entries],
  );

  const toPayload = useCallback(
    (): DefectEntry[] =>
      entries.map((entry) => {
        const payload: DefectEntry = {
          type: entry.type,
          qty: entry.qty,
          location: entry.location,
        };

        return entry.photo === undefined ? payload : { ...payload, photo: entry.photo };
      }),
    [entries],
  );

  return {
    entries,
    addEntry,
    removeEntry,
    updateEntry,
    setQty,
    upsertEntry,
    clear,
    totalQty,
    isEmpty: entries.length === 0,
    toPayload,
  };
}
