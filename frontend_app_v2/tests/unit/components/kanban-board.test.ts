import { readFileSync } from 'node:fs';
import path from 'node:path';
import type { ReactElement } from 'react';
import { describe, expect, it, vi } from 'vitest';
import {
  KanbanBoard,
  KanbanMoveConfirmDialog,
  type KanbanBoardProps,
  type KanbanMove,
} from '@/components/molecules/KanbanBoard';
import {
  decodeKanbanDrag,
  encodeKanbanDrag,
  KANBAN_DRAG_FORMAT,
  kanbanRowClass,
  resolveKanbanDrop,
} from '@/lib/kanban';
import { attrOf, attrsOf, findElement, htmlOf, textOf } from '../../helpers/react-tree';
import type { KanbanCardData, KanbanColumn, KanbanTransition } from '@/types/kanban';

/**
 * FASE K3 - `KanbanBoard`.
 *
 * `KanbanBoard` sengaja TANPA hook (sorotan kolom ada di komponen kolom) sehingga test
 * boleh memanggilnya sebagai fungsi lalu mem-walk pohon element untuk mengambil handler
 * `onDropCard`/`onDragOverColumn`/`onCardDragStart`. TANPA jsdom: yang diuji adalah
 * KEPUTUSAN handler (dipanggil dengan event tiruan), bukan perilaku browser.
 */

const CARD: KanbanCardData = {
  id: 7,
  code: 'BND-1',
  work_order_code: 'WO-1',
  size: 'L',
  qty: 5,
  state: 'DRAFT',
  allowed_actions: [],
};

const COLUMNS: KanbanColumn[] = [
  { state: 'DRAFT', label: 'Draft', order: 10, count: 1, cards: [CARD], truncated: false },
  { state: 'CUTTING', label: 'Cutting', order: 20, count: 0, cards: [], truncated: false },
  { state: 'QC', label: 'QC', order: 40, count: 0, cards: [], truncated: false },
];

const TRANSITIONS: KanbanTransition[] = [
  { from: 'DRAFT', to: 'CUTTING', action_id: 'BUNDLE_START', label: 'Mulai Bundle' },
  { from: 'QC', to: 'DONE', action_id: 'BUNDLE_FINISH', label: 'Selesai' },
];

interface StubEvent {
  preventDefault: ReturnType<typeof vi.fn>;
  dataTransfer: {
    getData: (format: string) => string;
    setData: ReturnType<typeof vi.fn>;
    dropEffect: string;
    effectAllowed: string;
  };
}

function dropEvent(raw: string): StubEvent {
  return {
    preventDefault: vi.fn(),
    dataTransfer: { getData: () => raw, setData: vi.fn(), dropEffect: 'none', effectAllowed: 'none' },
  };
}

function board(overrides: Partial<KanbanBoardProps> = {}): ReactElement {
  return KanbanBoard({
    columns: COLUMNS,
    transitions: TRANSITIONS,
    onCardMove: vi.fn(),
    ...overrides,
  });
}

/** Elemen kolom (komponen kolom internal) untuk `state` tertentu. */
function columnElement(tree: ReactElement, state: string): ReactElement<Record<string, unknown>> {
  const found = findElement(tree, (element) => {
    const column = element.props['column'];
    if (typeof column !== 'object' || column === null) return false;

    return (
      new Map(Object.entries(column)).get('state') === state &&
      typeof element.props['onDropCard'] === 'function'
    );
  });
  expect(found).toBeDefined();

  return found!;
}

function callDrop(tree: ReactElement, state: string, event: StubEvent): void {
  const handler = columnElement(tree, state).props['onDropCard'];
  (handler as (value: unknown, target: string) => void)(event, state);
}

const DRAG_OF_DRAFT_CARD = encodeKanbanDrag({ id: CARD.id, from: 'DRAFT' });

