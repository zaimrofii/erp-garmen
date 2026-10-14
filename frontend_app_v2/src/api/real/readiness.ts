// REAL - wrap integration engine v1 (api-client). Endpoint: GET /garmen/orders/{id}/readiness/
//
// F2/2.9b - adapter BARU. PENGECUALIAN KONTRAK (F1/D7): path memakai `orders`
// (id **ORDER**, bukan OrderLine) -> helper `buildOrderReadinessPath` dari
// `api/real/orderLines.ts` (satu sumber path, jangan disalin).
//
// `IsAuthenticated` (kontrak §5.4) -> api-client mengirim cookie + `X-CSRFToken`
// (F1.5 CORS credentials + F1.6 guard). Order tidak ada -> **404** (`unwrap` melempar).
import type { ApiClient } from '@/integrations/api-client';
import { unwrap } from '../client';
import { buildOrderReadinessPath, ORDER_READINESS_PATH } from './orderLines';

/** Status kesiapan material satu OrderLine (§5.4). */
export const READINESS_STATUSES = ['WAITING', 'PARTIAL', 'READY'] as const;
export type ReadinessStatus = (typeof READINESS_STATUSES)[number];

/** Satu baris readiness (OrderLine yang belum dihitung tetap muncul dengan nilai `null`). */
export interface OrderReadinessLine {
  order_line_id: number;
  product_code: string | null;
  required_qty: number | null;
  received_qty: number | null;
  shortage_qty: number | null;
  /** `WAITING` | `PARTIAL` | `READY`, atau `null` kalau belum pernah dihitung. */
  status: ReadinessStatus | string | null;
  expected_date: string | null;
  last_computed_at: string | null;
  vendor_bill_status: string | null;
  vendor_bill_ids: number[] | null;
  vendor_bill_amount: number | null;
}

/** Respons 200 `GET /garmen/orders/{id}/readiness/`. */
export interface OrderReadiness {
  order_id: number;
  lines: OrderReadinessLine[];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function readNullableNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function readNullableString(value: unknown): string | null {
  return typeof value === 'string' ? value : null;
}

function readNullableNumberList(value: unknown): number[] | null {
  if (!Array.isArray(value)) return null;

  const numbers = value.filter((item): item is number => typeof item === 'number');

  return numbers.length === value.length ? numbers : null;
}

/** PURE - satu baris readiness mentah -> `OrderReadinessLine`; `null` kalau tanpa `order_line_id`. */
export function readReadinessLine(raw: unknown): OrderReadinessLine | null {
  if (!isRecord(raw)) return null;

  const orderLineId = raw['order_line_id'];
  if (typeof orderLineId !== 'number' || !Number.isFinite(orderLineId)) return null;

  return {
    order_line_id: orderLineId,
    product_code: readNullableString(raw['product_code']),
    required_qty: readNullableNumber(raw['required_qty']),
    received_qty: readNullableNumber(raw['received_qty']),
    shortage_qty: readNullableNumber(raw['shortage_qty']),
    status: readNullableString(raw['status']),
    expected_date: readNullableString(raw['expected_date']),
    last_computed_at: readNullableString(raw['last_computed_at']),
    vendor_bill_status: readNullableString(raw['vendor_bill_status']),
    vendor_bill_ids: readNullableNumberList(raw['vendor_bill_ids']),
    vendor_bill_amount: readNullableNumber(raw['vendor_bill_amount']),
  };
}

/**
 * PURE - respons mentah -> `OrderReadiness`. `null` kalau envelope tidak dikenali
 * (`order_id` bukan angka / `lines` bukan array) supaya pemanggil bisa membedakan
 * "bentuk salah" dari "kosong".
 */
export function readOrderReadiness(raw: unknown): OrderReadiness | null {
  if (!isRecord(raw)) return null;

  const orderId = raw['order_id'];
  const lines = raw['lines'];
  if (typeof orderId !== 'number' || !Number.isFinite(orderId)) return null;
  if (!Array.isArray(lines)) return null;

  const parsed: OrderReadinessLine[] = [];
  for (const line of lines) {
    const row = readReadinessLine(line);
    if (row !== null) parsed.push(row);
  }

  return { order_id: orderId, lines: parsed };
}

/**
 * Baca kesiapan material satu Order. Gagal HTTP -> melempar Error (`unwrap`);
 * bentuk respons tak dikenal -> melempar Error dengan pesan yang bisa ditampilkan.
 */
export async function getOrderReadiness(
  client: ApiClient,
  orderId: number | string,
): Promise<OrderReadiness> {
  const res = await client.get<unknown>(buildOrderReadinessPath(orderId));
  const parsed = readOrderReadiness(unwrap(res));

  if (parsed === null) {
    throw new Error(`Bentuk respons readiness Order ${String(orderId)} tidak dikenali.`);
  }

  return parsed;
}

/* --------------------------------------------------------------------------
   F8 — recompute manual (kontrak §5.5). Path memakai `orders/{orderId}` juga.
   -------------------------------------------------------------------------- */

/** Path `POST /garmen/orders/{id}/recompute-readiness/`. */
export function buildOrderRecomputePath(orderId: number | string): string {
  return `${ORDER_READINESS_PATH}${orderId}/recompute-readiness/`;
}

/**
 * Counter hasil recompute. Backend (`MaterialReadinessService.compute_batch`) mengembalikan
 * `{processed, waiting, partial, ready, errors}` — docs §5.5 menulis `{ok, queued}`
 * (usang); keduanya diterima di sini (`queued` = `processed` bila tidak ada).
 */
export interface RecomputeReadinessResult {
  ok: boolean;
  queued: number;
  processed: number;
  waiting: number;
  partial: number;
  ready: number;
  errors: number;
}

function readCount(record: Record<string, unknown>, key: string): number {
  const value = record[key];

  return typeof value === 'number' && Number.isFinite(value) ? value : 0;
}

/** PURE — respons recompute mentah → counter; `null` kalau bentuknya tidak dikenali. */
export function readRecomputeResult(raw: unknown): RecomputeReadinessResult | null {
  if (!isRecord(raw)) return null;
  if (!('processed' in raw) && !('queued' in raw)) return null;

  const processed = readCount(raw, 'processed');
  const queued = readCount(raw, 'queued');

  return {
    ok: true,
    queued: queued > 0 ? queued : processed,
    processed,
    waiting: readCount(raw, 'waiting'),
    partial: readCount(raw, 'partial'),
    ready: readCount(raw, 'ready'),
    errors: readCount(raw, 'errors'),
  };
}

/**
 * Hitung ulang readiness satu Order (memanggil Odoo lewat service backend → efek nyata).
 * Gagal HTTP → melempar pesan backend (`unwrap`); bentuk tak dikenal → melempar pesan jelas.
 */
export async function postRecomputeReadiness(
  client: ApiClient,
  orderId: number | string,
): Promise<RecomputeReadinessResult> {
  const res = await client.post<unknown>(buildOrderRecomputePath(orderId), {});
  const parsed = readRecomputeResult(unwrap(res));

  if (parsed === null) {
    throw new Error(`Bentuk respons recompute Order ${String(orderId)} tidak dikenali.`);
  }

  return parsed;
}
