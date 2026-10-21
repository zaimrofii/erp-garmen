import type { ReactElement } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { KanbanCard } from '@/components/molecules/KanbanCard';
import { attrOf, findElement, htmlOf, textOf } from '../../helpers/react-tree';
import type { KanbanCardData } from '@/types/kanban';

/**
 * FASE K3 - `KanbanCard`.
 *
 * Tanpa jsdom: kartu dipanggil sebagai FUNGSI (tanpa hook) sehingga pohon element bisa
 * di-walk untuk mengambil handler drag; teks/atribut diperiksa dari HTML `react-dom/server`.
 */

const CARD: KanbanCardData = {
  id: 11,
  code: '12-L-001',
  work_order_code: 'WO-2026-0001',
  size: 'L',
  qty: 5,
  state: 'DRAFT',
  allowed_actions: [{ id: 'BUNDLE_START', label: 'Mulai Bundle', mode: 'optimistic' }],
};

interface FakeDragEvent {
  dataTransfer: { setData: (format: string, value: string) => void; effectAllowed: string };
}

function dragEvent(): FakeDragEvent {
  return { dataTransfer: { setData: vi.fn(), effectAllowed: 'none' } };
}

function root(tree: ReactElement): ReactElement<Record<string, unknown>> {
  const found = findElement(tree, (element) => element.props['data-kanban-card'] === CARD.id);
  expect(found).toBeDefined();

  return found!;
}

describe('FASE K3 - KanbanCard', () => {
  it('menampilkan kode, state, dan baris info (size/qty/WO)', () => {
    const tree = KanbanCard({ card: CARD });
    const text = textOf(tree);

    expect(text).toContain('12-L-001');
    expect(text).toContain('DRAFT');
    expect(text).toContain('L · 5 pcs · WO-2026-0001');
  });

  it('tanpa `qty`/`work_order_code`: baris info tetap rapi', () => {
    const tree = KanbanCard({
      card: { ...CARD, size: null, qty: 0, work_order_code: null },
    });

    expect(textOf(tree)).toContain('0 pcs');
    expect(textOf(tree)).not.toContain('· null');
  });

  it('draggable menandai atribut drag + redup saat `dragging`', () => {
    const idle = KanbanCard({ card: CARD, draggable: true });
    const dragging = KanbanCard({ card: CARD, draggable: true, dragging: true });

    expect(attrOf(idle, 'draggable')).toBe('true');
    expect(attrOf(idle, 'data-kanban-card-dragging')).toBeUndefined();
    expect(attrOf(dragging, 'data-kanban-card-dragging')).toBe('true');
    expect(htmlOf(dragging)).toContain('opacity-60');
  });

  it('tanpa `draggable`: tidak ada atribut drag (kartu statis)', () => {
    const tree = KanbanCard({ card: CARD });

    expect(attrOf(tree, 'draggable')).toBeUndefined();
    expect(htmlOf(tree)).not.toContain('cursor-grab');
  });

  it('onDragStart meneruskan kartu + event ke pemanggil', () => {
    const onDragStart = vi.fn();
    const event = dragEvent();
    const tree = KanbanCard({ card: CARD, draggable: true, onDragStart });

    callPropDragStart(root(tree), event);

    expect(onDragStart).toHaveBeenCalledTimes(1);
    expect(onDragStart.mock.calls[0]?.[0]).toEqual(CARD);
    expect(onDragStart.mock.calls[0]?.[1]).toBe(event);
  });

  it('pegangan drag punya ikon tersembunyi & onClick hanya saat diberikan', () => {
    const withoutClick = KanbanCard({ card: CARD, draggable: true });
    const onClick = vi.fn();
    const withClick = KanbanCard({ card: CARD, onClick });

    expect(textOf(withoutClick)).toContain('Tarik untuk pindah kolom');
    expect(htmlOf(withoutClick)).not.toContain('Buka 12-L-001');

    const openButton = findElement(withClick, (element) => element.props['aria-label'] === 'Buka 12-L-001');
    expect(openButton).toBeDefined();
    expect(findElement(withoutClick, (element) => element.props['aria-label'] === 'Buka 12-L-001')).toBeUndefined();

    callProp(openButton!, 'onClick');
    expect(onClick).toHaveBeenCalledWith(CARD);
  });
});

/** Panggil `onDragStart` pada pembungkus kartu (handler menerima `event` DOM). */
function callPropDragStart(
  element: ReactElement<Record<string, unknown>>,
  event: FakeDragEvent,
): void {
  const handler = element.props['onDragStart'];
  expect(typeof handler).toBe('function');
  (handler as (value: unknown) => void)(event);
}

function callProp(element: ReactElement<Record<string, unknown>>, key: string): void {
  const handler = element.props[key];
  expect(typeof handler).toBe('function');
  (handler as () => void)();
}
