import { describe, expect, it } from 'vitest';
import {
  buildChatterQuery,
  CHATTER_PAGE_LIMIT_DEFAULT,
  CHATTER_PAGE_LIMIT_MAX,
  mergeChatterPreview,
  normalizeChatterLimit,
} from '@/lib/chatter-merge';
import { ChatterPageSchema, type ChatterEvent } from '@/lib/schemas/chatter.schema';

/** F1 — D4: merge `preview` (prepend event real-time, potong 5) + paginasi cursor/limit. */

function event(id: string, createdAt: string, summary = `event ${id}`): ChatterEvent {
  return {
    id,
    actor: { id: 'op-1', name: 'Operator Satu' },
    type: 'state_change',
    summary,
    payload: { to: 'CUTTING' },
    created_at: createdAt,
  };
}

const PREVIEW = [
  event('evt-3', '2026-10-08T10:00:00Z'),
  event('evt-2', '2026-10-08T09:00:00Z'),
  event('evt-1', '2026-10-08T08:00:00Z'),
];

describe('D4 — mergeChatterPreview', () => {
  it('event WebSocket di-prepend ke depan preview', () => {
    const merged = mergeChatterPreview(PREVIEW, event('evt-4', '2026-10-08T11:00:00Z'));

    expect(merged.map((item) => item.id)).toEqual(['evt-4', 'evt-3', 'evt-2', 'evt-1']);
  });

  it('dedup by id — event yang sudah ada tidak dobel', () => {
    const merged = mergeChatterPreview(PREVIEW, event('evt-2', '2026-10-08T09:30:00Z'));

    expect(merged.map((item) => item.id)).toEqual(['evt-2', 'evt-3', 'evt-1']);
    expect(merged).toHaveLength(3);
  });

  it('batch event diurutkan `created_at` menurun lalu di-prepend', () => {
    const batch = [event('evt-5', '2026-10-08T11:00:00Z'), event('evt-6', '2026-10-08T12:00:00Z')];
    const merged = mergeChatterPreview(PREVIEW, batch);

    expect(merged.map((item) => item.id)).toEqual(['evt-6', 'evt-5', 'evt-3', 'evt-2', 'evt-1']);
  });

  it('hasil dipotong ke CHATTER_PREVIEW_LIMIT (5) supaya ChatterPageSchema lolos', () => {
    const incoming = [
      event('n1', '2026-10-08T15:00:00Z'),
      event('n2', '2026-10-08T14:00:00Z'),
      event('n3', '2026-10-08T13:00:00Z'),
      event('n4', '2026-10-08T12:30:00Z'),
    ];

    const merged = mergeChatterPreview(PREVIEW, incoming);
    expect(merged).toHaveLength(5);

    const page = ChatterPageSchema.safeParse({
      preview: merged,
      total_count: 7,
      has_more: true,
      next_cursor: 'evt-1',
    });
    expect(page.success).toBe(true);
  });

  it('incoming kosong → preview lama dikembalikan apa adanya (array baru)', () => {
    const merged = mergeChatterPreview(PREVIEW, []);

    expect(merged).toEqual(PREVIEW);
    expect(merged).not.toBe(PREVIEW);
  });
});

describe('D4 — paginasi cursor + limit (default 20)', () => {
  it('normalizeChatterLimit', () => {
    expect(CHATTER_PAGE_LIMIT_DEFAULT).toBe(20);
    expect(normalizeChatterLimit(undefined)).toBe(20);
    expect(normalizeChatterLimit(null)).toBe(20);
    expect(normalizeChatterLimit(0)).toBe(20);
    expect(normalizeChatterLimit(-3)).toBe(20);
    expect(normalizeChatterLimit(Number.NaN)).toBe(20);
    expect(normalizeChatterLimit(5)).toBe(5);
    expect(normalizeChatterLimit(7.9)).toBe(7);
    expect(normalizeChatterLimit(9999)).toBe(CHATTER_PAGE_LIMIT_MAX);
  });

  it('buildChatterQuery: halaman pertama (limit default, tanpa cursor)', () => {
    expect(buildChatterQuery()).toEqual({ limit: 20 });
    expect(buildChatterQuery({ cursor: '   ' })).toEqual({ limit: 20 });
  });

  it('buildChatterQuery: halaman berikutnya memakai cursor', () => {
    expect(buildChatterQuery({ limit: 5, cursor: ' evt-050 ' })).toEqual({
      limit: 5,
      cursor: 'evt-050',
    });
  });
});
