import { describe, expect, it } from 'vitest';
import {
  buildInventoryOperationsPath,
  fetchOperations,
  INVENTORY_OPERATIONS_PATH,
  readOperationPage,
  readOperationRow,
} from '@/api/inventory';
import { MODE } from '@/api/_adapter';
import type { ApiClient, ApiResponse } from '@/integrations/api-client';

/** F2C.2 — inventoryOperations REAL (`GET /api/v1/inventory/operations/`, B8). */

const LIVE_BODY = {
  rows: [
    { type: 'WIP_ISSUE', ref: 'WIP/2026/0001', product_code: 'TS-001', qty: 10, status: 'DONE', at: '2026-10-01T08:00:00Z' },
    { type: 'SCRAP', ref: 'SCR/2026/0001', product_code: null, qty: null, status: 'PENDING', at: null },
  ],
  total_count: 2,
  has_more: false,
  next_cursor: null,
};

function stubClient(data: unknown): { client: ApiClient; paths: string[] } {
  const paths: string[] = [];
  const client = {
    get: async <T,>(path: string): Promise<ApiResponse<T>> => {
      paths.push(path);
      return { ok: true, status: 200, data: data as T };
    },
  } as unknown as ApiClient;

  return { client, paths };
}

describe('F2C.2 — inventoryOperations', () => {
  it('MODE inventoryOperations = real; path + query stage', async () => {
    expect(MODE['inventoryOperations']).toBe('real');
    expect(INVENTORY_OPERATIONS_PATH).toBe('/inventory/operations/');
    expect(buildInventoryOperationsPath({ stage: 'SCRAP' })).toBe(
      '/inventory/operations/?stage=SCRAP',
    );

    const { client, paths } = stubClient(LIVE_BODY);

    await fetchOperations(client);

    expect(paths).toEqual(['/inventory/operations/']);
  });

  it('readOperationPage mempertahankan qty/product_code null', () => {
    const page = readOperationPage(LIVE_BODY);

    expect(page?.rows).toHaveLength(2);
    expect(page?.rows[0]?.product_code).toBe('TS-001');
    expect(page?.rows[1]?.product_code).toBeNull();
    expect(page?.rows[1]?.qty).toBeNull();
    expect(readOperationRow(LIVE_BODY.rows[1])?.at).toBeNull();
    expect(readOperationPage({ rows: 'x' })).toBeNull();
  });
});
