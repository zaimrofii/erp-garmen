import { ChatterEventSchema, type ChatterEvent } from '@/lib/schemas/chatter.schema';
import { mergeChatterPreview } from '@/lib/chatter-merge';
import type { WsEvent } from '@/core/useWebSocket';

/**
 * ws-chatter.ts — real-time → chatter (Fase E), seluruhnya **murni**.
 *
 * Backend mengirim setiap aksi bundle ke group WebSocket `bundle.<id>` dengan
 * `event` berbentuk chatter kontrak §8 (lihat `core/event_bus/websocket.py`).
 * Modul ini mengubahnya menjadi:
 *
 *  1. `ChatterEvent` tervalidasi (`ChatterEventSchema` — bentuk yang SAMA dengan
 *     metadata/chatter, jadi tidak ada validasi kedua yang berbeda);
 *  2. metadata mentah dengan `chatter.preview` yang sudah di-prepend event baru.
 *
 * Catatan penting: `preview` di metadata dibatasi `CHATTER_PREVIEW_LIMIT` (5) oleh
 * `ChatterPageSchema` — jadi penggabungan **wajib** memotong ke 5 event terbaru,
 * supaya `validateMetadata()` di `DynamicCanvas` tetap lolos.
 */

/** PURE — event chatter dari satu event WS; `null` kalau bukan event valid. */
export function readWsChatterEvent(event: WsEvent): ChatterEvent | null {
  const parsed = ChatterEventSchema.safeParse(event.event ?? event.payload);
  return parsed.success ? parsed.data : null;
}

/**
 * PURE — gabung preview lama + event baru (dedup by id, urut terbaru dulu,
 * dipotong `CHATTER_PREVIEW_LIMIT`).
 *
 * Dedup memakai `mergeChatterPreview` (lib yang sama dengan ChatterPanel), lalu
 * diurutkan ulang karena backend selalu mengirim chatter **terbaru dulu**
 * (`-ts, -id`) sedangkan `mergeChatterPreview` menambahkan di belakang.
 */
export function mergeWsChatter(
  existing: readonly ChatterEvent[],
  incoming: readonly ChatterEvent[]
): ChatterEvent[] {
  if (incoming.length === 0) return [...existing];

  // Satu jalur merge (D4): prepend + dedup + potong `CHATTER_PREVIEW_LIMIT` + urut
  // `created_at` menurun — semua sudah ditangani `mergeChatterPreview`.
  return mergeChatterPreview(existing, incoming);
}

/** PURE — jumlah event yang belum ada di preview (untuk update `total_count`). */
export function countNewEvents(
  existing: readonly ChatterEvent[],
  incoming: readonly ChatterEvent[]
): number {
  const seen = new Set(existing.map((event) => event.id));
  return incoming.filter((event) => !seen.has(event.id)).length;
}

/**
 * PURE — metadata mentah + blok `chatter` yang diperkaya event real-time.
 *
 * Metadata yang tidak punya blok `chatter` (atau bentuknya tidak terduga)
 * dikembalikan apa adanya: real-time tidak boleh merusak render metadata.
 * `total_count` ditambah hanya untuk event yang memang baru (event duplikat dari
 * reconnect/refetch tidak menggelembungkan hitungan).
 */
export function mergeWsEventsIntoMetadata(
  raw: unknown,
  events: readonly ChatterEvent[]
): unknown {
  if (events.length === 0) return raw;
  if (typeof raw !== 'object' || raw === null || Array.isArray(raw)) return raw;

  const metadata = raw as Record<string, unknown>;
  const chatter = metadata['chatter'];
  if (typeof chatter !== 'object' || chatter === null || Array.isArray(chatter)) return raw;

  const page = chatter as Record<string, unknown>;
  const preview = page['preview'];
  if (!Array.isArray(preview)) return raw;

  const existing: ChatterEvent[] = [];
  for (const item of preview) {
    const parsed = ChatterEventSchema.safeParse(item);
    if (parsed.success) existing.push(parsed.data);
  }

  const merged = mergeWsChatter(existing, events);
  const added = countNewEvents(existing, events);
  const total = typeof page['total_count'] === 'number' ? page['total_count'] : existing.length;

  return {
    ...metadata,
    chatter: { ...page, preview: merged, total_count: total + added },
  };
}
