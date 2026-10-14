// REAL - Inventory Adjustment (H2.5). Endpoint (`config/urls.py`, SEBELUM include industri):
//   POST `/inventory/adjust/`                       → create DRAFT (+`?commit=true`)
//   GET  `/inventory/adjustments/`                  → list audit (+filter & paging)
//   GET  `/inventory/adjustments/<id>/`             → detail (+blok `sync`)
//   POST `/inventory/adjustments/<id>/commit/`      → DRAFT → COMMITTED + push Odoo
//   GET  `/inventory/stock-qty/?product_id=&location_id=` → on-hand Odoo on-demand
//
// Bentuk baris = PERSIS `django_app/.../services/inventory_adjustment_services.py`
// (`adjustment_row`/`adjustment_detail_row`). CATATAN PENTING:
//   * MES **tidak menyimpan stok** ⇒ `qty_before`/`qty_after` = snapshot Odoo
//     (bisa `null` = tidak terbaca), dan `stock-qty` murni read-only;
//   * `qty_delta`/`qty_before`/`qty_after` dikirim backend sebagai **string desimal**;
//   * transaksi satu arah MES → Odoo: push hanya terjadi saat `COMMITTED`
//     (`DRAFT` = MES-only), hasil akhirnya `SYNCED`/`FAILED`.
import type { ApiClient } from '@/integrations/api-client';
import type {
  InventoryAdjustmentCommitResult,
  InventoryAdjustmentCreated,
  InventoryAdjustmentCreateInput,
  InventoryAdjustmentDetail,
  InventoryAdjustmentPage,
  InventoryAdjustmentRow,
  InventoryStockQty,
} from '@/types/inventory-adjustment';
import { unwrap } from '../client';
import {
  buildQueryPath,
  getParsed,
  isRecord,
  readBool,
  readListPage,
  readNullableNum,
  readNullableStr,
  readNum,
  readStr,
  type ListPage,
} from './_shape';

/** Path relatif terhadap `VITE_API_BASE_URL` (`…/api/v1`). */
export const INVENTORY_ADJUST_PATH = '/inventory/adjust/';
export const INVENTORY_ADJUSTMENTS_PATH = '/inventory/adjustments/';
export const INVENTORY_STOCK_QTY_PATH = '/inventory/stock-qty/';

/** Batas paging backend (`api/inventory_adjustments.py::DEFAULT_LIMIT`/`MAX_LIMIT`). */
export const INVENTORY_ADJUSTMENTS_LIMIT_DEFAULT = 50;
export const INVENTORY_ADJUSTMENTS_LIMIT_MAX = 200;

export type InventoryAdjustmentListPage = ListPage<InventoryAdjustmentRow>;

export interface InventoryAdjustmentsParams {
  search?: string | null;
  state?: string | null;
  product_id?: number | null;
  location_id?: number | null;
  limit?: number | null;
  offset?: number | null;
}

/** URL detail satu adjustment. */
export function adjustmentDetailPath(id: number): string {
  return `${INVENTORY_ADJUSTMENTS_PATH}${String(id)}/`;
}

/** URL commit satu adjustment. */
export function adjustmentCommitPath(id: number): string {
  return `${adjustmentDetailPath(id)}commit/`;
}

/** PURE — path + query `GET /inventory/adjustments/` (hanya param terisi dikirim). */
export function buildAdjustmentsPath(params: InventoryAdjustmentsParams = {}): string {
  return buildQueryPath(INVENTORY_ADJUSTMENTS_PATH, {
    search: params.search,
    state: params.state,
    product_id: params.product_id,
    location_id: params.location_id,
    limit: params.limit,
    offset: params.offset,
  });
}

/** PURE — path + query `GET /inventory/stock-qty/`. */
export function buildStockQtyPath(productId: number, locationId: number): string {
  return buildQueryPath(INVENTORY_STOCK_QTY_PATH, {
    product_id: productId,
    location_id: locationId,
  });
}

// ---------------------------------------------------------------------------
// Parser (PURE & defensif)
// ---------------------------------------------------------------------------
/** PURE — satu baris adjustment; `null` kalau `id` tidak valid (baris dibuang). */
export function readAdjustmentRow(raw: unknown): InventoryAdjustmentRow | null {
  if (!isRecord(raw)) return null;
  const id = readNullableNum(raw['id']);
  if (id === null) return null;

  return {
    id,
    code: readStr(raw['code']),
    product_id: readNum(raw['product_id']),
    product_code: readNullableStr(raw['product_code']),
    product_name: readNullableStr(raw['product_name']),
    location_id: readNum(raw['location_id']),
    location_code: readNullableStr(raw['location_code']),
    location_name: readNullableStr(raw['location_name']),
    location_usage: readNullableStr(raw['location_usage']),
    qty_delta: readStr(raw['qty_delta']),
    qty_before: readNullableStr(raw['qty_before']),
    qty_after: readNullableStr(raw['qty_after']),
    reason: readStr(raw['reason']),
    state: readStr(raw['state']) as InventoryAdjustmentRow['state'],
    odoo_move_id: readNullableNum(raw['odoo_move_id']),
    odoo_reference: readStr(raw['odoo_reference']),
    last_error: readStr(raw['last_error']),
    created_by: readNullableStr(raw['created_by']),
    created_at: readNullableStr(raw['created_at']),
    updated_at: readNullableStr(raw['updated_at']),
  };
}

