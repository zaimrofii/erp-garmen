import type { ComponentProps, ReactNode } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { ChatterBox } from '@/components/molecules/ChatterBox';
import type { ChatterEvent } from '@/lib/schemas/chatter.schema';
import { attrOf, attrsOf, callProp, findElement, textOf } from '../../helpers/react-tree';

/**
 * F1 (D4) — ChatterBox membaca `preview` (+ alias `events` untuk 3 halaman v3 lama).
 *
 * Komponen dipanggil sebagai FUNGSI (tanpa hook) supaya pohon element-nya bisa di-walk
 * untuk mencari handler; `textOf`/`attrOf` tetap memakai `react-dom/server`.
 * TIDAK ada klaim DOM/event browser (jsdom tidak jalan di bun).
 */

type ChatterProps = ComponentProps<typeof ChatterBox>;

function renderChatter(props: ChatterProps): ReactNode {
  return ChatterBox(props);
}

function event(id: string, summary: string): ChatterEvent {
  return {
    id,
    actor: { id: 'op-1', name: 'Operator Satu' },
    type: 'state_change',
    summary,
    payload: { to: 'CUTTING' },
    created_at: '2026-10-08T10:00:00Z',
  };
}

const PREVIEW = [event('evt-2', 'Bundle lanjut ke cutting'), event('evt-1', 'Bundle mulai')];

describe('ChatterBox — prop `preview`', () => {
  it('render item sesuai urutan preview + penanda `data-chatter-event`', () => {
    const tree = renderChatter({ preview: PREVIEW });

    expect(attrOf(tree, 'data-chatter-preview-count')).toBe('2');
    expect(attrsOf(tree, 'data-chatter-event')).toEqual(['evt-2', 'evt-1']);
    expect(textOf(tree)).toContain('Bundle lanjut ke cutting');
    expect(textOf(tree)).toContain('Operator Satu');
  });

  it('preview kosong → state kosong (bukan crash)', () => {
    const tree = renderChatter({ preview: [] });

    expect(attrOf(tree, 'data-chatter-preview-count')).toBe('0');
    expect(textOf(tree)).toContain('Belum ada aktivitas');
  });

  it('hanya membaca `preview` — alias `events` dihapus (F4/4.3)', () => {
    // `preview` sekarang WAJIB (types) sehingga tidak ada jalur lain yang bisa mengisi
    // daftar; "prop kedua menang" tidak lagi mungkin.
    const tree = renderChatter({ preview: PREVIEW });

    expect(attrOf(tree, 'data-chatter-preview-count')).toBe('2');
    expect(attrsOf(tree, 'data-chatter-event')).toEqual(['evt-2', 'evt-1']);
  });

  it('loading → keterangan memuat', () => {
    const tree = renderChatter({ preview: [], loading: true });

    expect(textOf(tree)).toContain('Memuat aktivitas...');
  });
});

describe('ChatterBox — paginasi (limit/cursor/hasMore)', () => {
  it('limit default 20 & cursor kosong ditandai (kontrak §3.3)', () => {
    const tree = renderChatter({ preview: PREVIEW });

    expect(attrOf(tree, 'data-chatter-limit')).toBe('20');
    expect(attrOf(tree, 'data-chatter-cursor')).toBe('');
  });

  it('limit + cursor dari `chatter.next_cursor` tampil sebagai jejak halaman', () => {
    const tree = renderChatter({ preview: PREVIEW, limit: 5, cursor: 'evt-050' });

    expect(attrOf(tree, 'data-chatter-limit')).toBe('5');
    expect(attrOf(tree, 'data-chatter-cursor')).toBe('evt-050');
  });

  it('hasMore + onLoadMore → tombol memanggil handler (tanpa DOM event)', () => {
    const onLoadMore = vi.fn();
    const tree = renderChatter({ preview: PREVIEW, hasMore: true, limit: 5, onLoadMore });

    expect(textOf(tree)).toContain('Muat lebih banyak');

    const button = findElement(tree, (el) => el.props['aria-label'] === 'Muat 5 aktivitas lagi');
    expect(button).toBeDefined();

    callProp(button!, 'onClick');
    expect(onLoadMore).toHaveBeenCalledTimes(1);
  });

  it('tanpa hasMore → tombol tidak dirender', () => {
    const tree = renderChatter({ preview: PREVIEW, onLoadMore: vi.fn() });

    expect(textOf(tree)).not.toContain('Muat lebih banyak');
  });
});

