// ADAPTER - satu-satunya pintu data WA Gateway Config (H5.8, TANPA logic domain).
//
// H5.8: endpoint `/api/v1/settings/wa/` SUDAH ADA di backend →
// MODE.waConfig = 'real' (`_adapter.ts`), jadi tidak ada implementasi dummy.
//
// **SINGLETON + Opsi B**: DB menyimpan *profil gateway*; konsumen (`get_wa_gateway`,
// `tasks_reconciliation`, `ai/hitl_views`) tetap membaca `.env`. GET mengembalikan
// `config` + `effective` + `diverges` + `needs_restart` + `restart_command`.
import { pickAdapter } from './_adapter';
import * as real from './real/waConfig';

/** Profil + effective + divergences (`GET /settings/wa/`) — REAL (H5.8). */
export const fetchWAConfig = pickAdapter('waConfig', real.fetchWAConfig, real.fetchWAConfig);

/** Simpan profil gateway (`PUT /settings/wa/`) — REAL (H5.8; izin admin/owner). */
export const updateWAConfig = pickAdapter('waConfig', real.updateWAConfig, real.updateWAConfig);

/** Uji gateway WA (`POST …/test-connection/`, read-only) — REAL (H5.8). */
export const testWAConnection = pickAdapter(
  'waConfig',
  real.testWAConnection,
  real.testWAConnection,
);

export {
  readDivergence,
  readDivergenceValue,
  readTestConnection,
  readWAConfigEnvelope,
  readWAConfigRow,
  readWAConfigValues,
  SETTINGS_WA_PATH,
  toWAConfigBody,
  WA_TEST_CONNECTION_PATH,
} from './real/waConfig';
export type {
  WAConfigDivergence,
  WAConfigEnvelope,
  WAConfigInput,
  WAConfigRow,
  WAConfigValues,
  WATestConnectionResult,
} from '@/types/wa-config';
