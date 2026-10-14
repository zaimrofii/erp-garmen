// REAL - Work Order MES (H2.3). Endpoint: `/api/v1/garmen/work-orders/…`
//   GET|POST `/garmen/work-orders/`        +  GET|PUT|DELETE `/<id>/`
//   POST     `/<id>/split/`                +  POST `/<id>/<WO_START|WO_CLOSE|WO_CANCEL>/`
//   POST     `/garmen/orders/<id>/generate-wo/`
//
// Bentuk baris = PERSIS `django_app/apps_industry/garment/services/work_order_services.py`
// (`wo_row`/`wo_detail_row`). CATATAN PENTING:
//   * `GET /garmen/work-orders/` (list F3) tetap **5 key** — endpoint itu di-pin
//     `apps_industry/garment/tests/test_list_endpoint.py:44` ⇒ barisnya tipis;
//     informasi kaya (order_line, bundles, allowed_actions) hanya di detail/split;
//   * Work Order = **MES-only** ⇒ tidak ada `odoo_id`/`task_id`/`queued`; jejaknya
//     `ledger_id` (SyncRecord `WORK_ORDER_PUSH` status `SKIPPED`);
//   * DELETE = **hibrida**: `DRAFT` tanpa bundle = hard delete (`deleted=true`),
//     selain itu soft delete (`cancelled=true` → `CANCELLED`), sudah `CANCELLED` = 409;
//   * `ApiClient` hanya punya `get`/`post` — PUT/DELETE lewat `client.request()`.
import type { ApiClient } from '@/integrations/api-client';
import type {
  WorkOrderBundleRow,
  WorkOrderCrudDetail,
  WorkOrderCrudInput,
  WorkOrderCrudListRow,
  WorkOrderCrudRow,
  WorkOrderCrudSaved,
  WorkOrderGenerateResult,
  WorkOrderSplitSaved,
} from '@/types/work-order';
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
export const WORK_ORDERS_CRUD_PATH = '/garmen/work-orders/';
/** Path batch generate WO dari Order (H2.1 orders + H2.3). */
export const ORDERS_GENERATE_WO_PATH = '/garmen/orders/';

/** Batas paging backend (`list_view.py::DEFAULT_LIMIT` / `MAX_LIMIT`). */
export const WORK_ORDERS_CRUD_LIMIT_DEFAULT = 50;
export const WORK_ORDERS_CRUD_LIMIT_MAX = 200;

/**
 * Aksi transisi state machine WO (di-SEED `garment.work_order`).
 * DRAFT → `WO_START`/`WO_CANCEL`, IN_PROGRESS → `WO_CLOSE`/`WO_CANCEL`.
 */
export const WORK_ORDER_ACTIONS = ['WO_START', 'WO_CLOSE', 'WO_CANCEL'] as const;

export type WorkOrderAction = (typeof WORK_ORDER_ACTIONS)[number];

export type WorkOrderCrudPage = ListPage<WorkOrderCrudListRow>;

export interface WorkOrdersCrudParams {
  limit?: number | null;
  offset?: number | null;
}

/** URL detail/CRUD satu WO. */
export function workOrderCrudDetailPath(id: number): string {
  return `${WORK_ORDERS_CRUD_PATH}${String(id)}/`;
}

/** URL split satu WO. */
export function workOrderCrudSplitPath(id: number): string {
  return `${WORK_ORDERS_CRUD_PATH}${String(id)}/split/`;
}

/** URL aksi state machine satu WO (`WO_START`/`WO_CLOSE`/`WO_CANCEL`). */
export function workOrderCrudActionPath(id: number, action: WorkOrderAction): string {
  return `${WORK_ORDERS_CRUD_PATH}${String(id)}/${action}/`;
}

/** URL batch generate WO dari Order. */
export function orderGenerateWoPath(orderId: number): string {
  return `${ORDERS_GENERATE_WO_PATH}${String(orderId)}/generate-wo/`;
}

/** PURE — path + query `GET /garmen/work-orders/` (hanya param terisi dikirim). */
export function buildWorkOrdersCrudPath(params: WorkOrdersCrudParams = {}): string {
  return buildQueryPath(WORK_ORDERS_CRUD_PATH, {
    limit: params.limit,
    offset: params.offset,
  });
}

/** PURE — satu baris list F3 (5 key) → tipe aman; `null` kalau `id` tidak valid. */
export function readWorkOrderCrudListRow(raw: unknown): WorkOrderCrudListRow | null {
  if (!isRecord(raw)) return null;

  const id = readNullableNum(raw['id']);
  if (id === null) return null;

  return {
    id,
    code: readStr(raw['code']),
    state: readStr(raw['state']),
    qty_planned: readNum(raw['qty_planned']),
    qty_done: readNum(raw['qty_done']),
  };
}

