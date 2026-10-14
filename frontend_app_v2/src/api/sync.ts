// ADAPTER - satu-satunya pintu sync ERP (TANPA logic domain).
//
// Halaman/utility WAJIB mengimpor dari sini - JANGAN dari `./real/*` langsung.
//
// F2/2.9 - MODE `syncOdoo` / `syncMaster` / `syncScrap` === 'real': endpoint SUDAH ADA
// (kontrak §5, `integrations/erp_sync/api.py`) dan semuanya `IsAuthenticated` (anon 403).
// Belum ada versi dummy, jadi slot dummy diisi implementasi real (pola `api/devices.ts`);
// `MODE` tetap satu-satunya saklar.
import { pickAdapter } from './_adapter';
import * as real from './real/sync';

/** `POST /sync/odoo/{WIP|FG}/` - two-stage sync stok (async Celery). */
export const postSyncOdoo = pickAdapter('syncOdoo', real.postSyncOdoo, real.postSyncOdoo);

/** `POST /sync/master/{entity}/` - sync master data per entity (async Celery). */
export const postSyncMaster = pickAdapter('syncMaster', real.postSyncMaster, real.postSyncMaster);

/** `POST /sync/scrap/` - sync scrap manual (SINKRON, efek samping tulis ke Odoo). */
export const postSyncScrap = pickAdapter('syncScrap', real.postSyncScrap, real.postSyncScrap);

export {
  SYNC_MASTER_ENTITIES,
  SYNC_MASTER_PATH,
  SYNC_ODOO_PATH,
  SYNC_SCRAP_PATH,
  SYNC_STAGES,
  SYNC_STAGE_RESOURCES,
} from './real/sync';
export type {
  SyncMasterEntity,
  SyncMasterQueuedResponse,
  SyncQueuedResponse,
  SyncScrapResponse,
  SyncStage,
  SyncStageInput,
  SyncStageResource,
} from './real/sync';
