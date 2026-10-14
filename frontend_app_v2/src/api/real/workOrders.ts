// REAL - wrap integration engine v2 (api-client). Endpoint: GET /garmen/work-orders/
//
// Logic fetch tetap di `integrations/api-client.ts`; file ini hanya signature adapter.
import type { ApiClient } from '@/integrations/api-client';
import type { ListPage } from '@/lib/schemas/list.schema';
import type { WorkOrderDetail } from '@/types/work-order';
import { unwrap } from '../client';

/** Path relatif terhadap `VITE_API_BASE_URL`. */
export const WORK_ORDERS_PATH = '/garmen/work-orders/';

export async function getWorkOrders(
  client: ApiClient,
  params: { limit?: number; offset?: number } = {},
): Promise<ListPage> {
  const qs = new URLSearchParams();
  if (params.limit != null) qs.set('limit', String(params.limit));
  if (params.offset != null) qs.set('offset', String(params.offset));
  const suffix = qs.toString() ? `?${qs}` : '';
  const res = await client.get<ListPage>(`${WORK_ORDERS_PATH}${suffix}`);
  return unwrap(res);
}

export async function getWorkOrder(
  client: ApiClient,
  id: number | string,
): Promise<WorkOrderDetail> {
  const res = await client.get<WorkOrderDetail>(`${WORK_ORDERS_PATH}${id}/`);
  return unwrap(res);
}

export type { WorkOrderRow, WorkOrderDetail } from '@/types/work-order';
