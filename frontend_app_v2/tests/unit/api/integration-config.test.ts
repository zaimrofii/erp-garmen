import { describe, expect, it } from 'vitest';
import {
  fetchIntegrationConfig,
  INTEGRATION_TEST_CONNECTION_PATH,
  readDivergence,
  readDivergenceValue,
  readIntegrationConfigEnvelope,
  readIntegrationConfigRow,
  readIntegrationConfigValues,
  readStrList,
  readTestConnection,
  SETTINGS_INTEGRATION_PATH,
  testIntegrationConnection,
  toIntegrationConfigBody,
  updateIntegrationConfig,
} from '@/api/integrationConfig';
import { MODE, isReal } from '@/api/_adapter';
import type { ApiClient, ApiResponse } from '@/integrations/api-client';

/**
 * H5.6 — adapter Integration Config (`/api/v1/settings/integration/`, SINGLETON).
 *
 * Bentuk baris = PERSIS `master/integration_config_services.py::config_row`
 * (16 field + `id`/`is_active`/`created_at`/`updated_at`); `odoo_api_key` **selalu** `***`
 * bila terisi. GET/PUT juga membawa `effective`/`diverges`/`needs_restart`/
 * `restart_command` (Opsi B — aktivasi lewat `.env` + restart).
 */

const VALUES = {
  erp_adapter: 'odoo',
  odoo_url: 'http://odoo:8069',
  odoo_db: 'garmen_db',
  odoo_user: 'api_bot',
  odoo_api_key: '***',
  odoo_timeout: 30,
  odoo_location_wip_id: 11,
  odoo_location_production_id: 12,
  odoo_location_fg_id: 13,
  odoo_location_scrap_id: 14,
  odoo_uom_id: 33,
  odoo_picking_type_internal_id: 5,
  odoo_payment_journal_id: 13,
  reconciliation_tolerance_units: 5,
  reconciliation_tolerance_pct: 0.01,
  reconciliation_alert_wa_to: ['6281'],
};

const ROW = {
  id: 3,
  ...VALUES,
  is_active: true,
  created_at: '2026-10-14T03:00:00+00:00',
  updated_at: '2026-10-14T04:00:00+00:00',
};

const ENVELOPE = {
  config: ROW,
  effective: { ...VALUES, odoo_uom_id: 99 },
  diverges: { odoo_uom_id: { db: 33, env: 99 } },
  needs_restart: true,
  restart_command: 'docker compose restart django celery_worker celery_beat',
};

interface RecordedRequest {
  path: string;
  method: string;
  body?: unknown;
}

function stubClient(data: unknown): { client: ApiClient; requests: RecordedRequest[] } {
  const requests: RecordedRequest[] = [];
  const reply = <T,>(): ApiResponse<T> => ({ ok: true, status: 200, data: data as T });

  const client = {
    get: async <T,>(path: string): Promise<ApiResponse<T>> => {
      requests.push({ path, method: 'GET' });

      return reply<T>();
    },
    post: async <T,>(path: string, body: unknown): Promise<ApiResponse<T>> => {
      requests.push({ path, method: 'POST', body });

      return reply<T>();
    },
    request: async <T,>(
      path: string,
      options?: { method?: 'GET' | 'POST' | 'PUT' | 'DELETE'; body?: unknown },
    ): Promise<ApiResponse<T>> => {
      requests.push({ path, method: options?.method ?? 'GET', body: options?.body });

      return reply<T>();
    },
  } as unknown as ApiClient;

  return { client, requests };
}

function failingClient(status: number, message: string): ApiClient {
  const response = <T,>(): ApiResponse<T> => ({
    ok: false,
    status,
    error: { kind: 'http_error', message },
  });

  return {
    request: async <T,>(): Promise<ApiResponse<T>> => response<T>(),
    get: async <T,>(): Promise<ApiResponse<T>> => response<T>(),
    post: async <T,>(): Promise<ApiResponse<T>> => response<T>(),
  } as unknown as ApiClient;
}

