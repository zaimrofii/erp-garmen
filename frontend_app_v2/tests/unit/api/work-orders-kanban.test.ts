import { describe, expect, it } from 'vitest';
import { MODE, isReal } from '@/api/_adapter';
import { readKanbanResponse } from '@/api/real/kanban';
import {
  buildWorkOrdersKanbanPath,
  fetchWorkOrdersKanban,
  WORK_ORDERS_KANBAN_PATH,
} from '@/api/workOrdersKanban';
import type { ApiClient, ApiResponse } from '@/integrations/api-client';

/**
 * FASE K3 - adapter papan kanban WORK ORDER (`/garmen/work-orders/kanban/`).
 *
 * Kartu WO memakai kunci yang SAMA dengan bundle (kontrak K2): `work_order_code` = kode
 * WO itu sendiri, `size` = null, `qty` = `qty_planned`.
 */

const PAYLOAD = {
  resource: 'work-orders',
  industry: 'garmen',
  machine: 'garment.work_order',
  columns: [
    {
      state: 'DRAFT',
      label: 'Draft',
      order: 10,
      count: 1,
      truncated: false,
      cards: [
        {
          id: 3,
          code: 'WO-2026-0001',
          work_order_code: 'WO-2026-0001',
          size: null,
          qty: 40,
          state: 'DRAFT',
          allowed_actions: [{ id: 'WO_START', label: 'Mulai WO', mode: 'optimistic' }],
        },
      ],
    },
    { state: 'IN_PROGRESS', label: 'In Progress', order: 20, count: 0, truncated: false, cards: [] },
  ],
  transitions: [{ from: 'DRAFT', to: 'IN_PROGRESS', action_id: 'WO_START', label: 'Mulai WO' }],
  total_count: 1,
  limit: 50,
  truncated: false,
  unknown_states: {},
  filters: { applied: {}, ignored: ['work_center_id'] },
};

function stubClient(data: unknown): { client: ApiClient; requests: string[] } {
  const requests: string[] = [];
  const reply = <T,>(): ApiResponse<T> => ({ ok: true, status: 200, data: data as T });

  const client = {
    get: async <T,>(requestPath: string): Promise<ApiResponse<T>> => {
      requests.push(requestPath);

      return reply<T>();
    },
  } as unknown as ApiClient;

  return { client, requests };
}

describe('FASE K3 - path kanban work order', () => {
  it('path polos & query param terisi saja', () => {
    expect(buildWorkOrdersKanbanPath()).toBe(WORK_ORDERS_KANBAN_PATH);
    expect(buildWorkOrdersKanbanPath()) .toBe('/garmen/work-orders/kanban/');

    const built = buildWorkOrdersKanbanPath({ search: 'WO-2026', limit: 5 });
    expect(built).toBe('/garmen/work-orders/kanban/?search=WO-2026&limit=5');
  });
});

describe('FASE K3 - fetch & parse kanban work order', () => {
  it('GET path kanban WO + kartu WO berbentuk sama dengan bundle', async () => {
    const { client, requests } = stubClient(PAYLOAD);

    const board = await fetchWorkOrdersKanban(client, { limit: 5 });

    expect(requests[0]).toBe('/garmen/work-orders/kanban/?limit=5');
    expect(board.machine).toBe('garment.work_order');
    expect(board.columns.map((column) => column.label)).toEqual(['Draft', 'In Progress']);
    expect(board.columns[0]?.cards[0]).toEqual({
      id: 3,
      code: 'WO-2026-0001',
      work_order_code: 'WO-2026-0001',
      size: null,
      qty: 40,
      state: 'DRAFT',
      allowed_actions: [{ id: 'WO_START', label: 'Mulai WO', mode: 'optimistic' }],
    });
    expect(board.transitions[0]?.action_id).toBe('WO_START');
  });

  it('kolom tanpa kartu & filter `ignored` tetap dibaca apa adanya', async () => {
    const { client } = stubClient(PAYLOAD);

    const board = await fetchWorkOrdersKanban(client);

    expect(board.columns[1]?.cards).toEqual([]);
    expect(board.filters.ignored).toEqual(['work_center_id']);
    expect(board.total_count).toBe(1);
  });

  it('parser toleran terhadap kolom/kartu rusak (dibuang, bukan crash)', () => {
    const parsed = readKanbanResponse({
      columns: [{ state: 'DRAFT', label: 'Draft', cards: [{ code: 'tanpa-id' }, null] }, { label: 'Tanpa state' }],
      transitions: [{ from: 'DRAFT' }],
    });

    expect(parsed?.columns).toHaveLength(1);
    expect(parsed?.columns[0]?.cards).toEqual([]);
    expect(parsed?.transitions).toEqual([]);
  });

  it('MODE.workOrdersKanban `real` tanpa mengubah `workOrders` (list F13)', () => {
    expect(MODE['workOrdersKanban']).toBe('real');
    expect(isReal('workOrdersKanban')).toBe(true);
    expect(MODE['workOrders']).toBe('real');
    expect(MODE['workOrdersCrud']).toBe('real');
  });
});