describe('FASE K3 - KanbanBoard: struktur', () => {
  it('merender kolom sesuai props (urutannya seperti dari backend)', () => {
    const tree = board();

    expect(attrsOf(tree, 'data-kanban-column')).toEqual(['DRAFT', 'CUTTING', 'QC']);
    expect(textOf(tree)).toContain('Draft');
    expect(textOf(tree)).toContain('Cutting');
  });

  it('badge count per kolom mengikuti `count` (bukan jumlah kartu yang dipotong)', () => {
    const tree = board({
      columns: [{ ...COLUMNS[0], count: 12, truncated: true }, COLUMNS[1], COLUMNS[2]],
    });

    expect(attrsOf(tree, 'data-kanban-column-count')).toEqual(['12', '0', '0']);
    expect(htmlOf(tree)).toContain('+11');
  });

  it('empty state per kolom: kotak garis putus-putus + pesan', () => {
    const tree = board({ emptyMessage: 'Belum ada bundle' });
    const html = htmlOf(tree);

    expect(attrsOf(tree, 'data-kanban-column-empty')).toEqual(['CUTTING', 'QC']);
    expect(textOf(tree)).toContain('Belum ada bundle');
    expect(html).toContain('border-dashed');
  });

  it('loading: 3 skeleton abu-abu per kolom & kartu tidak dirender', () => {
    const tree = board({ loading: true });
    const html = htmlOf(tree);

    expect(attrsOf(tree, 'data-kanban-skeleton')).toEqual([
      'DRAFT',
      'DRAFT',
      'DRAFT',
      'CUTTING',
      'CUTTING',
      'CUTTING',
      'QC',
      'QC',
      'QC',
    ]);
    expect(html).toContain('animate-pulse');
    expect(textOf(tree)).not.toContain('BND-1');
  });

  it('tanpa kolom: pesan `emptyMessage` di level papan', () => {
    const tree = board({ columns: [], emptyMessage: 'Belum ada kolom' });

    expect(textOf(tree)).toContain('Belum ada kolom');
    expect(attrsOf(tree, 'data-kanban-column')).toEqual([]);
  });

  it('onDragOver kolom: preventDefault + dropEffect `move`', () => {
    const event = dropEvent('');
    const handler = columnElement(board(), 'CUTTING').props['onDragOverColumn'];

    (handler as (value: unknown) => void)(event);

    expect(event.preventDefault).toHaveBeenCalledTimes(1);
    expect(event.dataTransfer.dropEffect).toBe('move');
  });
});

describe('FASE K3 - KanbanBoard: drop', () => {
  it('transisi valid: onCardMove dipanggil dengan action_id backend', () => {
    const onCardMove = vi.fn();
    const onInvalidMove = vi.fn();
    const tree = board({ onCardMove, onInvalidMove });

    callDrop(tree, 'CUTTING', dropEvent(DRAG_OF_DRAFT_CARD));

    expect(onCardMove).toHaveBeenCalledTimes(1);
    expect(onCardMove).toHaveBeenCalledWith({
      cardId: 7,
      cardCode: 'BND-1',
      from: 'DRAFT',
      to: 'CUTTING',
      actionId: 'BUNDLE_START',
    });
    expect(onInvalidMove).not.toHaveBeenCalled();
  });

  it('transisi TIDAK valid: BATAL (tanpa onCardMove) + alasan untuk toast', () => {
    const onCardMove = vi.fn();
    const onInvalidMove = vi.fn();
    const tree = board({ onCardMove, onInvalidMove });

    callDrop(tree, 'QC', dropEvent(DRAG_OF_DRAFT_CARD));

    expect(onCardMove).not.toHaveBeenCalled();
    expect(onInvalidMove).toHaveBeenCalledTimes(1);
    expect(onInvalidMove.mock.calls[0]?.[0]).toMatchObject({ cardId: 7, from: 'DRAFT', to: 'QC' });
    expect(String(onInvalidMove.mock.calls[0]?.[0]?.reason)).toContain('tidak tersedia');
  });

  it('drop ke kolom asal: ditolak dengan alasan "sudah berada di kolom ini"', () => {
    const onCardMove = vi.fn();
    const onInvalidMove = vi.fn();

    callDrop(board({ onCardMove, onInvalidMove }), 'DRAFT', dropEvent(DRAG_OF_DRAFT_CARD));

    expect(onCardMove).not.toHaveBeenCalled();
    expect(String(onInvalidMove.mock.calls[0]?.[0]?.reason)).toContain('sudah berada di kolom ini');
  });

  it('payload drag rusak/kosong: tidak ada callback (drag dari luar papan)', () => {
    const onCardMove = vi.fn();
    const onInvalidMove = vi.fn();
    const tree = board({ onCardMove, onInvalidMove });

    callDrop(tree, 'CUTTING', dropEvent(''));
    callDrop(tree, 'CUTTING', dropEvent('{bukan json}'));

    expect(onCardMove).not.toHaveBeenCalled();
    expect(onInvalidMove).not.toHaveBeenCalled();
  });
});

