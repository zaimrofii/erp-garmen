// REAL - wrap integration engine v1 (api-client). Endpoint: GET /garmen/order-lines/, GET /garmen/order-lines/{id}/
//
// Logic fetch TIDAK ditulis ulang di sini: semua lewat `integrations/api-client.ts`
// (satu-satunya pintu keluar HTTP - sabuk pengaman #1). Yang ditambahkan hanya signature
// adapter + konstanta path.
//
// F1 (D7): resource metadata/list backend = `order-lines` (kontrak v4.3 §3.2/§4.1).
// Path `/garmen/orders/` HANYA dipakai material readiness (id ORDER, bukan OrderLine).
import type { ApiClient } from '@/integrations/api-client';
import type { ListPage } from '@/lib/schemas/list.schema';
import type { OrderLineDetail } from '@/types/order-line';
import { unwrap } from '../client';

/** Path relatif terhadap `VITE_API_BASE_URL` — resource kanonik (D7). */
export const ORDER_LINES_PATH = '/garmen/order-lines/';

/**
 * PENGECUALIAN KONTRAK (D7) — material readiness memakai `orders` (id Order, §5.4/§5.5),
 * jadi path ini SENGAJA tetap `/garmen/orders/`; jangan diganti `order-lines`.
 */
export const ORDER_READINESS_PATH = '/garmen/orders/';

/** PURE — path readiness satu Order: `/garmen/orders/{id}/readiness/`. */
export function buildOrderReadinessPath(orderId: number | string): string {
  return `${ORDER_READINESS_PATH}${orderId}/readiness/`;
}

export async function getOrderLines(
  client: ApiClient,
  params: { limit?: number; offset?: number } = {},
): Promise<ListPage> {
  const qs = new URLSearchParams();
  if (params.limit != null) qs.set('limit', String(params.limit));
  if (params.offset != null) qs.set('offset', String(params.offset));
  const suffix = qs.toString() ? `?${qs}` : '';

  const res = await client.get<ListPage>(`${ORDER_LINES_PATH}${suffix}`);
  return unwrap(res);
}

export async function getOrderLine(
  client: ApiClient,
  id: number | string,
): Promise<OrderLineDetail> {
  const res = await client.get<OrderLineDetail>(`${ORDER_LINES_PATH}${id}/`);
  return unwrap(res);
}

export type { OrderLineRow, OrderLineDetail } from '@/types/order-line';
