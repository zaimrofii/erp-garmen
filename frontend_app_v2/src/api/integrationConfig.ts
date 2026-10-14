// ADAPTER - satu-satunya pintu data Integration Config (H5.6, TANPA logic domain).
//
// H5.6: endpoint `/api/v1/settings/integration/` SUDAH ADA di backend →
// MODE.integrationConfig = 'real' (`_adapter.ts`), jadi tidak ada implementasi dummy.
//
// **SINGLETON + Opsi B**: DB menyimpan *profil* config; konsumen tetap membaca `.env`.
// GET mengembalikan `config` + `effective` + `diverges` + `needs_restart` +
// `restart_command` supaya UI bisa menjelaskan bahwa perubahan belum otomatis aktif.
import { pickAdapter } from './_adapter';
import * as real from './real/integrationConfig';

/** Profil + effective + divergences (`GET /settings/integration/`) — REAL (H5.6). */
export const fetchIntegrationConfig = pickAdapter(
  'integrationConfig',
  real.fetchIntegrationConfig,
  real.fetchIntegrationConfig,
);

/** Simpan profil config (`PUT /settings/integration/`) — REAL (H5.6; izin admin/owner). */
export const updateIntegrationConfig = pickAdapter(
  'integrationConfig',
  real.updateIntegrationConfig,
  real.updateIntegrationConfig,
);

/** Uji koneksi Odoo (`POST …/test-connection/`, read-only) — REAL (H5.6). */
export const testIntegrationConnection = pickAdapter(
  'integrationConfig',
  real.testIntegrationConnection,
  real.testIntegrationConnection,
);

export {
  INTEGRATION_TEST_CONNECTION_PATH,
  readDivergence,
  readDivergenceValue,
  readIntegrationConfigEnvelope,
  readIntegrationConfigRow,
  readIntegrationConfigValues,
  readStrList,
  readTestConnection,
  SETTINGS_INTEGRATION_PATH,
  toIntegrationConfigBody,
} from './real/integrationConfig';
export type {
  IntegrationConfigDivergence,
  IntegrationConfigEnvelope,
  IntegrationConfigInput,
  IntegrationConfigRow,
  IntegrationConfigValues,
  TestConnectionResult,
} from '@/types/integration-config';
