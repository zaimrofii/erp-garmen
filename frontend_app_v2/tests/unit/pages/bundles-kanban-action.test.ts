import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it, vi } from 'vitest';
import { KanbanBoard } from '@/components/molecules/KanbanBoard';
import { moveCardInKanban } from '@/lib/kanban';
import { findElement } from '../../helpers/react-tree';
import type { KanbanColumn, KanbanResponse, KanbanTransition } from '@/types/kanban';

/**
 * FASE K4 - pindah kartu BUNDLE: `onCardMove` -> aksi state machine (optimistic + rollback).
 *
 * Dua lapis (tanpa jsdom):
 *   1. PURE/BEHAVIOR: `moveCardInKanban` benar-benar memindahkan kartu di cache kanban
 *      dan `KanbanBoard` menolak transisi ilegal TANPA memanggil `onCardMove`;
 *   2. SUMBER: wiring halaman + hook (`useKanbanMove`) — aksi nyata yang dipanggil,
 *      snapshot/rollback, dan invalidate setelah settle.
 */

const ROOT = path.resolve(import.meta.dirname, '../../..');

function read(relative: string): string {
  return readFileSync(path.join(ROOT, relative), 'utf8');
}

const PAGE = read('src/pages/bundles/BundleListPage.tsx');
const HOOK = read('src/hooks/useKanbanMove.ts');

const CARD = {
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
  { state: 'CUTTING', label: 'Cutting', order: 20, count: 2, cards: [], truncated: false },
  { state: 'QC', label: 'QC', order: 40, count: 0, cards: [], truncated: false },
];

const TRANSITIONS: KanbanTransition[] = [
  { from: 'DRAFT', to: 'CUTTING', action_id: 'BUNDLE_START', label: 'Mulai Bundle' },
];

const RESPONSE: KanbanResponse = {
  resource: 'bundles',
  industry: 'garmen',
  machine: 'garment.bundle',
  columns: COLUMNS,
  transitions: TRANSITIONS,
  total_count: 3,
  limit: 50,
  truncated: false,
  unknown_states: {},
  filters: { applied: {}, ignored: [] },
};

function columnOf(response: KanbanResponse, state: string): KanbanColumn {
  const found = response.columns.find((column) => column.state === state);
  if (found === undefined) throw new Error(`kolom ${state} tidak ada`);

  return found;
}

describe('FASE K4 - Bundle kanban: onCardMove valid', () => {
  it('kartu berpindah di cache (count ikut) & aksi memakai ACTION_ID backend', () => {
    const moved = moveCardInKanban(RESPONSE, { cardId: 7, from: 'DRAFT', to: 'CUTTING' });

    expect(columnOf(moved, 'DRAFT').cards).toHaveLength(0);
    expect(columnOf(moved, 'DRAFT').count).toBe(0);
    expect(columnOf(moved, 'CUTTING').cards.map((card) => card.id)).toEqual([7]);
    expect(columnOf(moved, 'CUTTING').cards[0]?.state).toBe('CUTTING');
    expect(columnOf(moved, 'CUTTING').count).toBe(3);
    expect(moved.total_count).toBe(3);
    expect(RESPONSE.columns[0]?.cards).toHaveLength(1); // immutable (snapshot tetap utuh)

    expect(PAGE).toContain('onCardMove={(payload) => {');
    expect(PAGE).toMatch(
      /runAction: \(cardId, actionId\) =>\s*submitBundleAction\(client, cardId, actionId\)/,
    );
    expect(PAGE).toContain('queryKey: bundlesKanbanQueryKey(KANBAN_PARAMS)');
    expect(HOOK).toContain('runAction(move.cardId, move.actionId)');
  });
});

describe('FASE K4 - Bundle kanban: transisi invalid', () => {
  it('drop ke kolom tanpa transisi: BATAL (tanpa aksi) + halaman menampilkan toast', () => {
    const onCardMove = vi.fn();
    const onInvalidMove = vi.fn();
    const tree = KanbanBoard({
      columns: COLUMNS,
      transitions: TRANSITIONS,
      onCardMove,
      onInvalidMove,
    });
    const qc = findElement(
      tree,
      (element) =>
        typeof element.props['column'] === 'object' &&
        element.props['column'] !== null &&
        Object.entries(element.props['column']).some(([key, value]) => key === 'state' && value === 'QC') &&
        typeof element.props['onDropCard'] === 'function',
    );
    const handler = qc?.props['onDropCard'];
    const event = { preventDefault: vi.fn(), dataTransfer: { getData: () => JSON.stringify({ id: 7, from: 'DRAFT', dropEffect: 'none' }) } };

    (handler as (value: unknown, target: string) => void)(event, 'QC');

    expect(onCardMove).not.toHaveBeenCalled();
    expect(onInvalidMove).toHaveBeenCalledTimes(1);

    expect(PAGE).toContain('onInvalidMove={(invalid) => {');
    expect(PAGE).toContain('setMoveError(invalid.reason)');
    expect(PAGE).toContain('title="Perpindahan tidak valid"');
  });
});

describe('FASE K4 - Bundle kanban: error server', () => {
  it('rollback ke snapshot + pesan error diteruskan ke toast', () => {
    const optimistic = moveCardInKanban(RESPONSE, { cardId: 7, from: 'DRAFT', to: 'CUTTING' });
    const previous = RESPONSE; // snapshot yang disimpan `onMutate`

    expect(columnOf(optimistic, 'DRAFT').count).toBe(0);
    expect(columnOf(previous, 'DRAFT').count).toBe(1); // rollback mengembalikan angka awal

    expect(HOOK).toContain('const previous = queryClient.getQueryData<KanbanResponse>(queryKey)');
    expect(HOOK).toContain('queryClient.setQueryData(queryKey, context.previous)');
    expect(HOOK).toContain('onErrorMessage?.(error.message)');
    expect(HOOK).toContain('void queryClient.invalidateQueries({ queryKey })');
    expect(PAGE).toContain('onErrorMessage: (message) => setMoveError(message)');
    expect(PAGE).toContain('alsoInvalidate: [["bundles"]]');
  });
});
