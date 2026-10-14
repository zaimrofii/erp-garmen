import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

/**
 * cn — penggabung className kondisional + resolver konflik utility Tailwind.
 *
 * Fase 1 (§1.1): pure function, tanpa React, deterministic.
 * - `clsx` menangani semua bentuk input: string, array, object `{ 'class': boolean }`,
 *   nested array/object, dan nilai falsy (`false`, `null`, `undefined`, `0`, `''`).
 * - `tailwind-merge` memastikan saat ada utility yang konflik (mis. `p-2` vs `p-4`),
 *   yang **terakhir** yang menang.
 *
 * Contoh:
 *   cn('a', 'b')                                  // 'a b'
 *   cn('p-2', 'p-4')                              // 'p-4'
 *   cn('a', false && 'b', { c: true, d: false })  // 'a c'
 */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

export default cn;
