// REAL - Bundle MES (H2.4). Endpoint: `/api/v1/garmen/bundles/…`
//   GET|POST `/garmen/bundles/`            +  POST `/garmen/bundles/preview/`
//   GET|PUT|DELETE `/<id>/`                +  POST `/<id>/split/` & `/<id>/merge/`
//
// Bentuk baris = PERSIS `django_app/apps_industry/garment/services/bundle_services.py`
// (`bundle_row`/`bundle_detail_row` superset). CATATAN PENTING:
//   * `GET /garmen/bundles/` barisnya tetap **9 key** kontrak F3 (di-pin
//     `apps_industry/garment/tests/test_list_endpoint.py:57`) — detail kaya
//     (order line, `events_count`, `ledger_status`) hanya di detail/create;
//   * Bundle = **MES-only sebagai objek** ⇒ tidak ada `odoo_id`/`task_id`/`queued`;
//     jejaknya `ledger_id` (SyncRecord `BUNDLE_PUSH` status `SKIPPED`);
//   * transisi state TETAP lewat `submitBundleAction` di `@/api/bundles` (aksi existing);
//   * `code` TIDAK bisa diubah; `DELETE` hanya untuk DRAFT tanpa jejak produksi (409 kalau ada).
import type { ApiClient } from '@/integrations/api-client';
import type {
  BundleCrudCreateInput,
  BundleCrudCreated,
  BundleCrudDetail,
  BundleCrudRow,
  BundleCrudSaved,
  BundleCrudUpdateInput,
  BundleMergeSaved,
  BundlePlanRow,
  BundlePreviewResult,
} from '@/types/bundle';
import { unwrap } from '../client';
import {
  buildQueryPath,
  getParsed,
  isRecord,
  readBool,
  readNullableNum,
  readNullableStr,
  readNum,
  readStr,
  type ListPage,
} from './_shape';

/** Path relatif terhadap `VITE_API_BASE_URL` (`…/api/v1`). */
export const BUNDLES_CRUD_PATH = '/garmen/bundles/';

/** Batas paging backend (`api/bundles.py::DEFAULT_LIMIT` / `MAX_LIMIT`). */
export const BUNDLES_CRUD_LIMIT_DEFAULT = 50;
export const BUNDLES_CRUD_LIMIT_MAX = 200;

/** Aksi state machine bundle (di-SEED `garment.bundle`; endpoint aksi existing). */
export const BUNDLE_STATE_ACTIONS = [
  'BUNDLE_START',
  'BUNDLE_ADVANCE',
  'BUNDLE_QC',
  'BUNDLE_FINISH',
  'BUNDLE_SCRAP',
] as const;

export type BundleStateAction = (typeof BUNDLE_STATE_ACTIONS)[number];

export type BundleCrudPage = ListPage<BundleCrudRow>;

export interface BundlesCrudParams {
  search?: string | null;
  state?: string | null;
  size?: string | null;
  work_order_id?: number | null;
  limit?: number | null;
  offset?: number | null;
}

/** URL detail/CRUD satu bundle. */
export function bundleCrudDetailPath(id: number): string {
  return `${BUNDLES_CRUD_PATH}${String(id)}/`;
}

/** URL split satu bundle. */
export function bundleCrudSplitPath(id: number): string {
  return `${BUNDLES_CRUD_PATH}${String(id)}/split/`;
}

/** URL merge ke satu bundle target. */
export function bundleCrudMergePath(id: number): string {
  return `${BUNDLES_CRUD_PATH}${String(id)}/merge/`;
}

/** URL preview rencana bundle (tanpa simpan). */
export function bundleCrudPreviewPath(): string {
  return `${BUNDLES_CRUD_PATH}preview/`;
}

/** PURE — path + query `GET /garmen/bundles/` (hanya param terisi dikirim). */
export function buildBundlesCrudPath(params: BundlesCrudParams = {}): string {
  return buildQueryPath(BUNDLES_CRUD_PATH, {
    search: params.search,
    state: params.state,
    size: params.size,
    work_order_id: params.work_order_id,
    limit: params.limit,
    offset: params.offset,
  });
}

// ---------------------------------------------------------------------------
// Parser (PURE & defensif)
// ---------------------------------------------------------------------------
/** PURE — `allowed_actions` mentah (string ATAU `{id,...}`) → daftar id aksi. */
function readActionNames(raw: unknown): string[] {
  const names: string[] = [];
  if (!Array.isArray(raw)) return names;

  for (const item of raw) {
    if (typeof item === 'string') names.push(item);
    else if (isRecord(item) && typeof item['id'] === 'string') names.push(item['id']);
  }

  return names;
}

