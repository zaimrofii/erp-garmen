// ADAPTER - satu-satunya pintu monitoring SyncRecord (F15, revive F10). TANPA logic domain.
//
// Halaman WAJIB mengimpor dari sini - JANGAN dari `./real/*` langsung.
// MODE `syncMonitor` === 'real': `GET /sync/records/` (Fase 4.4, IsAuthenticated).
import { pickAdapter } from './_adapter';
import * as real from './real/syncMonitor';

/** Daftar `SyncRecord` (filter opsional stage/status). */
export const getSyncRecords = pickAdapter('syncMonitor', real.getSyncRecords, real.getSyncRecords);

export {
  buildSyncRecordsPath,
  parseSyncStage,
  parseSyncStatus,
  readSyncRecordPage,
  readSyncRecordRow,
  SYNC_CURSOR_MAX,
  SYNC_LIMIT_DEFAULT,
  SYNC_LIMIT_MAX,
  SYNC_LIMIT_MIN,
  SYNC_RECORDS_PATH,
  SYNC_STAGES,
  SYNC_STATUSES,
} from './real/syncMonitor';
export type { SyncRecordPage, SyncRecordRow, SyncStage, SyncStatus } from './real/syncMonitor';
export { parseIntParam } from './real/invoice';