describe('H5.6 — MODE, path & parsing', () => {
  it('MODE.integrationConfig = real + path config/test-connection', () => {
    expect(MODE['integrationConfig']).toBe('real');
    expect(isReal('integrationConfig')).toBe(true);
    expect(SETTINGS_INTEGRATION_PATH).toBe('/settings/integration/');
    expect(INTEGRATION_TEST_CONNECTION_PATH).toBe('/settings/integration/test-connection/');
  });

  it('readIntegrationConfigValues/Row/Envelope (bentuk backend apa adanya)', () => {
    const values = readIntegrationConfigValues(VALUES);

    expect(values?.odoo_api_key).toBe('***');
    expect(values?.reconciliation_alert_wa_to).toEqual(['6281']);
    expect(values?.odoo_picking_type_internal_id).toBe(5);
    expect(values?.odoo_location_fg_id).toBe(13);

    const row = readIntegrationConfigRow(ROW);

    expect(row?.id).toBe(3);
    expect(row?.is_active).toBe(true);

    const envelope = readIntegrationConfigEnvelope(ENVELOPE);

    expect(envelope?.config?.id).toBe(3);
    expect(envelope?.effective.odoo_uom_id).toBe(99);
    expect(envelope?.diverges['odoo_uom_id']).toEqual({ db: 33, env: 99 });
    expect(envelope?.needs_restart).toBe(true);
    expect(envelope?.restart_command).toContain('restart');

    // config null tetap valid (profil belum diisi)
    expect(readIntegrationConfigEnvelope({ ...ENVELOPE, config: null })?.config).toBeNull();

    // bentuk rusak -> null
    expect(readIntegrationConfigEnvelope({ config: null })).toBeNull();
    expect(readIntegrationConfigRow({})).toBeNull();
    expect(readIntegrationConfigValues('bukan objek')).toBeNull();
  });

  it('readStrList / readDivergenceValue / readDivergence (edge case)', () => {
    expect(readStrList(['6281', '', '6282'])).toEqual(['6281', '6282']);
    expect(readStrList('bukan array')).toEqual([]);

    expect(readDivergenceValue(33)).toBe(33);
    expect(readDivergenceValue('http://odoo:8069')).toBe('http://odoo:8069');
    expect(readDivergenceValue([1, 2])).toEqual([1, 2]);
    expect(readDivergenceValue(null)).toBeNull();
    expect(readDivergenceValue({})).toBeNull();

    expect(readDivergence({ db: '***', env: '***' })).toEqual({ db: '***', env: '***' });
    expect(readDivergence(null)).toBeNull();
  });

  it('toIntegrationConfigBody hanya membawa field yang dikirim', () => {
    expect(
      toIntegrationConfigBody({ odoo_url: ' http://odoo:8069 ', odoo_uom_id: null }),
    ).toEqual({ odoo_url: 'http://odoo:8069', odoo_uom_id: null });

    // `odoo_api_key` tidak di-trim ulang (rahasia / mask apa adanya)
    expect(toIntegrationConfigBody({ odoo_api_key: '***' })).toEqual({ odoo_api_key: '***' });
    expect(toIntegrationConfigBody({ odoo_api_key: ' kunci ' })).toEqual({
      odoo_api_key: ' kunci ',
    });
    expect(
      toIntegrationConfigBody({ reconciliation_alert_wa_to: ['6281'], active: false }),
    ).toEqual({ reconciliation_alert_wa_to: ['6281'], active: false });
  });
});

describe('H5.6 — HTTP adapter', () => {
  it('fetchIntegrationConfig GET amplop', async () => {
    const stub = stubClient(ENVELOPE);

    const envelope = await fetchIntegrationConfig(stub.client);

    expect(stub.requests).toEqual([{ path: '/settings/integration/', method: 'GET' }]);
    expect(envelope.config?.erp_adapter).toBe('odoo');
    expect(envelope.needs_restart).toBe(true);
  });

  it('updateIntegrationConfig PUT body + amplop', async () => {
    const stub = stubClient({ ...ENVELOPE, needs_restart: false, diverges: {} });

    const envelope = await updateIntegrationConfig(stub.client, {
      odoo_uom_id: 99,
      reconciliation_tolerance_pct: 0.02,
    });

    expect(stub.requests).toEqual([
      {
        path: '/settings/integration/',
        method: 'PUT',
        body: { odoo_uom_id: 99, reconciliation_tolerance_pct: 0.02 },
      },
    ]);
    expect(envelope.needs_restart).toBe(false);
  });

  it('testIntegrationConnection POST + readTestConnection', async () => {
    const stub = stubClient({
      ok: true,
      adapter: 'odoo',
      url: 'http://odoo:8069',
      server_version: '17.0',
      message: 'Koneksi Odoo OK.',
    });

    const result = await testIntegrationConnection(stub.client);

    expect(stub.requests).toEqual([
      { path: '/settings/integration/test-connection/', method: 'POST', body: {} },
    ]);
    expect(result.ok).toBe(true);
    expect(result.server_version).toBe('17.0');

    expect(readTestConnection({ ok: false, message: 'gagal' })?.url).toBeNull();
    expect(readTestConnection({ adapter: 'odoo' })).toBeNull();
  });

  it('gagal HTTP & bentuk rusak → melempar', async () => {
    await expect(
      updateIntegrationConfig(failingClient(400, "Adapter 'odoo' membutuhkan 'odoo_db'."), {
        erp_adapter: 'odoo',
      }),
    ).rejects.toThrow('membutuhkan');
    await expect(
      fetchIntegrationConfig(failingClient(403, 'Hanya user dengan role ADMIN/OWNER')),
    ).rejects.toThrow('ADMIN/OWNER');
    await expect(fetchIntegrationConfig(stubClient({ config: null }).client)).rejects.toThrow(
      'tidak dikenali',
    );
    await expect(
      testIntegrationConnection(failingClient(403, 'Hanya user dengan role ADMIN/OWNER')),
    ).rejects.toThrow('ADMIN/OWNER');
  });
});
