// REAL - operasi inventory (F2C.2). Endpoint: GET /api/v1/inventory/operations/
//
// Backend `monitoring.InventoryOperationsView` (B8). ListPage.
// CATATAN: ini MONITOR sync stok (bukan master operasi gudang) — `product_code`
// dan `qty` BISA `null`.
import type { ApiClient } from '@/integrations/api-client';
import { unwrap } from '../client';

/** Path relatif terhadap `VITE_API_BASE_URL`. */
export const INVENTORY_OPERATIONS_PATH = '/inventory/operations/';

export interface OperationRow {
  /** `WIP_ISSUE` | `FG_RECEIPT` | `SCRAP` | `INVOICE`. */
  type: string;
  ref: string;
  product_code: string | null;
  qty: number | null;
  status: string;
  at: string | null;
}

export interface OperationPage {
  rows: OperationRow[];
  total_count: number;
  has_more: boolean;
  next_cursor: number | null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function readNum(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0;
}

function readStr(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

function readNullableNum(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function readNullableStr(value: unknown): string | null {
  return typeof value === 'string' ? value : null;
}

/** PURE — satu baris operasi mentah → `OperationRow`. */
export function readOperationRow(raw: unknown): OperationRow | null {
  if (!isRecord(raw)) return null;
  return {
    type: readStr(raw['type']),
    ref: readStr(raw['ref']),
    product_code: readNullableStr(raw['product_code']),
    qty: readNullableNum(raw['qty']),
    status: readStr(raw['status']),
    at: readNullableStr(raw['at']),
  };
}

/** PURE — respons mentah → `OperationPage`; `null` kalau `rows` bukan array. */
export function readOperationPage(raw: unknown): OperationPage | null {
  if (!isRecord(raw)) return null;
  const rows = raw['rows'];
  if (!Array.isArray(rows)) return null;

  const parsed: OperationRow[] = [];
  for (const row of rows) {
    const item = readOperationRow(row);
    if (item !== null) parsed.push(item);
  }

  return {
    rows: parsed,
    total_count: readNum(raw['total_count']),
    has_more: raw['has_more'] === true,
    next_cursor: typeof raw['next_cursor'] === 'number' ? raw['next_cursor'] : null,
  };
}

/** PURE — path + query `GET /inventory/operations/`. */
export function buildInventoryOperationsPath(
  params: { limit?: number | null; cursor?: number | null; stage?: string | null } = {},
): string {
  const qs = new URLSearchParams();
  if (params.limit != null) qs.set('limit', String(params.limit));
  if (params.cursor != null && params.cursor > 0) qs.set('cursor', String(params.cursor));
  const stage = params.stage?.trim();
  if (stage) qs.set('stage', stage);
  const suffix = qs.toString();
  return suffix.length === 0
    ? INVENTORY_OPERATIONS_PATH
    : `${INVENTORY_OPERATIONS_PATH}?${suffix}`;
}

/** Baca daftar operasi (rows saja). Gagal HTTP → melempar (`unwrap`). */
export async function fetchOperations(
  client: ApiClient,
  params: { limit?: number | null; cursor?: number | null; stage?: string | null } = {},
): Promise<OperationRow[]> {
  const res = await client.get<unknown>(buildInventoryOperationsPath(params));
  const page = readOperationPage(unwrap(res));

  if (page === null) {
    throw new Error('Bentuk respons daftar operasi tidak dikenali.');
  }

  return page.rows;
}
