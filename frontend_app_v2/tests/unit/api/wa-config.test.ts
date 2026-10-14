import { describe, expect, it } from 'vitest';
import {
  fetchWAConfig,
  readDivergence,
  readDivergenceValue,
  readTestConnection,
  readWAConfigEnvelope,
  readWAConfigRow,
  readWAConfigValues,
  SETTINGS_WA_PATH,
  testWAConnection,
  toWAConfigBody,
  updateWAConfig,
  WA_TEST_CONNECTION_PATH,
} from '@/api/waConfig';
import { MODE, isReal } from '@/api/_adapter';
import type { ApiClient, ApiResponse } from '@/integrations/api-client';

/**
 * H5.8 — adapter WA Gateway Config (`/api/v1/settings/wa/`, SINGLETON).
 *
 * Bentuk baris = PERSIS `master/wa_config_services.py::config_row` (3 field +
 * `id`/`is_active`/`created_at`/`updated_at`); `wa_api_key` **selalu** `***` bila
 * terisi. GET/PUT juga membawa `effective`/`diverges`/`needs_restart`/`restart_command`
 * (Opsi B — aktivasi lewat `.env` + restart).
 */

const VALUES = {
  wa_backend: 'real',
  wa_api_url: 'http://wa-gateway:8080',
  wa_api_key: '***',
};

const ROW = {
  id: 7,
  ...VALUES,
  is_active: true,
  created_at: '2026-10-14T03:00:00+00:00',
  updated_at: '2026-10-14T04:00:00+00:00',
};

const ENVELOPE = {
  config: ROW,
  effective: { ...VALUES, wa_backend: 'mock', wa_api_url: '' },
  diverges: { wa_backend: { db: 'real', env: 'mock' } },
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

describe('H5.8 — MODE, path & parsing', () => {
  it('MODE.waConfig = real + path config/test-connection', () => {
    expect(MODE['waConfig']).toBe('real');
    expect(isReal('waConfig')).toBe(true);
    expect(SETTINGS_WA_PATH).toBe('/settings/wa/');
    expect(WA_TEST_CONNECTION_PATH).toBe('/settings/wa/test-connection/');
  });

  it('readWAConfigValues/Row/Envelope (bentuk backend apa adanya)', () => {
    const values = readWAConfigValues(VALUES);

    expect(values?.wa_backend).toBe('real');
    expect(values?.wa_api_url).toBe('http://wa-gateway:8080');
    expect(values?.wa_api_key).toBe('***');

    const row = readWAConfigRow(ROW);

    expect(row?.id).toBe(7);
    expect(row?.is_active).toBe(true);
    expect(row?.wa_backend).toBe('real');

    const envelope = readWAConfigEnvelope(ENVELOPE);

    expect(envelope?.effective.wa_backend).toBe('mock');
    expect(envelope?.diverges['wa_backend']).toEqual({ db: 'real', env: 'mock' });
    expect(envelope?.needs_restart).toBe(true);
    expect(envelope?.restart_command).toContain('restart');

    // profil belum diisi -> config null, effective tetap ada
    expect(readWAConfigEnvelope({ ...ENVELOPE, config: null })?.config).toBeNull();

    // bentuk rusak -> null
    expect(readWAConfigEnvelope({ config: null })).toBeNull();
    expect(readWAConfigRow({})).toBeNull();
    expect(readWAConfigValues('bukan objek')).toBeNull();
  });

  it('readDivergenceValue / readDivergence (edge case)', () => {
    expect(readDivergenceValue(33)).toBe(33);
    expect(readDivergenceValue('http://wa-gateway:8080')).toBe('http://wa-gateway:8080');
    expect(readDivergenceValue(null)).toBeNull();
    expect(readDivergenceValue({})).toBeNull();

    expect(readDivergence({ db: '***', env: '***' })).toEqual({ db: '***', env: '***' });
    expect(readDivergence(null)).toBeNull();
  });

  it('toWAConfigBody hanya membawa field yang dikirim', () => {
    expect(toWAConfigBody({ wa_api_url: ' http://wa-gateway:8080 ' })).toEqual({
      wa_api_url: 'http://wa-gateway:8080',
    });

    // `wa_api_key` tidak di-trim ulang (rahasia / mask apa adanya)
    expect(toWAConfigBody({ wa_api_key: '***' })).toEqual({ wa_api_key: '***' });
    expect(toWAConfigBody({ wa_api_key: ' kunci ' })).toEqual({ wa_api_key: ' kunci ' });
    expect(toWAConfigBody({ wa_backend: 'mock', active: false })).toEqual({
      wa_backend: 'mock',
      active: false,
    });
    expect(toWAConfigBody({})).toEqual({});
  });
});

describe('H5.8 — HTTP adapter', () => {
  it('fetchWAConfig GET amplop', async () => {
    const stub = stubClient(ENVELOPE);

    const envelope = await fetchWAConfig(stub.client);

    expect(stub.requests).toEqual([{ path: '/settings/wa/', method: 'GET' }]);
    expect(envelope.config?.wa_backend).toBe('real');
    expect(envelope.needs_restart).toBe(true);
  });

  it('updateWAConfig PUT body + amplop', async () => {
    const stub = stubClient({ ...ENVELOPE, needs_restart: false, diverges: {} });

    const envelope = await updateWAConfig(stub.client, {
      wa_backend: 'mock',
      wa_api_key: '***',
    });

    expect(stub.requests).toEqual([
      { path: '/settings/wa/', method: 'PUT', body: { wa_backend: 'mock', wa_api_key: '***' } },
    ]);
    expect(envelope.needs_restart).toBe(false);
  });

  it('testWAConnection POST + readTestConnection', async () => {
    const stub = stubClient({
      ok: true,
      backend: 'mock',
      url: null,
      mock: true,
      message: 'Mock gateway aktif (tanpa jaringan) — alur notifikasi WA siap dipakai.',
    });

    const result = await testWAConnection(stub.client);

    expect(stub.requests).toEqual([
      { path: '/settings/wa/test-connection/', method: 'POST', body: {} },
    ]);
    expect(result.ok).toBe(true);
    expect(result.mock).toBe(true);
    expect(result.url).toBeNull();

    expect(readTestConnection({ ok: false, message: 'gagal' })?.url).toBeNull();
    expect(readTestConnection({ backend: 'mock' })).toBeNull();
  });

  it('gagal HTTP & bentuk rusak → melempar', async () => {
    await expect(
      updateWAConfig(failingClient(400, "Backend 'real'/'api' membutuhkan 'wa_api_url'."), {
        wa_backend: 'real',
      }),
    ).rejects.toThrow('membutuhkan');
    await expect(
      fetchWAConfig(failingClient(403, 'Hanya user dengan role ADMIN/OWNER')),
    ).rejects.toThrow('ADMIN/OWNER');
    await expect(fetchWAConfig(stubClient({ config: null }).client)).rejects.toThrow(
      'tidak dikenali',
    );
    await expect(
      testWAConnection(failingClient(403, 'Hanya user dengan role ADMIN/OWNER')),
    ).rejects.toThrow('ADMIN/OWNER');
  });
});