describe('FASE K3 - KanbanBoard: drag start & layout', () => {
  it('onCardDragStart menulis payload ke dataTransfer (format K3) + effectAllowed', () => {
    const event = dropEvent('');
    const handler = columnElement(board(), 'DRAFT').props['onCardDragStart'];

    (handler as (value: unknown, from: string, dragEvent: unknown) => void)(CARD, 'DRAFT', event);

    expect(event.dataTransfer.setData).toHaveBeenCalledWith(
      KANBAN_DRAG_FORMAT,
      encodeKanbanDrag({ id: CARD.id, from: 'DRAFT' }),
    );
    expect(event.dataTransfer.effectAllowed).toBe('move');
  });

  it('layout: geser-snap di HP, grid penuh di xl untuk 4-6 kolom', () => {
    expect(kanbanRowClass(5)).toContain('xl:grid-cols-5');
    expect(kanbanRowClass(4)).toContain('xl:grid-cols-4');
    expect(kanbanRowClass(7)).not.toContain('xl:grid-cols-');
    expect(kanbanRowClass(0)).toContain('snap-x');
    expect(htmlOf(board({ columns: [COLUMNS[0], COLUMNS[1]] }))).toContain('xl:grid-cols-2');
  });

  it('helper PURE: encode/decode + resolveKanbanDrop (case-insensitive & asing)', () => {
    const payload = decodeKanbanDrag(DRAG_OF_DRAFT_CARD);
    expect(payload).toEqual({ id: 7, from: 'DRAFT' });
    expect(decodeKanbanDrag('   ')).toBeNull();
    expect(decodeKanbanDrag('[1,2]')).toBeNull();

    const ok = resolveKanbanDrop({ id: 7, from: 'draft' }, 'cutting', TRANSITIONS);
    expect(ok).toMatchObject({ ok: true, actionId: 'BUNDLE_START' });

    const unknown = resolveKanbanDrop({ id: 7, from: 'DRAFT' }, 'QC', TRANSITIONS);
    expect(unknown.ok).toBe(false);
  });
});

describe('FASE K4 - KanbanBoard: empty state & skeleton', () => {
  it('emptyMessage tampil di SETIAP kolom kosong', () => {
    const tree = board({ emptyMessage: 'Belum ada bundle' });

    expect(attrsOf(tree, 'data-kanban-column-empty')).toEqual(['CUTTING', 'QC']);
    expect((textOf(tree).match(/Belum ada bundle/g) ?? [])).toHaveLength(2);
  });

  it('tanpa emptyMessage: teks bawaan "Belum ada kartu"', () => {
    const tree = board();

    expect(textOf(tree)).toContain('Belum ada kartu');
  });

  it('5 kolom saat loading: 3 skeleton per kolom & TANPA empty-state', () => {
    const five: KanbanColumn[] = [
      COLUMNS[0],
      COLUMNS[1],
      COLUMNS[2],
      { state: 'SEWING', label: 'Sewing', order: 30, count: 0, cards: [], truncated: false },
      { state: 'DONE', label: 'Done', order: 50, count: 12, cards: [], truncated: true },
    ];
    const tree = board({ columns: five, loading: true });

    expect(attrsOf(tree, 'data-kanban-skeleton')).toHaveLength(15);
    expect(attrsOf(tree, 'data-kanban-column-empty')).toEqual([]);
  });

  it('kolom `truncated` (count 12) tetap hanya 3 skeleton saat loading', () => {
    const tree = board({
      columns: [{ ...COLUMNS[0], count: 12, truncated: true }, COLUMNS[1]],
      loading: true,
    });

    expect(attrsOf(tree, 'data-kanban-skeleton')).toHaveLength(6);
  });
});

