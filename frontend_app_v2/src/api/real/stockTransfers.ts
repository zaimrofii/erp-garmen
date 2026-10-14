// REAL - Stock Transfer (H2.6). Endpoint (`config/urls.py`, SEBELUM include industri):
//   POST `/inventory/transfer/`                     → create DRAFT (+`?commit=true`)
//   GET  `/inventory/transfers/`                    → list audit (+filter & paging)
//   GET  `/inventory/transfers/<id>/`               → detail (+blok `sync`)
//   POST `/inventory/transfers/<id>/commit/`        → DRAFT → COMMITTED + push Odoo
//
// Bentuk baris = PERSIS `django_app/.../services/stock_transfer_services.py`
// (`transfer_row`/`transfer_detail_row`). CATATAN PENTING:
//   * MES **tidak menyimpan stok** ⇒ `qty_before` hanya snapshot Odoo (boleh `null`),
//     dan tidak ada pull saldo;
//   * `qty`/`qty_before` dikirim backend sebagai **string desimal**;
//   * jalur Odoo = `stock.picking` internal + `button_validate()`; jejaknya
//     `odoo_picking_id`/`odoo_picking_name` (mis. `WH/INT/00003`).
import type { ApiClient } from '@/integrations/api-client';
import type {
  StockTransferCommitResult,
  StockTransferCreated,
  StockTransferCreateInput,
  StockTransferDetail,
  StockTransferPage,
  StockTransferRow,
} from '@/types/stock-transfer';
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
export const INVENTORY_TRANSFER_PATH = '/inventory/transfer/';
export const INVENTORY_TRANSFERS_PATH = '/inventory/transfers/';

/** Batas paging backend (`api/stock_transfers.py::DEFAULT_LIMIT`/`MAX_LIMIT`). */
export const STOCK_TRANSFERS_LIMIT_DEFAULT = 50;
export const STOCK_TRANSFERS_LIMIT_MAX = 200;

export type StockTransferListPage = ListPage<StockTransferRow>;

export interface StockTransfersParams {
  search?: string | null;
  state?: string | null;
  product_id?: number | null;
  from_location_id?: number | null;
  to_location_id?: number | null;
  limit?: number | null;
  offset?: number | null;
}

/** URL detail satu transfer. */
export function transferDetailPath(id: number): string {
  return `${INVENTORY_TRANSFERS_PATH}${String(id)}/`;
}

/** URL commit satu transfer. */
export function transferCommitPath(id: number): string {
  return `${transferDetailPath(id)}commit/`;
}

/** PURE — path + query `GET /inventory/transfers/` (hanya param terisi dikirim). */
export function buildTransfersPath(params: StockTransfersParams = {}): string {
  return buildQueryPath(INVENTORY_TRANSFERS_PATH, {
    search: params.search,
    state: params.state,
    product_id: params.product_id,
    from_location_id: params.from_location_id,
    to_location_id: params.to_location_id,
    limit: params.limit,
    offset: params.offset,
  });
}

// ---------------------------------------------------------------------------
// Parser (PURE & defensif)
// ---------------------------------------------------------------------------
/** PURE — satu baris transfer; `null` kalau `id` tidak valid (baris dibuang). */
export function readTransferRow(raw: unknown): StockTransferRow | null {
  if (!isRecord(raw)) return null;
  const id = readNullableNum(raw['id']);
  if (id === null) return null;

  return {
    id,
    code: readStr(raw['code']),
    product_id: readNum(raw['product_id']),
    product_code: readNullableStr(raw['product_code']),
    product_name: readNullableStr(raw['product_name']),
    from_location_id: readNum(raw['from_location_id']),
    from_location_code: readNullableStr(raw['from_location_code']),
    from_location_name: readNullableStr(raw['from_location_name']),
    to_location_id: readNum(raw['to_location_id']),
    to_location_code: readNullableStr(raw['to_location_code']),
    to_location_name: readNullableStr(raw['to_location_name']),
    qty: readStr(raw['qty']),
    qty_before: readNullableStr(raw['qty_before']),
    reason: readStr(raw['reason']),
    state: readStr(raw['state']) as StockTransferRow['state'],
    odoo_picking_id: readNullableNum(raw['odoo_picking_id']),
    odoo_picking_name: readStr(raw['odoo_picking_name']),
    last_error: readStr(raw['last_error']),
    created_by: readNullableStr(raw['created_by']),
    created_at: readNullableStr(raw['created_at']),
    updated_at: readNullableStr(raw['updated_at']),
  };
}

/** PURE — detail (+blok `sync` ledger); `null` kalau bentuknya rusak. */
export function readTransferDetail(raw: unknown): StockTransferDetail | null {
  const row = readTransferRow(raw);
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
export function readTransferCreated(raw: unknown): StockTransferCreated | null {
  const detail = readTransferDetail(raw);
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
export function readTransferCommitResult(raw: unknown): StockTransferCommitResult | null {
  const detail = readTransferDetail(raw);
  if (detail === null || !isRecord(raw)) return null;

  return {
    ...detail,
    ledger_id: readNullableNum(raw['ledger_id']),
    task_id: readNullableStr(raw['task_id']),
    queued: readBool(raw['queued']),
  };
}

// ---------------------------------------------------------------------------
// Fetch
// ---------------------------------------------------------------------------
/** Daftar log transfer + filter (audit trail). */
export async function fetchTransfers(
  client: ApiClient,
  params: StockTransfersParams = {},
): Promise<StockTransferPage> {
  return getParsed(
    client,
    buildTransfersPath(params),
    (raw) => readListPage(raw, readTransferRow),
    'daftar stock transfer',
  );
}

/** Detail satu transfer (+blok `sync`). */
export async function fetchTransfer(
  client: ApiClient,
  id: number,
): Promise<StockTransferDetail> {
  return getParsed(client, transferDetailPath(id), readTransferDetail, 'detail stock transfer');
}

/** Buat log transfer; `commit=true` → langsung kirim ke Odoo (COMMITTED). */
export async function createTransfer(
  client: ApiClient,
  input: StockTransferCreateInput,
  options: { commit?: boolean; idempotencyKey?: string } = {},
): Promise<StockTransferCreated> {
  const path =
    options.commit === true ? `${INVENTORY_TRANSFER_PATH}?commit=true` : INVENTORY_TRANSFER_PATH;
  const parsed = readTransferCreated(
    unwrap(await client.post<unknown>(path, input, { idempotencyKey: options.idempotencyKey })),
  );
  if (parsed === null) throw new Error('Bentuk respons create Stock Transfer tidak dikenali.');

  return parsed;
}

/** Commit (kirim) transfer ke Odoo: `DRAFT` → `COMMITTED` + enqueue push. */
export async function commitTransfer(
  client: ApiClient,
  id: number,
): Promise<StockTransferCommitResult> {
  const parsed = readTransferCommitResult(
    unwrap(await client.post<unknown>(transferCommitPath(id), {})),
  );
  if (parsed === null) throw new Error('Bentuk respons commit Stock Transfer tidak dikenali.');

  return parsed;
}
