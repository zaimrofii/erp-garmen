// REAL - Integration Config (H5.6). Endpoint: `/api/v1/settings/integration/` (SINGLETON)
//   GET  `/settings/integration/` → {config, effective, diverges, needs_restart, restart_command}
//   PUT  `/settings/integration/` → amplop yang sama (create-on-first-PUT; ADMIN/OWNER)
//   POST `/settings/integration/test-connection/` → {ok, adapter, url, server_version, message}
//
// Pemetaan UI ↔ backend (tidak ada shape yang dikarang):
//   * baris `{id, erp_adapter, odoo_url, odoo_db, odoo_user, odoo_api_key, odoo_timeout,
//     7 id Odoo, 3 field rekonsiliasi, is_active, created_at, updated_at}`;
//   * `odoo_api_key` **selalu** `***` bila terisi (rahasia tidak pernah dikirim apa adanya);
//   * `effective` = nilai `.env` yang aktif; `diverges` = `{field: {db, env}}` (masked);
//   * `needs_restart` = bool(diverges) — aktivasi butuh salin ke `.env` + restart worker.
//
// Catatan: `ApiClient` hanya punya `get`/`post` — PUT lewat `client.request()`.
import type { ApiClient } from '@/integrations/api-client';
import type {
  IntegrationConfigDivergence,
  IntegrationConfigEnvelope,
  IntegrationConfigInput,
  IntegrationConfigRow,
  IntegrationConfigValues,
  TestConnectionResult,
} from '@/types/integration-config';
import { unwrap } from '../client';
import { isRecord, readBool, readNullableNum, readNum, readStr } from './_shape';

/** Path relatif terhadap `VITE_API_BASE_URL` (`…/api/v1`). */
export const SETTINGS_INTEGRATION_PATH = '/settings/integration/';

/** Path uji koneksi Odoo (POST, read-only). */
export const INTEGRATION_TEST_CONNECTION_PATH = `${SETTINGS_INTEGRATION_PATH}test-connection/`;

/** PURE — daftar string (buang item kosong); bukan array → `[]`. */
export function readStrList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];

  return value.map((item) => readStr(item)).filter((item) => item !== '');
}

/** PURE — nilai satu field `diverges` (`db`/`env`): string | angka | array angka | null. */
export function readDivergenceValue(value: unknown): string | number | number[] | null {
  if (Array.isArray(value)) {
    return value.map((item) => readNum(item));
  }
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string') return value;

  return null;
}

/** PURE — satu entri `diverges` → `{db, env}`; `null` kalau bukan objek. */
export function readDivergence(raw: unknown): IntegrationConfigDivergence | null {
  if (!isRecord(raw)) return null;

  return {
    db: readDivergenceValue(raw['db']),
    env: readDivergenceValue(raw['env']),
  };
}

/** PURE — 16 field nilai config (tanpa `id`/status/timestamp). */
export function readIntegrationConfigValues(raw: unknown): IntegrationConfigValues | null {
  if (!isRecord(raw)) return null;

  return {
    erp_adapter: readStr(raw['erp_adapter']),
    odoo_url: readStr(raw['odoo_url']),
    odoo_db: readStr(raw['odoo_db']),
    odoo_user: readStr(raw['odoo_user']),
    odoo_api_key: readStr(raw['odoo_api_key']),
    odoo_timeout: readNum(raw['odoo_timeout']),
    odoo_location_wip_id: readNullableNum(raw['odoo_location_wip_id']),
    odoo_location_production_id: readNullableNum(raw['odoo_location_production_id']),
    odoo_location_fg_id: readNullableNum(raw['odoo_location_fg_id']),
    odoo_location_scrap_id: readNullableNum(raw['odoo_location_scrap_id']),
    odoo_uom_id: readNullableNum(raw['odoo_uom_id']),
    odoo_picking_type_internal_id: readNullableNum(raw['odoo_picking_type_internal_id']),
    odoo_payment_journal_id: readNullableNum(raw['odoo_payment_journal_id']),
    reconciliation_tolerance_units: readNum(raw['reconciliation_tolerance_units']),
    reconciliation_tolerance_pct: readNum(raw['reconciliation_tolerance_pct']),
    reconciliation_alert_wa_to: readStrList(raw['reconciliation_alert_wa_to']),
  };
}

/** PURE — satu baris profil (`null` kalau tanpa `id` angka). */
export function readIntegrationConfigRow(raw: unknown): IntegrationConfigRow | null {
  if (!isRecord(raw)) return null;

  const id = raw['id'];
  if (typeof id !== 'number' || !Number.isFinite(id)) return null;

  const values = readIntegrationConfigValues(raw);
  if (values === null) return null;

  return {
    id,
    ...values,
    is_active: readBool(raw['is_active']),
    created_at: readStr(raw['created_at']),
    updated_at: readStr(raw['updated_at']),
  };
}

