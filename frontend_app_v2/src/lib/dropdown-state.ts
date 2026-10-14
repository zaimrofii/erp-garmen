/**
 * dropdown-state.ts - logika MURNI atom `Dropdown` (F5).
 *
 * Dipisah dari komponen supaya bisa diuji tanpa DOM (jsdom tidak jalan di bun) dan
 * supaya `components/atoms/Dropdown.tsx` hanya mengekspor komponen (Fast Refresh).
 *
 * Semua fungsi tidak pernah throw: index di luar batas / daftar kosong → nilai aman
 * (`-1` / `null`), sehingga atom tidak perlu penjagaan tambahan.
 */

export interface DropdownEntryLike {
  disabled?: boolean;
}

/** PURE - index item pertama yang bisa dipilih; `-1` kalau semuanya disabled/kosong. */
export function firstEnabledIndex(entries: readonly DropdownEntryLike[]): number {
  return entries.findIndex((entry) => entry.disabled !== true);
}

/**
 * PURE - index fokus berikutnya (`direction` 1 = ArrowDown, -1 = ArrowUp).
 * Item `disabled` DILEWATI dan pencarian mengelilingi (wrap). `-1` kalau tidak ada
 * item yang bisa dipilih.
 */
export function stepFocusIndex(
  entries: readonly DropdownEntryLike[],
  current: number,
  direction: 1 | -1,
): number {
  const count = entries.length;
  if (count === 0) return -1;

  let index = current;

  for (let step = 0; step < count; step += 1) {
    index = (index + direction + count) % count;
    if (entries[index]?.disabled !== true) return index;
  }

  return -1;
}

/** PURE - tombol yang menutup menu. */
export function isCloseKey(key: string): boolean {
  return key === 'Escape';
}

/** PURE - arah fokus dari tombol; `0` = bukan tombol navigasi. */
export function stepForKey(key: string): 1 | -1 | 0 {
  if (key === 'ArrowDown') return 1;
  if (key === 'ArrowUp') return -1;

  return 0;
}

/**
 * PURE - id item yang dipilih pada `index` (Enter/Space atau klik).
 * `null` kalau index di luar batas atau item-nya `disabled` (item placeholder TIDAK
 * boleh memicu navigasi).
 */
export function resolveSelection(
  entries: readonly { id: string; disabled?: boolean }[],
  index: number,
): string | null {
  const entry = entries[index];
  if (entry === undefined || entry.disabled === true) return null;

  return entry.id;
}
