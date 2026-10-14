// REAL - wrap integration engine v1 (api-client). Endpoint sync ERP (kontrak §5):
//   POST /sync/odoo/{WIP|FG}/    -> {ok,status,task_id,sync_record_id,stage,resource,resource_id}
//   POST /sync/master/{entity}/  -> {status,task_id}
//   POST /sync/scrap/            -> {sent,failed,skipped}
//
// F2/2.9 - adapter BARU (endpoint sudah ADA di backend, adapter belum ada).
// Semua endpoint `IsAuthenticated` -> api-client mengirim cookie + `X-CSRFToken`
// (F1.5 CORS credentials + F1.6 guard).
import type { ApiClient } from '@/integrations/api-client';
import { unwrap } from '../client';

/** Path relatif terhadap `VITE_API_BASE_URL`. */
export const SYNC_ODOO_PATH = '/sync/odoo/';
export const SYNC_MASTER_PATH = '/sync/master/';
export const SYNC_SCRAP_PATH = '/sync/scrap/';

/** Stage two-stage sync (§5.1): `WIP` = issue bahan, `FG` = receipt barang jadi. */
export const SYNC_STAGES = ['WIP', 'FG'] as const;
export type SyncStage = (typeof SYNC_STAGES)[number];

/** Resource yang boleh lewat two-stage (backend `STAGE_RESOURCES`). */
export const SYNC_STAGE_RESOURCES = ['bundle', 'work_order'] as const;
export type SyncStageResource = (typeof SYNC_STAGE_RESOURCES)[number];

/**
 * Entity master valid — **bentuk PLURAL**, diambil dari `MASTER_TASKS`
 * (`integrations/erp_sync/api.py`). Catatan: `docs/api-contract.md` §5.2 menulis bentuk
 * tunggal (`product`, `uom`, …) = USANG; backend membalas **404** untuk bentuk tunggal.
 */
export const SYNC_MASTER_ENTITIES = [
  'products',
  'boms',
  'partners',
  'locations',
  'taxes',
  'uoms',
  'warehouses',
  'journals',
  'currencies',
] as const;
export type SyncMasterEntity = (typeof SYNC_MASTER_ENTITIES)[number];

/** Body `POST /sync/odoo/{stage}/` (§5.1). */
export interface SyncStageInput {
  resource: SyncStageResource;
  resource_id: string;
  payload: Record<string, unknown>;
}

/** Respons 200 `POST /sync/odoo/{stage}/` (200 juga dipakai saat replay idempoten). */
export interface SyncQueuedResponse {
  ok: boolean;
  status: string;
  task_id: string;
  sync_record_id: number;
  stage: string;
  resource: string;
  resource_id: string;
}

/** Respons 200 `POST /sync/master/{entity}/`. */
export interface SyncMasterQueuedResponse {
  status: string;
  task_id: string;
}

/** Respons 200 `POST /sync/scrap/` (sinkron — bukan Celery). */
export interface SyncScrapResponse {
  sent: number;
  failed: number;
  skipped: number;
}

/** Trigger two-stage sync stok (WIP/FG). Gagal HTTP -> melempar Error (`unwrap`). */
export async function postSyncOdoo(
  client: ApiClient,
  stage: SyncStage,
  input: SyncStageInput,
): Promise<SyncQueuedResponse> {
  const res = await client.post<SyncQueuedResponse>(`${SYNC_ODOO_PATH}${stage}/`, input);
  return unwrap(res);
}

/** Trigger sync master data satu entity. Gagal HTTP -> melempar Error (`unwrap`). */
export async function postSyncMaster(
  client: ApiClient,
  entity: SyncMasterEntity,
): Promise<SyncMasterQueuedResponse> {
  const res = await client.post<SyncMasterQueuedResponse>(`${SYNC_MASTER_PATH}${entity}/`, {});
  return unwrap(res);
}

/**
 * Trigger sync scrap manual (sinkron). **Efek samping ERP**: mengirim semua
 * ScrapAccumulator `qty > 0` yang belum SENT ke Odoo — panggil hanya dari aksi
 * operator/supervisor yang disengaja (bukan saat render).
 */
export async function postSyncScrap(client: ApiClient): Promise<SyncScrapResponse> {
  const res = await client.post<SyncScrapResponse>(SYNC_SCRAP_PATH, {});
  return unwrap(res);
}