/**
 * PURE — amplop respons → `IntegrationConfigEnvelope | null`.
 *
 * `config` boleh `null` (profil belum diisi), tetapi `effective` **wajib** objek —
 * kalau tidak, respons dianggap tidak dikenali.
 */
export function readIntegrationConfigEnvelope(raw: unknown): IntegrationConfigEnvelope | null {
  if (!isRecord(raw)) return null;

  const effective = readIntegrationConfigValues(raw['effective']);
  if (effective === null) return null;

  const diverges: Record<string, IntegrationConfigDivergence> = {};
  const rawDiverges = raw['diverges'];
  if (isRecord(rawDiverges)) {
    for (const [field, value] of Object.entries(rawDiverges)) {
      const parsed = readDivergence(value);
      if (parsed !== null) diverges[field] = parsed;
    }
  }

  return {
    config: readIntegrationConfigRow(raw['config']),
    effective,
    diverges,
    needs_restart: readBool(raw['needs_restart']),
    restart_command: readStr(raw['restart_command']),
  };
}

/** PURE — body `PUT` (hanya field yang ada di input). */
export function toIntegrationConfigBody(
  input: IntegrationConfigInput,
): Record<string, unknown> {
  const keys: (keyof IntegrationConfigInput)[] = [
    'erp_adapter',
    'odoo_url',
    'odoo_db',
    'odoo_user',
    'odoo_api_key',
    'odoo_timeout',
    'odoo_location_wip_id',
    'odoo_location_production_id',
    'odoo_location_fg_id',
    'odoo_location_scrap_id',
    'odoo_uom_id',
    'odoo_picking_type_internal_id',
    'odoo_payment_journal_id',
    'reconciliation_tolerance_units',
    'reconciliation_tolerance_pct',
    'reconciliation_alert_wa_to',
    'active',
  ];
  const body: Record<string, unknown> = {};

  for (const key of keys) {
    const value = input[key];
    if (value === undefined) continue;
    // teks kredensial di-trim; `odoo_api_key` SENGAJA tidak di-trim ulang (nilai rahasia
    // apa adanya / `***` = jangan ubah).
    body[key] =
      (key === 'odoo_url' || key === 'odoo_db' || key === 'odoo_user') && typeof value === 'string'
        ? value.trim()
        : value;
  }

  return body;
}

/** PURE — respons `test-connection`; `null` kalau bentuk tidak dikenali. */
export function readTestConnection(raw: unknown): TestConnectionResult | null {
  if (!isRecord(raw)) return null;
  if (typeof raw['ok'] !== 'boolean') return null;

  const optional = (value: unknown): string | null =>
    value === null || value === undefined ? null : readStr(value);

  return {
    ok: raw['ok'],
    adapter: readStr(raw['adapter']),
    url: optional(raw['url']),
    server_version: optional(raw['server_version']),
    message: readStr(raw['message']),
  };
}

/** Profil + effective + divergences (`GET`). Gagal HTTP → melempar. */
export async function fetchIntegrationConfig(
  client: ApiClient,
): Promise<IntegrationConfigEnvelope> {
  const envelope = readIntegrationConfigEnvelope(
    unwrap(await client.get<unknown>(SETTINGS_INTEGRATION_PATH)),
  );
  if (envelope === null) {
    throw new Error('Bentuk respons konfigurasi integrasi tidak dikenali.');
  }

  return envelope;
}

/** Simpan profil config (PUT, ADMIN/OWNER; create-on-first-PUT) → amplop terbaru. */
export async function updateIntegrationConfig(
  client: ApiClient,
  input: IntegrationConfigInput,
): Promise<IntegrationConfigEnvelope> {
  const envelope = readIntegrationConfigEnvelope(
    unwrap(
      await client.request<unknown>(SETTINGS_INTEGRATION_PATH, {
        method: 'PUT',
        body: toIntegrationConfigBody(input),
      }),
    ),
  );
  if (envelope === null) {
    throw new Error('Bentuk respons simpan konfigurasi integrasi tidak dikenali.');
  }

  return envelope;
}

/** Uji koneksi Odoo (POST, read-only, kredensial `.env`) → hasil uji. */
export async function testIntegrationConnection(
  client: ApiClient,
): Promise<TestConnectionResult> {
  const result = readTestConnection(
    unwrap(await client.post<unknown>(INTEGRATION_TEST_CONNECTION_PATH, {})),
  );
  if (result === null) {
    throw new Error('Bentuk respons uji koneksi tidak dikenali.');
  }

  return result;
}