/** PURE — detail (+blok `sync` ledger); `null` kalau bentuknya rusak. */
export function readAdjustmentDetail(raw: unknown): InventoryAdjustmentDetail | null {
  const row = readAdjustmentRow(raw);
  if (row === null || !isRecord(raw)) return null;

  const sync = isRecord(raw['sync']) ? raw['sync'] : {};

  return {
    ...row,
    sync: {
      record_id: readNullableNum(sync['record_id']),
      status: readNullableStr(sync['status']),
      erp_id: readNullableStr(sync['erp_id']),
      attempts: readNum(sync['attempts']),
    },
  };
}

/** PURE — respons create (`?commit=true` menambahkan blok `commit`). */
export function readAdjustmentCreated(raw: unknown): InventoryAdjustmentCreated | null {
  const detail = readAdjustmentDetail(raw);
  if (detail === null || !isRecord(raw)) return null;

  if (!isRecord(raw['commit'])) return detail;
  const commit = raw['commit'];

  return {
    ...detail,
    commit: {
      ok: readBool(commit['ok']),
      detail: readNullableStr(commit['detail']) ?? undefined,
      ledger_id: readNullableNum(commit['ledger_id']),
      task_id: readNullableStr(commit['task_id']),
      queued: readBool(commit['queued']),
    },
  };
}

/** PURE — respons commit (baris detail + `ledger_id`/`task_id`/`queued`). */
export function readAdjustmentCommitResult(
  raw: unknown,
): InventoryAdjustmentCommitResult | null {
  const detail = readAdjustmentDetail(raw);
  if (detail === null || !isRecord(raw)) return null;

  return {
    ...detail,
    ledger_id: readNullableNum(raw['ledger_id']),
    task_id: readNullableStr(raw['task_id']),
    queued: readBool(raw['queued']),
  };
}

/** PURE — respons `stock-qty` on-demand; `null` kalau bentuknya rusak. */
export function readStockQty(raw: unknown): InventoryStockQty | null {
  if (!isRecord(raw)) return null;
  const productId = readNullableNum(raw['product_id']);
  const locationId = readNullableNum(raw['location_id']);
  if (productId === null || locationId === null) return null;

  return {
    product_id: productId,
    product_code: readStr(raw['product_code']),
    product_odoo_id: readNullableNum(raw['product_odoo_id']),
    location_id: locationId,
    location_code: readStr(raw['location_code']),
    location_odoo_id: readNullableNum(raw['location_odoo_id']),
    qty: readNullableStr(raw['qty']),
    source: readStr(raw['source']),
    stock_owner: readStr(raw['stock_owner']),
  };
}

// ---------------------------------------------------------------------------
// Fetch
// ---------------------------------------------------------------------------
/** Daftar log adjustment + filter (audit trail). */
export async function fetchAdjustments(
  client: ApiClient,
  params: InventoryAdjustmentsParams = {},
): Promise<InventoryAdjustmentPage> {
  return getParsed(
    client,
    buildAdjustmentsPath(params),
    (raw) => readListPage(raw, readAdjustmentRow),
    'daftar inventory adjustment',
  );
}

/** Detail satu adjustment (+blok `sync`). */
export async function fetchAdjustment(
  client: ApiClient,
  id: number,
): Promise<InventoryAdjustmentDetail> {
  return getParsed(
    client,
    adjustmentDetailPath(id),
    readAdjustmentDetail,
    'detail inventory adjustment',
  );
}

/** Buat log adjustment; `commit=true` → langsung kirim ke Odoo (COMMITTED). */
export async function createAdjustment(
  client: ApiClient,
  input: InventoryAdjustmentCreateInput,
  options: { commit?: boolean; idempotencyKey?: string } = {},
): Promise<InventoryAdjustmentCreated> {
  const path =
    options.commit === true ? `${INVENTORY_ADJUST_PATH}?commit=true` : INVENTORY_ADJUST_PATH;
  const parsed = readAdjustmentCreated(
    unwrap(await client.post<unknown>(path, input, { idempotencyKey: options.idempotencyKey })),
  );
  if (parsed === null) {
    throw new Error('Bentuk respons create Inventory Adjustment tidak dikenali.');
  }

  return parsed;
}

/** Commit (kirim) adjustment ke Odoo: `DRAFT` → `COMMITTED` + enqueue push. */
export async function commitAdjustment(
  client: ApiClient,
  id: number,
): Promise<InventoryAdjustmentCommitResult> {
  const parsed = readAdjustmentCommitResult(
    unwrap(await client.post<unknown>(adjustmentCommitPath(id), {})),
  );
  if (parsed === null) {
    throw new Error('Bentuk respons commit Inventory Adjustment tidak dikenali.');
  }

  return parsed;
}

/** On-hand Odoo **on-demand** (read-only; MES tidak menyimpan stok). */
export async function fetchStockQty(
  client: ApiClient,
  productId: number,
  locationId: number,
): Promise<InventoryStockQty> {
  return getParsed(
    client,
    buildStockQtyPath(productId, locationId),
    readStockQty,
    'stok Odoo (on-demand)',
  );
}
