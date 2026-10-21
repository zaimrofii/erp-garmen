/**
 * view-mode.ts - preferensi mode tampilan halaman list: `list` | `grid` | `kanban` (FASE K3).
 *
 * Kenapa logic-nya di `lib/` (bukan di dalam komponen): `ViewToggle` (tampilan) dan
 * halaman (pembaca nilai tersimpan) harus memakai aturan YANG SAMA, supaya nilai
 * localStorage yang asing/tak didukung tidak pernah lolos ke state React.
 *
 * Aman di runtime tanpa DOM (SSR/vitest `environment: 'node'`): `globalThis.localStorage`
 * bisa tidak ada -> baca = `fallback`, tulis = diabaikan (pola `app/useMode.ts`).
 */

export type ViewMode = 'list' | 'grid' | 'kanban';

/** Urutan kanonik mode (dipakai validasi + urutan tombol kalau pemanggil tidak menentukan). */
export const VIEW_MODES: readonly ViewMode[] = ['list', 'grid', 'kanban'];

/** Label tombol (Indonesia singkat, konsisten `ViewToggle`). */
export const VIEW_MODE_LABELS: Record<ViewMode, string> = {
  list: 'List',
  grid: 'Grid',
  kanban: 'Kanban',
};

/** Key localStorage per halaman (satu key per resource supaya preferensi tidak tercampur). */
export const VIEW_STORAGE_KEYS = {
  bundles: 'mes-view-bundles',
  workOrders: 'mes-view-work-orders',
  products: 'mes-view-products',
  partners: 'mes-view-partners',
} as const;

interface StorageLike {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

function storage(): StorageLike | null {
  const candidate = (globalThis as { localStorage?: StorageLike }).localStorage;
  return candidate === undefined ? null : candidate;
}

/** PURE - true kalau `value` salah satu mode yang didukung (tanpa cast `as`). */
export function isViewMode(value: string): value is ViewMode {
  return VIEW_MODES.some((mode) => mode === value);
}

/**
 * Baca mode tersimpan untuk `storageKey`; hanya diterima kalau ada di `modes`.
 * Nilai kosong/asing/storage tak tersedia -> `fallback` (default: mode pertama).
 */
export function readViewMode(
  storageKey: string,
  modes: readonly ViewMode[],
  fallback?: ViewMode,
): ViewMode {
  const initial = fallback ?? modes[0] ?? 'list';
  const store = storage();
  if (store === null) return initial;

  const raw = store.getItem(storageKey);
  if (raw === null) return initial;

  return modes.find((mode) => mode === raw) ?? initial;
}

/** Simpan preferensi mode (storage diblokir/gagal -> diabaikan, bukan error fatal). */
export function persistViewMode(storageKey: string, mode: ViewMode): void {
  const store = storage();
  if (store === null) return;

  try {
    store.setItem(storageKey, mode);
  } catch {
    // Kuota penuh / storage diblokir: preferensi tampilan bukan data kritis.
  }
}