/** PURE — baris list F3 (9 key) → tipe aman; `null` kalau `id` tidak valid. */
export function readBundleCrudListRow(raw: unknown): BundleCrudRow | null {
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
    version: readStr(raw['version']),
    current_work_center_code: readNullableStr(raw['current_work_center_code']),
    allowed_actions: readActionNames(raw['allowed_actions']),
    sku_variant: readStr(raw['sku_variant']),
    work_order_id: readNullableNum(raw['work_order_id']),
    work_order_code: readNullableStr(raw['work_order_code']),
    order_line_id: readNullableNum(raw['order_line_id']),
    order_code: readNullableStr(raw['order_code']),
    product_code: readNullableStr(raw['product_code']),
    current_work_center_id: readNullableNum(raw['current_work_center_id']),
    production_line_id: readNullableNum(raw['production_line_id']),
    production_line_code: readNullableStr(raw['production_line_code']),
    events_count: readNum(raw['events_count']),
    ledger_status: readStr(raw['ledger_status']),
    created_at: readNullableStr(raw['created_at']),
    updated_at: readNullableStr(raw['updated_at']),
  };
}

/** PURE — `rows[]` list → `ListPage` (bentuk rusak → `null` ⇒ pemanggil melempar). */
export function readBundlesCrudPage(raw: unknown): BundleCrudPage | null {
  if (!isRecord(raw)) return null;
  const rows = raw['rows'];
  if (!Array.isArray(rows)) return null;

  const parsed: BundleCrudRow[] = [];
  for (const row of rows) {
    const item = readBundleCrudListRow(row);
    if (item !== null) parsed.push(item);
  }

  return {
    rows: parsed,
    total_count: readNum(raw['total_count']),
    has_more: raw['has_more'] === true,
    next_cursor: typeof raw['next_cursor'] === 'number' ? raw['next_cursor'] : null,
  };
}

/** PURE — detail bundle (butuh `version`; `null` kalau bentuk rusak). */
export function readBundleCrudDetail(raw: unknown): BundleCrudDetail | null {
  const row = readBundleCrudListRow(raw);
  if (row === null || !isRecord(raw)) return null;
  if (typeof raw['version'] !== 'string' || raw['version'].length === 0) return null;

  return row;
}

/** PURE — hasil CUD → `BundleCrudSaved` (butuh `version` = detail). */
export function readBundleCrudSaved(raw: unknown): BundleCrudSaved | null {
  const detail = readBundleCrudDetail(raw);
  if (detail === null || !isRecord(raw)) return null;

  const child = Array.isArray(raw['bundles']) ? raw['bundles'] : [];
  const rows: BundleCrudRow[] = [];
  for (const item of child) {
    const parsed = readBundleCrudListRow(item);
    if (parsed !== null) rows.push(parsed);
  }

  const summary = isRecord(raw['summary']) ? (raw['summary'] as Record<string, unknown>) : undefined;

  return {
    ...detail,
    ledger_id: readNullableNum(raw['ledger_id']),
    deleted: readBool(raw['deleted']),
    bundles: rows,
    summary,
  };
}

/** PURE — hasil merge (detail + `summary.merged_ids`). */
export function readBundleMergeSaved(raw: unknown): BundleMergeSaved | null {
  const saved = readBundleCrudSaved(raw);
  if (saved === null || !isRecord(raw)) return null;

  const summary = isRecord(raw['summary']) ? raw['summary'] : {};
  const ids = Array.isArray(summary['merged_ids'])
    ? summary['merged_ids'].filter((item): item is number => typeof item === 'number')
    : [];

  return {
    ...saved,
    summary: {
      merged: readNum(summary['merged']),
      qty: readNum(summary['qty']),
      merged_ids: ids,
    },
  };
}

/** PURE — hasil preview (`plan[]` + `summary`). */
export function readBundlePreview(raw: unknown): BundlePreviewResult | null {
  if (!isRecord(raw)) return null;
  const plan = raw['plan'];
  if (!Array.isArray(plan)) return null;

  const rows: BundlePlanRow[] = [];
  for (const item of plan) {
    if (!isRecord(item)) continue;
    rows.push({
      code: readStr(item['code']),
      size: readStr(item['size']),
      sku_variant: readStr(item['sku_variant']),
      qty: readNum(item['qty']),
      work_order_id: readNum(item['work_order_id']),
    });
  }

  const summary = isRecord(raw['summary']) ? raw['summary'] : {};

  return {
    plan: rows,
    summary: {
      planned: readNum(summary['planned']),
      total_qty: readNum(summary['total_qty']),
    },
  };
}

// ---------------------------------------------------------------------------
// Panggilan HTTP (logic fetch tetap di `integrations/api-client`)
// ---------------------------------------------------------------------------
/** PURE — input create → body backend (`bundle_size` kosong ⇒ default backend 1). */
export function toBundleCreateBody(input: BundleCrudCreateInput): Record<string, unknown> {
  const body: Record<string, unknown> = {
    work_order_id: input.work_order_id,
    size_matrix: { ...input.size_matrix },
  };
  if (input.bundle_size !== null) body['bundle_size'] = input.bundle_size;
  const sku = input.sku_variant.trim();
  if (sku.length > 0) body['sku_variant'] = sku;

  return body;
}

