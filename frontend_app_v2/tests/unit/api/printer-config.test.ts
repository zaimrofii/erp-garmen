import { describe, expect, it } from 'vitest';
import {
  PRINTER_TEST_CONNECTION_PATH,
  SETTINGS_PRINTER_PATH,
  fetchPrinterConfig,
  readDivergence,
  readDivergenceValue,
  readPrinterConfigEnvelope,
  readPrinterConfigRow,
  readPrinterConfigValues,
  readTestConnection,
  testPrinterConnection,
  toPrinterConfigBody,
  updatePrinterConfig,
} from '@/api/printerConfig';
import { MODE, isReal } from '@/api/_adapter';
import type { ApiClient, ApiResponse } from '@/integrations/api-client';

/**
 * H5.7 — adapter Printer Config (`/api/v1/settings/printer/`, SINGLETON).
 *
 * Bentuk baris = PERSIS `master/printer_config_services.py::config_row` (6 field +
 * `id`/`is_active`/`created_at`/`updated_at`) — **tanpa mask** (host/port/USB id bukan
 * rahasia). GET/PUT juga membawa `effective`/`diverges`/`needs_restart`/`restart_command`.
 */

const VALUES = {
  printer_backend: 'network',
  printer_usb_vendor_id: '',
  printer_usb_product_id: '',
  printer_network_host: '192.168.1.50',
  printer_network_port: 9100,
  printer_mock_dir: '',
};

const ROW = {
  id: 5,
  ...VALUES,
  is_active: true,
  created_at: '2026-10-14T03:00:00+00:00',
  updated_at: '2026-10-14T04:00:00+00:00',
};

const ENVELOPE = {
  config: ROW,
  effective: {
    ...VALUES,
    printer_backend: 'mock',
    printer_network_host: '',
    printer_network_port: null,
  },
  diverges: { printer_backend: { db: 'network', env: 'mock' } },
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

describe('H5.7 — MODE, path & parsing', () => {
  it('MODE.printerConfig = real + path config/test-connection', () => {
    expect(MODE['printerConfig']).toBe('real');
    expect(isReal('printerConfig')).toBe(true);
    expect(SETTINGS_PRINTER_PATH).toBe('/settings/printer/');
    expect(PRINTER_TEST_CONNECTION_PATH).toBe('/settings/printer/test-connection/');
  });

  it('readPrinterConfigValues/Row/Envelope (bentuk backend apa adanya)', () => {
    const values = readPrinterConfigValues(VALUES);

    expect(values?.printer_backend).toBe('network');
    expect(values?.printer_network_host).toBe('192.168.1.50');
    expect(values?.printer_network_port).toBe(9100);
    expect(values?.printer_mock_dir).toBe('');

    const row = readPrinterConfigRow(ROW);

    expect(row?.id).toBe(5);
    expect(row?.is_active).toBe(true);
    expect(row?.printer_network_port).toBe(9100);

    const envelope = readPrinterConfigEnvelope(ENVELOPE);

    expect(envelope?.effective.printer_backend).toBe('mock');
    expect(envelope?.diverges['printer_backend']).toEqual({ db: 'network', env: 'mock' });
    expect(envelope?.needs_restart).toBe(true);
    expect(envelope?.restart_command).toContain('restart');

    // profil belum diisi -> config null, effective tetap ada
    expect(readPrinterConfigEnvelope({ ...ENVELOPE, config: null })?.config).toBeNull();

    // port null tetap valid
    expect(
      readPrinterConfigRow({ ...ROW, printer_network_port: null })?.printer_network_port,
    ).toBeNull();

    // bentuk rusak -> null
    expect(readPrinterConfigEnvelope({ config: null })).toBeNull();
    expect(readPrinterConfigRow({})).toBeNull();
    expect(readPrinterConfigValues('bukan objek')).toBeNull();
  });

  it('readDivergenceValue / readDivergence (edge case, tanpa mask)', () => {
    expect(readDivergenceValue(9100)).toBe(9100);
    expect(readDivergenceValue('192.168.1.50')).toBe('192.168.1.50');
    expect(readDivergenceValue(null)).toBeNull();
    expect(readDivergenceValue({})).toBeNull();

    expect(readDivergence({ db: 'usb', env: 'mock' })).toEqual({ db: 'usb', env: 'mock' });
    expect(readDivergence({ db: 9100, env: null })).toEqual({ db: 9100, env: null });
    expect(readDivergence(null)).toBeNull();
  });

  it('toPrinterConfigBody hanya membawa field yang dikirim (teks di-trim)', () => {
    expect(toPrinterConfigBody({ printer_network_host: ' 10.0.0.9 ' })).toEqual({
      printer_network_host: '10.0.0.9',
    });

    expect(toPrinterConfigBody({ printer_network_port: 9100, active: false })).toEqual({
      printer_network_port: 9100,
      active: false,
    });

    // port null diteruskan (artinya: hapus)
    expect(toPrinterConfigBody({ printer_network_port: null })).toEqual({
      printer_network_port: null,
    });
    expect(toPrinterConfigBody({})).toEqual({});
  });
});

describe('H5.7 — HTTP adapter', () => {
  it('fetchPrinterConfig GET amplop', async () => {
    const stub = stubClient(ENVELOPE);

    const envelope = await fetchPrinterConfig(stub.client);

    expect(stub.requests).toEqual([{ path: '/settings/printer/', method: 'GET' }]);
    expect(envelope.config?.printer_backend).toBe('network');
    expect(envelope.needs_restart).toBe(true);
  });

  it('updatePrinterConfig PUT body + amplop', async () => {
    const stub = stubClient({ ...ENVELOPE, needs_restart: false, diverges: {} });

    const envelope = await updatePrinterConfig(stub.client, {
      printer_backend: 'network',
      printer_network_host: '192.168.1.50',
      printer_network_port: 9100,
    });

    expect(stub.requests).toEqual([
      {
        path: '/settings/printer/',
        method: 'PUT',
        body: {
          printer_backend: 'network',
          printer_network_host: '192.168.1.50',
          printer_network_port: 9100,
        },
      },
    ]);
    expect(envelope.needs_restart).toBe(false);
  });

  it('testPrinterConnection POST + readTestConnection', async () => {
    const stub = stubClient({
      ok: true,
      backend: 'mock',
      message: 'Mock dir siap: /tmp/print_mock',
    });

    const result = await testPrinterConnection(stub.client);

    expect(stub.requests).toEqual([
      { path: '/settings/printer/test-connection/', method: 'POST', body: {} },
    ]);
    expect(result.ok).toBe(true);
    expect(result.backend).toBe('mock');
    expect(result.message).toContain('Mock dir siap');

    expect(readTestConnection({ ok: false, message: 'usb stub' })?.backend).toBe('');
    expect(readTestConnection({ backend: 'mock' })).toBeNull();
  });

  it('gagal HTTP & bentuk rusak → melempar', async () => {
    await expect(
      updatePrinterConfig(
        failingClient(400, "Backend 'network' membutuhkan 'printer_network_host'."),
        { printer_backend: 'network' },
      ),
    ).rejects.toThrow('membutuhkan');
    await expect(
      fetchPrinterConfig(failingClient(403, 'Hanya user dengan role ADMIN/OWNER')),
    ).rejects.toThrow('ADMIN/OWNER');
    await expect(fetchPrinterConfig(stubClient({ config: null }).client)).rejects.toThrow(
      'tidak dikenali',
    );
    await expect(
      testPrinterConnection(failingClient(403, 'Hanya user dengan role ADMIN/OWNER')),
    ).rejects.toThrow('ADMIN/OWNER');
  });
});