/** PURE — baris WO versi H2.3 (`wo_row`); `null` kalau `id` tidak valid. */
export function readWorkOrderCrudRow(raw: unknown): WorkOrderCrudRow | null {
  const base = readWorkOrderCrudListRow(raw);
  if (base === null || !isRecord(raw)) return null;

  const actions = raw['allowed_actions'];

  return {
    ...base,
    order_line_id: readNullableNum(raw['order_line_id']),
    order_id: readNullableNum(raw['order_id']),
    order_code: readNullableStr(raw['order_code']),
    product_id: readNullableNum(raw['product_id']),
    product_code: readNullableStr(raw['product_code']),
    bundles_count: readNum(raw['bundles_count']),
    allowed_actions: Array.isArray(actions) ? actions.filter((a) => typeof a === 'string') : [],
    created_at: readNullableStr(raw['created_at']),
    updated_at: readNullableStr(raw['updated_at']),
  };
}

/** PURE — satu bundle ringkas milik WO. */
function readWorkOrderBundleRow(raw: unknown): WorkOrderBundleRow | null {
  if (!isRecord(raw)) return null;

  const id = readNullableNum(raw['id']);
  if (id === null) return null;

  return {
    id,
    code: readStr(raw['code']),
    state: readStr(raw['state']),
    size: readStr(raw['size']),
    qty: readNum(raw['qty']),
    qty_done: readNum(raw['qty_done']),
  };
}

/** PURE — baris `rows[]` list → `ListPage` (bentuk rusak → melempar di pemanggil). */
export function readWorkOrdersCrudPage(raw: unknown): WorkOrderCrudPage | null {
  return readListPage(raw, readWorkOrderCrudListRow);
}

/** PURE — detail WO (`wo_detail_row` + `version` + `bundles[]`). */
export function readWorkOrderCrudDetail(raw: unknown): WorkOrderCrudDetail | null {
  const row = readWorkOrderCrudRow(raw);
  if (row === null || !isRecord(raw)) return null;

  const bundles = Array.isArray(raw['bundles']) ? raw['bundles'] : [];
  const parsedBundles: WorkOrderBundleRow[] = [];
  for (const bundle of bundles) {
    const item = readWorkOrderBundleRow(bundle);
    if (item !== null) parsedBundles.push(item);
  }

  return { ...row, bundles: parsedBundles, version: readStr(raw['version']) };
}

/** PURE — hasil CUD → `WorkOrderCrudSaved` (butuh `version`; `null` kalau bukan detail). */
export function readWorkOrderCrudSaved(raw: unknown): WorkOrderCrudSaved | null {
  const detail = readWorkOrderCrudDetail(raw);
  if (detail === null || !isRecord(raw)) return null;

  return {
    ...detail,
    ledger_id: readNullableNum(raw['ledger_id']),
    cancelled: readBool(raw['cancelled']),
    deleted: readBool(raw['deleted']),
  };
}

/** PURE — hasil split → `WorkOrderSplitSaved` (detail + `work_orders[]` + `summary`). */
export function readWorkOrderSplitSaved(raw: unknown): WorkOrderSplitSaved | null {
  const saved = readWorkOrderCrudSaved(raw);
  if (saved === null || !isRecord(raw)) return null;

  const created = Array.isArray(raw['work_orders']) ? raw['work_orders'] : [];
  const rows: WorkOrderCrudRow[] = [];
  for (const child of created) {
    const item = readWorkOrderCrudRow(child);
    if (item !== null) rows.push(item);
  }

  const summary = isRecord(raw['summary']) ? raw['summary'] : {};
  const parts = Array.isArray(summary['parts'])
    ? summary['parts'].filter((part): part is number => typeof part === 'number')
    : undefined;

  return {
    ...saved,
    work_orders: rows,
    summary: parts === undefined ? { created: readNum(summary['created']) } : {
      parts,
      created: readNum(summary['created']),
    },
  };
}

/** PURE — hasil batch generate WO dari Order. */
export function readWorkOrderGenerateResult(raw: unknown): WorkOrderGenerateResult | null {
  if (!isRecord(raw)) return null;

  const orderId = readNullableNum(raw['order_id']);
  if (orderId === null) return null;

  const created = Array.isArray(raw['work_orders']) ? raw['work_orders'] : [];
  const rows: WorkOrderCrudRow[] = [];
  for (const child of created) {
    const item = readWorkOrderCrudRow(child);
    if (item !== null) rows.push(item);
  }

  const summary = isRecord(raw['summary']) ? raw['summary'] : {};

  return {
    order_id: orderId,
    order_code: readStr(raw['order_code']),
    summary: {
      created: readNum(summary['created']),
      skipped: readNum(summary['skipped']),
    },
    work_orders: rows,
  };
}