describe('K4.4 - KanbanMoveConfirmDialog', () => {
  const MOVE: KanbanMove = {
    cardId: 7,
    cardCode: 'BND-1',
    from: 'DRAFT',
    to: 'CUTTING',
    actionId: 'BUNDLE_START',
  };

  it('menampilkan kalimat konfirmasi + tombol Batal & Ya', () => {
    const tree = KanbanMoveConfirmDialog({ move: MOVE, resourceLabel: 'bundle', onConfirm: vi.fn(), onCancel: vi.fn() });

    expect(textOf(tree)).toContain('Pindah bundle BND-1 dari DRAFT ke CUTTING?');
    expect(textOf(tree)).toContain('Batal');
    expect(textOf(tree)).toContain('Ya, Pindahkan');
    expect(attrOf(tree, 'data-kanban-confirm-text')).toBe('7');
  });

  it('klik "Ya, Pindahkan" memanggil onConfirm', () => {
    const onConfirm = vi.fn();
    const tree = KanbanMoveConfirmDialog({ move: MOVE, onConfirm, onCancel: vi.fn() });

    const button = findElement(tree, (element) => element.props['aria-label'] === 'Ya, Pindahkan');
    expect(button).toBeDefined();
    const handler = button?.props['onClick'];
    expect(typeof handler).toBe('function');
    (handler as () => void)();

    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it('klik "Batal" memanggil onCancel TANPA onConfirm', () => {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    const tree = KanbanMoveConfirmDialog({ move: MOVE, onConfirm, onCancel });

    const button = findElement(tree, (element) => element.props['aria-label'] === 'Batal');
    expect(button).toBeDefined();
    const handler = button?.props['onClick'];
    expect(typeof handler).toBe('function');
    (handler as () => void)();

    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(onConfirm).not.toHaveBeenCalled();
  });
});

describe('K4.4 - konfirmasi sebelum pindah', () => {
  it('drop valid menyerahkan `move` ke onMoveRequest (bukan langsung onCardMove)', () => {
    const onCardMove = vi.fn();
    const onMoveRequest = vi.fn();
    const tree = board({ onCardMove, onMoveRequest });

    callDrop(tree, 'CUTTING', dropEvent(DRAG_OF_DRAFT_CARD));

    expect(onMoveRequest).toHaveBeenCalledTimes(1);
    expect(onMoveRequest.mock.calls[0]?.[0]).toMatchObject({ cardId: 7, cardCode: 'BND-1' });
    expect(onCardMove).not.toHaveBeenCalled();
  });

  it('halaman memakai wrapper konfirmasi; Modal hanya saat ada `pendingMove`', () => {
    const bundle = readFileSync(
      path.resolve(import.meta.dirname, '../../../src/pages/bundles/BundleListPage.tsx'),
      'utf8',
    );
    const boardSource = readFileSync(
      path.resolve(import.meta.dirname, '../../../src/components/molecules/KanbanBoard.tsx'),
      'utf8',
    );

    expect(bundle).toContain('KanbanBoardWithConfirm');
    expect(bundle).toContain('resourceLabel="bundle"');
    expect(boardSource).toContain('open={pendingMove !== null}');
    expect(boardSource).toContain('confirmMove = true');
    expect(boardSource).toContain('onMoveRequest={confirmMove ? setPendingMove : undefined}');
    expect(boardSource).toContain('boardProps.onCardMove(pendingMove)');
  });
});
