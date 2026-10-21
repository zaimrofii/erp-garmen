import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it, vi } from 'vitest';
import { KanbanBoard } from '@/components/molecules/KanbanBoard';
import { moveCardInKanban } from '@/lib/kanban';
import { findElement } from '../../helpers/react-tree';
import type { KanbanColumn, KanbanResponse, KanbanTransition } from '@/types/kanban';

/**
 * FASE K4 - pindah kartu WORK ORDER: `onCardMove` -> `POST /garmen/work-orders/<id>/<ACTION>/`.
 *
 * Sama seperti bundle, tetapi ACTION_ID wajib lolos gerbang `WORK_ORDER_ACTIONS`
 * (`toWorkOrderAction`) sebelum dikirim; optimistic + rollback ditangani `useKanbanMove`.
 */

const ROOT = path.resolve(import.meta.dirname, '../../..');

function read(relative: string): string {
  return readFileSync(path.join(ROOT, relative), 'utf8');
}

const PAGE = read('src/pages/work-orders/WorkOrderListPage.tsx');
const HOOK = read('src/hooks/useKanbanMove.ts');

const CARD = {
  id: 3,
  code: 'WO-2026-0001',
  work_order_code: 'WO-2026-0001',
  size: null,
  qty: 40,
  state: 'DRAFT',
  allowed_actions: [],
};

const COLUMNS: KanbanColumn[] = [
  { state: 'DRAFT', label: 'Draft', order: 10, count: 1, cards: [CARD], truncated: false },
  { state: 'IN_PROGRESS', label: 'In Progress', order: 20, count: 0, cards: [], truncated: false },
  { state: 'CANCELLED', label: 'Cancelled', order: 40, count: 0, cards: [], truncated: false },
];

const TRANSITIONS: KanbanTransition[] = [
  { from: 'DRAFT', to: 'IN_PROGRESS', action_id: 'WO_START', label: 'Mulai WO' },
];

const RESPONSE: KanbanResponse = {
  resource: 'work-orders',
  industry: 'garmen',
  machine: 'garment.work_order',
  columns: COLUMNS,
  transitions: TRANSITIONS,
  total_count: 1,
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

describe('FASE K4 - WO kanban: onCardMove valid', () => {
  it('kartu WO berpindah di cache & aksi dijaga union WORK_ORDER_ACTIONS', () => {
    const moved = moveCardInKanban(RESPONSE, {
      cardId: 3,
      from: 'DRAFT',
      to: 'IN_PROGRESS',
    });

    expect(columnOf(moved, 'DRAFT').count).toBe(0);
    expect(columnOf(moved, 'IN_PROGRESS').cards.map((card) => card.id)).toEqual([3]);
    expect(columnOf(moved, 'IN_PROGRESS').count).toBe(1);

    expect(PAGE).toContain('runAction: (cardId, actionId) =>');
    expect(PAGE).toContain('runWorkOrderCrudAction(client, cardId, toWorkOrderAction(actionId))');
    expect(PAGE).toContain('queryKey: workOrdersKanbanQueryKey(KANBAN_PARAMS)');
    expect(PAGE).toContain('WORK_ORDER_ACTIONS');
  });
});

describe('FASE K4 - WO kanban: transisi invalid', () => {
  it('drop ke CANCELLED (tanpa transisi DRAFT->CANCELLED di daftar): BATAL + toast', () => {
    const onCardMove = vi.fn();
    const onInvalidMove = vi.fn();
    const tree = KanbanBoard({
      columns: COLUMNS,
      transitions: TRANSITIONS,
      onCardMove,
      onInvalidMove,
    });
    const cancelled = findElement(
      tree,
      (element) =>
        typeof element.props['column'] === 'object' &&
        element.props['column'] !== null &&
        Object.entries(element.props['column']).some(
          ([key, value]) => key === 'state' && value === 'CANCELLED',
        ) &&
        typeof element.props['onDropCard'] === 'function',
    );
    const handler = cancelled?.props['onDropCard'];
    const event = { preventDefault: vi.fn(), dataTransfer: { getData: () => JSON.stringify({ id: 3, from: 'DRAFT' }) } };

    (handler as (value: unknown, target: string) => void)(event, 'CANCELLED');

    expect(onCardMove).not.toHaveBeenCalled();
    expect(onInvalidMove).toHaveBeenCalledTimes(1);
    expect(PAGE).toContain('onInvalidMove={(invalid) => {');
    expect(PAGE).toContain('title="Perpindahan tidak valid"');
  });
});

describe('FASE K4 - WO kanban: error server', () => {
  it('rollback snapshot + invalidate daftar WO setelah settle', () => {
    const optimistic = moveCardInKanban(RESPONSE, { cardId: 3, from: 'DRAFT', to: 'IN_PROGRESS' });

    expect(columnOf(optimistic, 'DRAFT').count).toBe(0);
    expect(columnOf(RESPONSE, 'DRAFT').count).toBe(1); // snapshot utuh untuk rollback

    expect(HOOK).toContain('queryClient.setQueryData(queryKey, context.previous)');
    expect(PAGE).toContain('onErrorMessage: (message) => setMoveError(message)');
    expect(PAGE).toContain('alsoInvalidate: [["work-orders"]]');
  });
});
