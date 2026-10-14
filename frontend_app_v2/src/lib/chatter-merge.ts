import { CHATTER_PREVIEW_LIMIT, type ChatterEvent } from '@/lib/schemas/chatter.schema';

/**
 * chatter-merge.ts — penggabungan event chatter + paginasi (murni).
 *
 * Dipisah dari komponen chatter supaya file komponen hanya mengekspor komponen
 * (React fast-refresh bersih) dan logikanya bisa diuji tanpa DOM.
 *
 * F1 (D4) — kontrak backend v4.3 (§3.3):
 * - endpoint chatter mengirim `preview` (BUKAN `events`, bentuk lama sudah dihapus di
 *   backend `B.2`) + `total_count`/`has_more`/`next_cursor`;
 * - `limit` default **20** (+ `cursor` opsional) → `buildChatterQuery`;
 * - event real-time (WebSocket) di-**prepend** ke `preview` dan hasilnya dipotong
 *   `CHATTER_PREVIEW_LIMIT` (5) supaya tetap lolos `ChatterPageSchema`.
 */

/** Default `limit` paginasi chatter (kontrak §3.3: "limit (default 20)"). */
export const CHATTER_PAGE_LIMIT_DEFAULT = 20;

/** Batas atas wajar supaya satu halaman tidak membanjiri UI (backend membatasi sendiri). */
export const CHATTER_PAGE_LIMIT_MAX = 100;

/** PURE — `limit` valid (1..100); nilai kosong/aneh → default 20. */
export function normalizeChatterLimit(limit?: number | null): number {
  if (typeof limit !== 'number' || !Number.isFinite(limit)) return CHATTER_PAGE_LIMIT_DEFAULT;

  const rounded = Math.floor(limit);
  if (rounded < 1) return CHATTER_PAGE_LIMIT_DEFAULT;

  return Math.min(rounded, CHATTER_PAGE_LIMIT_MAX);
}

export interface ChatterQuery {
  limit: number;
  /** `undefined` = halaman pertama (tanpa `cursor`). */
  cursor?: string;
}

/** PURE — query string chatter (`limit` default 20 + `cursor` kalau ada). */
export function buildChatterQuery(
  params: { limit?: number | null; cursor?: string | null } = {}
): ChatterQuery {
  const cursor = typeof params.cursor === 'string' ? params.cursor.trim() : '';

  const query: ChatterQuery = { limit: normalizeChatterLimit(params.limit) };
  if (cursor.length > 0) query.cursor = cursor;

  return query;
}

function toEventList(incoming: ChatterEvent | readonly ChatterEvent[]): readonly ChatterEvent[] {
  // Cast eksplisit: `Array.isArray` tidak mempersempit union yang memuat array readonly.
  return Array.isArray(incoming)
    ? (incoming as readonly ChatterEvent[])
    : [incoming as ChatterEvent];
}

/**
 * PURE — D4: `preview` baru = event masuk (terbaru dulu, dedup by `id`) **di depan**
 * `preview` lama, dipotong `CHATTER_PREVIEW_LIMIT` (5).
 *
 * `incoming` boleh satu event (event WebSocket tunggal) atau banyak (batch/refresh).
 * Urutannya mengikuti `created_at` menurun → kompatibel dengan backend yang selalu
 * mengirim chatter terbaru dulu; `preview` lama yang tidak ada di `incoming` dipertahankan
 * (urutan aslinya tidak diubah) supaya item yang sudah tampil tidak "melompat".
 */
export function mergeChatterPreview(
  preview: readonly ChatterEvent[],
  incoming: ChatterEvent | readonly ChatterEvent[]
): ChatterEvent[] {
  const sorted = [...toEventList(incoming)].sort((a, b) =>
    b.created_at.localeCompare(a.created_at)
  );

  const fresh: ChatterEvent[] = [];
  const seen = new Set<string>();
  for (const event of sorted) {
    if (seen.has(event.id)) continue;
    seen.add(event.id);
    fresh.push(event);
  }

  if (fresh.length === 0) return [...preview];

  const kept = preview.filter((event) => !seen.has(event.id));

  return [...fresh, ...kept].slice(0, CHATTER_PREVIEW_LIMIT);
}