/** PURE — input update → body backend (field kosong dikirim `null` bila bermakna). */
export function toBundleUpdateBody(input: BundleCrudUpdateInput): Record<string, unknown> {
  const body: Record<string, unknown> = {
    size: input.size.trim().toUpperCase(),
    sku_variant: input.sku_variant.trim(),
  };
  if (input.qty !== null) body['qty'] = input.qty;
  if (input.current_work_center_id !== null) {
    body['current_work_center_id'] = input.current_work_center_id;
  }
  if (input.production_line_id !== null) {
    body['production_line_id'] = input.production_line_id;
  }

  return body;
}

/** Daftar bundle (baris 9 key kontrak F3) + filter opsional. */
export async function fetchBundlesCrud(
  client: ApiClient,
  params: BundlesCrudParams = {},
): Promise<BundleCrudPage> {
  return getParsed(client, buildBundlesCrudPath(params), readBundlesCrudPage, 'daftar Bundle');
}

/** Detail bundle (H2.4 superset: WO/order line, `events_count`, `ledger_status`). */
export async function fetchBundleCrud(client: ApiClient, id: number): Promise<BundleCrudDetail> {
  return getParsed(client, bundleCrudDetailPath(id), readBundleCrudDetail, 'detail Bundle');
}

/** Rencana bundle TANPA menyimpan (form create). */
export async function previewBundles(
  client: ApiClient,
  input: BundleCrudCreateInput,
): Promise<BundlePreviewResult> {
  const parsed = readBundlePreview(
    unwrap(await client.post<unknown>(bundleCrudPreviewPath(), toBundleCreateBody(input))),
  );
  if (parsed === null) throw new Error('Bentuk respons preview Bundle tidak dikenali.');

  return parsed;
}

/** PURE — hasil create (`created` + `summary` + `bundles[]` di luar `bundle_row`). */
export function readBundleCrudCreated(raw: unknown): BundleCrudCreated | null {
  const saved = readBundleCrudSaved(raw);
  if (saved === null || !isRecord(raw)) return null;

  const summary = isRecord(raw['summary']) ? raw['summary'] : {};
  const created = readNullableNum(raw['created']);

  return {
    ...saved,
    created: created ?? saved.bundles?.length ?? 0,
    summary: {
      created: readNum(summary['created']),
      total_qty: readNum(summary['total_qty']),
    },
    bundles: saved.bundles ?? [],
  };
}

/** Buat bundle untuk satu WorkOrder (size matrix + bundle_size). */
export async function createBundles(
  client: ApiClient,
  input: BundleCrudCreateInput,
  idempotencyKey?: string,
): Promise<BundleCrudCreated> {
  const parsed = readBundleCrudCreated(
    unwrap(
      await client.post<unknown>(BUNDLES_CRUD_PATH, toBundleCreateBody(input), {
        idempotencyKey,
      }),
    ),
  );
  if (parsed === null) throw new Error('Bentuk respons create Bundle tidak dikenali.');

  return parsed;
}

/** Ubah bundle (DRAFT-only; sertakan `baseVersion` untuk optimistic lock). */
export async function updateBundle(
  client: ApiClient,
  id: number,
  input: BundleCrudUpdateInput,
  baseVersion?: string,
): Promise<BundleCrudSaved> {
  const parsed = readBundleCrudSaved(
    unwrap(
      await client.request<unknown>(bundleCrudDetailPath(id), {
        method: 'PUT',
        body: toBundleUpdateBody(input),
        baseVersion,
      }),
    ),
  );
  if (parsed === null) throw new Error('Bentuk respons update Bundle tidak dikenali.');

  return parsed;
}

/** Hapus bundle (hibrida: hanya DRAFT tanpa jejak produksi; selain itu 409). */
export async function deleteBundle(client: ApiClient, id: number): Promise<BundleCrudSaved | null> {
  const raw = unwrap(
    await client.request<unknown>(bundleCrudDetailPath(id), { method: 'DELETE' }),
  );

  return isRecord(raw) && raw['deleted'] === true && raw['id'] === undefined
    ? null
    : readBundleCrudSaved(raw);
}

/** Pecah satu bundle (`parts[]`; jumlah WAJIB = qty sumber). */
export async function splitBundle(
  client: ApiClient,
  id: number,
  parts: number[],
): Promise<BundleCrudSaved> {
  const parsed = readBundleCrudSaved(
    unwrap(await client.post<unknown>(bundleCrudSplitPath(id), { parts })),
  );
  if (parsed === null) throw new Error('Bentuk respons split Bundle tidak dikenali.');

  return parsed;
}

/** Gabungkan 2+ bundle DRAFT sejenis ke bundle target. */
export async function mergeBundles(
  client: ApiClient,
  id: number,
  bundleIds: number[],
): Promise<BundleMergeSaved> {
  const parsed = readBundleMergeSaved(
    unwrap(await client.post<unknown>(bundleCrudMergePath(id), { bundle_ids: bundleIds })),
  );
  if (parsed === null) throw new Error('Bentuk respons merge Bundle tidak dikenali.');

  return parsed;
}
