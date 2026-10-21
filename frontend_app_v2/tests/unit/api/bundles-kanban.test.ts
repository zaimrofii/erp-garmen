import { describe, expect, it } from 'vitest';
import { MODE, isReal } from '@/api/_adapter';
import { buildBundlesKanbanPath, BUNDLES_KANBAN_PATH, fetchBundlesKanban } from '@/api/bundlesKanban';
import { KANBAN_LIMIT_DEFAULT, readKanbanResponse } from '@/api/real/kanban';
import type { ApiClient, ApiResponse } from '@/integrations/api-client';

/**
 * FASE K3 - adapter papan kanban BUNDLE (`/garmen/bundles/kanban/`).
 *
 * Bentuk payload disalin dari backend K2 (`kanban_services.build_kanban_response`).
 * Tanpa server: `ApiClient` di-stub, jadi yang diuji = path + parsing (bukan HTTP).
 */

const PAYLOAD = {
  resource: 'bundles',
  industry: 'garmen',
  machine: 'garment.bundle',
  columns: [
    {
      state: 'DRAFT',
      label: 'Draft',
      order: 10,
      count: 2,
      truncated: false,
      cards: [
        {
          id: 11,
          code: 'BND-1',
          work_order_code: 'WO-1',
          size: 'L',
          qty: 5,
          state: 'DRAFT',
          allowed_actions: [
            { id: 'BUNDLE_START', label: 'Mulai Bundle', mode: 'optimistic', endpoint: '/garmen/bundles/11/BUNDLE_START/' },
          ],
        },
      ],
    },
    { state: 'CUTTING', label: 'Cutting', order: 20, count: 0, truncated: false, cards: [] },
  ],
  transitions: [{ from: 'DRAFT', to: 'CUTTING', action_id: 'BUNDLE_START', label: 'Mulai Bundle' }],
  total_count: 2,
  limit: 50,
  truncated: false,
  unknown_states: {},
  filters: { applied: { state: 'DRAFT' }, ignored: [] },
};

interface RecordedRequest {
  path: string;
  method: string;
}

function stubClient(data: unknown): { client: ApiClient; requests: RecordedRequest[] } {
  const requests: RecordedRequest[] = [];
  const reply = <T,>(): ApiResponse<T> => ({ ok: true, status: 200, data: data as T });

  const client = {
    get: async <T,>(requestPath: string): Promise<ApiResponse<T>> => {
      requests.push({ path: requestPath, method: 'GET' });

      return reply<T>();
    },
  } as unknown as ApiClient;

  return { client, requests };
}

describe('FASE K3 - path kanban bundle', () => {
  it('tanpa param: path polos tanpa query string', () => {
    expect(buildBundlesKanbanPath()).toBe(BUNDLES_KANBAN_PATH);
    expect(BUNDLES_KANBAN_PATH).toBe('/garmen/bundles/kanban/');
  });

  it('dengan param: hanya yang terisi + angka jadi string', () => {
    const built = buildBundlesKanbanPath({
      search: ' BND-1 ',
      state: 'draft',
      work_center_id: 4,
      line_id: 2,
      limit: 10,
    });

    expect(built.startsWith(`${BUNDLES_KANBAN_PATH}?`)).toBe(true);
    expect(built).toContain('search=BND-1');
    expect(built).toContain('state=draft');
    expect(built).toContain('work_center_id=4');
    expect(built).toContain('line_id=2');
    expect(built).toContain('limit=10');
    expect(buildBundlesKanbanPath({ search: '   ' })).toBe(BUNDLES_KANBAN_PATH);
  });
});

describe('FASE K3 - fetch & parse kanban bundle', () => {
  it('GET path kanban + parse kolom, kartu, transisi, filter', async () => {
    const { client, requests } = stubClient(PAYLOAD);

    const board = await fetchBundlesKanban(client, { state: 'DRAFT' });

    expect(requests[0]?.method).toBe('GET');
    expect(requests[0]?.path).toBe('/garmen/bundles/kanban/?state=DRAFT');
    expect(board.machine).toBe('garment.bundle');
    expect(board.columns.map((column) => column.state)).toEqual(['DRAFT', 'CUTTING']);
    expect(board.columns[0]?.cards[0]).toEqual({
      id: 11,
      code: 'BND-1',
      work_order_code: 'WO-1',
      size: 'L',
      qty: 5,
      state: 'DRAFT',
      allowed_actions: [
        {
          id: 'BUNDLE_START',
          label: 'Mulai Bundle',
          mode: 'optimistic',
          endpoint: '/garmen/bundles/11/BUNDLE_START/',
        },
      ],
    });
    expect(board.transitions[0]).toEqual({
      from: 'DRAFT',
      to: 'CUTTING',
      action_id: 'BUNDLE_START',
      label: 'Mulai Bundle',
    });
    expect(board.filters.applied).toEqual({ state: 'DRAFT' });
    expect(board.total_count).toBe(2);
  });

  it('bentuk asing ditolak (bukan crash) & default limit terisi', () => {
    expect(readKanbanResponse({})).toBeNull();
    expect(readKanbanResponse(null)).toBeNull();

    const parsed = readKanbanResponse({ columns: [] });
    expect(parsed?.columns).toEqual([]);
    expect(parsed?.limit).toBe(KANBAN_LIMIT_DEFAULT);
    expect(parsed?.unknown_states).toEqual({});
  });

  it('MODE.bundlesKanban `real` tanpa mengubah `bundles` (list F13)', () => {
    expect(MODE['bundlesKanban']).toBe('real');
    expect(isReal('bundlesKanban')).toBe(true);
    expect(MODE['bundles']).toBe('real');
  });
});
