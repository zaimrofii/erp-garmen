import type { AllowedAction } from '@/lib/schemas/action.schema';

/**
 * order-line.ts - tipe resource `order-lines` (kontrak backend v4.3 §4.2).
 *
 * F1 (D7): metadata & list backend mengenal resource **`order-lines`** (bukan `orders`).
 * Path list/detail: `GET /garmen/order-lines/` dan `GET /garmen/order-lines/{id}/`.
 *
 * PENGECUALIAN: material readiness TETAP di `/garmen/orders/{id}/readiness/` karena `{id}`
 * di situ adalah **id Order**, bukan id OrderLine (kontrak §5.4/§5.5). Helper path-nya ada
 * di `api/real/orderLines.ts` (`buildOrderReadinessPath`) - jangan "seragamkan" ke
 * `order-lines`.
 */

export interface OrderLineRow {
  id: number;
  order_id: number;
  order_code: string;
  product_code: string;
  qty: number;
  /** Label produksi (`custom` | `brand`); `null` kalau order belum menetapkannya. */
  tag: string | null;
  ticket_code: string | null;
  version: string;
}

export interface OrderLineDetail extends OrderLineRow {
  work_order_ids: number[];
  updated_at: string;
  allowed_actions: AllowedAction[];
}