// ---------------------------------------------------------------------------
// Panggilan HTTP (signature adapter; logic fetch tetap di `integrations/api-client`)
// ---------------------------------------------------------------------------
/** PURE — input UI → body backend (trim kode; `order_line_id`/`qty_planned` angka). */
export function toWorkOrderCrudBody(input: WorkOrderCrudInput): Record<string, unknown> {
  const body: Record<string, unknown> = {};

  if (input.order_line_id !== null) body['order_line_id'] = input.order_line_id;
  const code = input.code.trim();
  if (code.length > 0) body['code'] = code;
  if (input.qty_planned !== null) body['qty_planned'] = input.qty_planned;

  return body;
}

/** Daftar WO (list F3 5 key; `limit`/`offset`). Bentuk rusak / HTTP gagal → melempar. */
export async function fetchWorkOrdersCrud(
  client: ApiClient,
  params: WorkOrdersCrudParams = {},
): Promise<WorkOrderCrudPage> {
  return getParsed(
    client,
    buildWorkOrdersCrudPath(params),
    readWorkOrdersCrudPage,
    'daftar Work Order',
  );
}

/** Detail WO (H2.3 superset: order line, `bundles[]`, `allowed_actions`). */
export async function fetchWorkOrderCrud(
  client: ApiClient,
  id: number,
): Promise<WorkOrderCrudDetail> {
  return getParsed(
    client,
    workOrderCrudDetailPath(id),
    readWorkOrderCrudDetail,
    'detail Work Order',
  );
}

/** Buat WO — nomor `WO-<TAHUN>-<SEQ>` dibangkitkan backend bila `code` kosong. */
export async function createWorkOrderCrud(
  client: ApiClient,
  input: WorkOrderCrudInput,
): Promise<WorkOrderCrudSaved> {
  const parsed = readWorkOrderCrudSaved(
    unwrap(await client.post<unknown>(WORK_ORDERS_CRUD_PATH, toWorkOrderCrudBody(input))),
  );
  if (parsed === null) throw new Error('Bentuk respons create Work Order tidak dikenali.');

  return parsed;
}

/** Ubah WO (DRAFT-only; `state` lewat aksi existing). */
export async function updateWorkOrderCrud(
  client: ApiClient,
  id: number,
  input: WorkOrderCrudInput,
): Promise<WorkOrderCrudSaved> {
  const parsed = readWorkOrderCrudSaved(
    unwrap(
      await client.request<unknown>(workOrderCrudDetailPath(id), {
        method: 'PUT',
        body: toWorkOrderCrudBody(input),
      }),
    ),
  );
  if (parsed === null) throw new Error('Bentuk respons update Work Order tidak dikenali.');

  return parsed;
}

/** Hapus WO (hibrida: `deleted=true` hard delete / `cancelled=true` soft delete). */
export async function deleteWorkOrderCrud(
  client: ApiClient,
  id: number,
): Promise<WorkOrderCrudSaved | null> {
  const raw = unwrap(
    await client.request<unknown>(workOrderCrudDetailPath(id), { method: 'DELETE' }),
  );

  // Hard delete → `{deleted: true}` tanpa `version` (WO sudah tidak ada).
  return isRecord(raw) && raw['deleted'] === true && raw['id'] === undefined
    ? null
    : readWorkOrderCrudSaved(raw);
}

/** Pecah satu WO (`splits[]` qty; jumlah WAJIB sama dengan `qty_planned` sumber). */
export async function splitWorkOrderCrud(
  client: ApiClient,
  id: number,
  splits: number[],
): Promise<WorkOrderSplitSaved> {
  const parsed = readWorkOrderSplitSaved(
    unwrap(await client.post<unknown>(workOrderCrudSplitPath(id), { splits })),
  );
  if (parsed === null) throw new Error('Bentuk respons split Work Order tidak dikenali.');

  return parsed;
}

/** Jalankan aksi state machine WO (`WO_START`/`WO_CLOSE`/`WO_CANCEL`). */
export async function runWorkOrderCrudAction(
  client: ApiClient,
  id: number,
  action: WorkOrderAction,
): Promise<WorkOrderCrudDetail | null> {
  const raw = unwrap(await client.post<unknown>(workOrderCrudActionPath(id, action), {}));

  return readWorkOrderCrudDetail(raw);
}

/** Batch generate WO dari Order (idempoten: OrderLine yang sudah punya WO dilewati). */
export async function generateWorkOrdersForOrder(
  client: ApiClient,
  orderId: number,
): Promise<WorkOrderGenerateResult> {
  const parsed = readWorkOrderGenerateResult(
    unwrap(await client.post<unknown>(orderGenerateWoPath(orderId), {})),
  );
  if (parsed === null) throw new Error('Bentuk respons generate Work Order tidak dikenali.');

  return parsed;
}


