import { describe, expect, it } from 'vitest';
import {
  buildOrderReadinessPath,
  getOrderLine,
  getOrderLines,
  ORDER_LINES_PATH,
  ORDER_READINESS_PATH,
} from '@/api/orderLines';
import type { ApiClient, ApiResponse } from '@/integrations/api-client';
import type { ListPage } from '@/lib/schemas/list.schema';
import type { OrderLineDetail } from '@/types/order-line';

/** F1 — D7: resource `order-lines` (bukan `orders`) + pengecualian readiness. */

const EMPTY_PAGE: ListPage = { rows: [], total_count: 0, has_more: false, next_cursor: null };

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

describe('D7 — adapter order-lines', () => {
  it('path list/detail = /garmen/order-lines/ (BUKAN /garmen/orders/)', () => {
    expect(ORDER_LINES_PATH).toBe('/garmen/order-lines/');
  });

  it('getOrderLines memakai limit/offset di path order-lines', async () => {
    const { client, paths } = stubClient(EMPTY_PAGE);

    const page = await getOrderLines(client, { limit: 2, offset: 1 });

    expect(paths).toEqual(['/garmen/order-lines/?limit=2&offset=1']);
    expect(page).toEqual(EMPTY_PAGE);
  });

  it('getOrderLine detail memakai id OrderLine', async () => {
    const { client, paths } = stubClient(EMPTY_PAGE);

    await getOrderLine(client, 7);

    expect(paths).toEqual(['/garmen/order-lines/7/']);
  });

  it('material readiness TETAP /garmen/orders/{id}/readiness/ (id ORDER)', () => {
    expect(ORDER_READINESS_PATH).toBe('/garmen/orders/');
    expect(buildOrderReadinessPath(16)).toBe('/garmen/orders/16/readiness/');
  });

  it('tipe OrderLineDetail sesuai kontrak §4.2 (snake_case)', () => {
    const detail: OrderLineDetail = {
      id: 1,
      order_id: 1,
      order_code: 'ORD-DEMO-001',
      product_code: 'TS-DEMO-001',
      qty: 20,
      tag: 'custom',
      ticket_code: 'TKT-001',
      version: 'd5e6',
      work_order_ids: [1],
      updated_at: '2026-10-08T10:00:00Z',
      allowed_actions: [],
    };

    expect(detail.order_code).toBe('ORD-DEMO-001');
    expect(detail.work_order_ids).toEqual([1]);
    expect(detail).not.toHaveProperty('state');
  });
});
