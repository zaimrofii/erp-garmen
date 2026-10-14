import { describe, expect, it } from 'vitest';
import {
  buildMasterCurrenciesPath,
  createCurrency,
  CURRENCIES_DEFAULT_PATH,
  CURRENCIES_LIMIT_DEFAULT,
  CURRENCIES_LIMIT_MAX,
  currencyDetailPath,
  currencySetDefaultPath,
  deleteCurrency,
  fetchCurrencies,
  fetchCurrency,
  fetchDefaultCurrency,
  readMasterCurrencyDefault,
  readMasterCurrencyDeleted,
  readMasterCurrencyPage,
  readMasterCurrencyRow,
  setDefaultCurrency,
  SETTINGS_CURRENCIES_PATH,
  toMasterCurrencyCreateBody,
  toMasterCurrencyUpdateBody,
  updateCurrency,
} from '@/api/masterCurrencies';
import { MODE, isReal } from '@/api/_adapter';
import type { ApiClient, ApiResponse } from '@/integrations/api-client';
import type { MasterCurrencyRow } from '@/types/master-currency';

/**
 * H5.2 — adapter Currency (`/api/v1/settings/currencies/`).
 *
 * Bentuk baris = PERSIS `django_app/master/currency_services.py::currency_row`:
 * `{id, code, name, symbol, rate, is_default, is_active, odoo_id}`.
 * **MES-only** (tanpa `task_id`/`queued`) — ledger `SyncRecord` ditulis `SKIPPED`.
 */

const ROW: MasterCurrencyRow = {
  id: 4,
  code: 'IDR',
  name: 'Rupiah',
  symbol: 'Rp',
  rate: 1,
  is_default: true,
  is_active: true,
  odoo_id: null,
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

describe('H5.2 — MODE, path & parsing', () => {
  it('MODE.masterCurrencies = real + path list/detail/set-default/default', () => {
    expect(MODE['masterCurrencies']).toBe('real');
    expect(isReal('masterCurrencies')).toBe(true);
    expect(SETTINGS_CURRENCIES_PATH).toBe('/settings/currencies/');
    expect(CURRENCIES_DEFAULT_PATH).toBe('/settings/currencies/default/');
    expect(CURRENCIES_LIMIT_DEFAULT).toBe(50);
    expect(CURRENCIES_LIMIT_MAX).toBe(200);

    expect(currencyDetailPath(4)).toBe('/settings/currencies/4/');
    expect(currencySetDefaultPath(4)).toBe('/settings/currencies/4/set-default/');
  });

  it('buildMasterCurrenciesPath hanya mengirim param terisi', () => {
    expect(buildMasterCurrenciesPath()).toBe('/settings/currencies/');
    expect(buildMasterCurrenciesPath({ search: 'rup', active: false, limit: 200 })).toBe(
      '/settings/currencies/?search=rup&active=false&limit=200',
    );
    expect(buildMasterCurrenciesPath({ active: null, cursor: 20 })).toBe(
      '/settings/currencies/?cursor=20',
    );
  });

  it('read* : row/page/default/deleted (bentuk backend apa adanya)', () => {
    const row = readMasterCurrencyRow(ROW);

    expect(Object.keys(row ?? {}).sort()).toEqual(
      [
        'code',
        'id',
        'is_active',
        'is_default',
        'name',
        'odoo_id',
        'rate',
        'symbol',
      ].sort(),
    );
    expect(row?.rate).toBe(1);
    expect(row?.odoo_id).toBeNull();

    const page = readMasterCurrencyPage({
      rows: [ROW],
      total_count: 3,
      has_more: false,
      next_cursor: null,
    });

    expect(page?.total_count).toBe(3);
    expect(page?.rows[0]?.code).toBe('IDR');

    expect(readMasterCurrencyDefault({ currency: ROW })?.code).toBe('IDR');
    expect(readMasterCurrencyDefault({ currency: null })).toBeNull();

    const deleted = readMasterCurrencyDeleted({
      id: 4,
      is_active: false,
      deleted: true,
      is_default: false,
      sync_record_id: 9,
    });

    expect(deleted?.deleted).toBe(true);
    expect(deleted?.sync_record_id).toBe(9);

    expect(readMasterCurrencyRow(null)).toBeNull();
    expect(readMasterCurrencyRow({})).toBeNull();
    expect(readMasterCurrencyRow('bukan objek')).toBeNull();
  });

  it('toMasterCurrencyCreateBody/UpdateBody (PURE)', () => {
    expect(
      toMasterCurrencyCreateBody({ code: ' gbp ', name: ' Pound ', symbol: ' £ ', rate: 0.5 }),
    ).toEqual({ code: 'GBP', name: 'Pound', symbol: '£', rate: 0.5 });
    expect(toMasterCurrencyCreateBody({ code: 'gbp', name: 'Pound' })).toEqual({
      code: 'GBP',
      name: 'Pound',
      symbol: '',
    });

    expect(toMasterCurrencyUpdateBody({ name: ' Pound Sterling ', active: false })).toEqual({
      name: 'Pound Sterling',
      active: false,
    });
    expect(toMasterCurrencyUpdateBody({ code: ' usd ', rate: null })).toEqual({
      code: 'USD',
      rate: null,
    });
  });
});

describe('H5.2 — HTTP adapter', () => {
  it('fetchCurrencies/fetchCurrency/fetchDefaultCurrency (GET)', async () => {
    const list = stubClient({ rows: [ROW], total_count: 1, has_more: false, next_cursor: null });

    const page = await fetchCurrencies(list.client, { active: true, limit: 200 });

    expect(list.requests).toEqual([
      { path: '/settings/currencies/?active=true&limit=200', method: 'GET' },
    ]);
    expect(page.rows[0]?.code).toBe('IDR');

    const one = stubClient(ROW);

    const detail = await fetchCurrency(one.client, 4);

    expect(one.requests).toEqual([{ path: '/settings/currencies/4/', method: 'GET' }]);
    expect(detail.name).toBe('Rupiah');

    const kosong = stubClient({ currency: null });

    expect(await fetchDefaultCurrency(kosong.client)).toBeNull();
    expect(kosong.requests).toEqual([
      { path: '/settings/currencies/default/', method: 'GET' },
    ]);

    const ada = stubClient({ currency: ROW });

    expect((await fetchDefaultCurrency(ada.client))?.code).toBe('IDR');
  });

  it('createCurrency POST + updateCurrency PUT + setDefaultCurrency POST', async () => {
    const created = stubClient(ROW);

    const row = await createCurrency(created.client, {
      code: 'idr',
      name: 'Rupiah',
      symbol: 'Rp',
    });

    expect(created.requests).toEqual([
      {
        path: '/settings/currencies/',
        method: 'POST',
        body: { code: 'IDR', name: 'Rupiah', symbol: 'Rp' },
      },
    ]);
    expect(row.code).toBe('IDR');

    const updated = stubClient({ ...ROW, name: 'Rupiah (baru)' });

    const saved = await updateCurrency(updated.client, 4, {
      name: 'Rupiah (baru)',
      active: false,
    });

    expect(updated.requests).toEqual([
      {
        path: '/settings/currencies/4/',
        method: 'PUT',
        body: { name: 'Rupiah (baru)', active: false },
      },
    ]);
    expect(saved.name).toBe('Rupiah (baru)');

    const defaulted = stubClient({ ...ROW, is_default: true });

    await setDefaultCurrency(defaulted.client, 4);

    expect(defaulted.requests).toEqual([
      { path: '/settings/currencies/4/set-default/', method: 'POST', body: {} },
    ]);
  });

  it('deleteCurrency DELETE 200 + body (soft delete) & gagal HTTP melempar', async () => {
    const stub = stubClient({
      id: 4,
      is_active: false,
      deleted: true,
      is_default: false,
      sync_record_id: 11,
    });

    const deleted = await deleteCurrency(stub.client, 4);

    expect(stub.requests).toEqual([
      { path: '/settings/currencies/4/', method: 'DELETE', body: undefined },
    ]);
    expect(deleted.deleted).toBe(true);
    expect(deleted.sync_record_id).toBe(11);

    await expect(
      createCurrency(failingClient(400, "Kode mata uang 'IDR' sudah dipakai."), {
        code: 'IDR',
        name: 'Rupiah',
      }),
    ).rejects.toThrow('sudah dipakai');
    await expect(
      deleteCurrency(failingClient(400, "Mata uang 'USD' masih dipakai (protected ISO)"), 4),
    ).rejects.toThrow('protected ISO');
    await expect(
      setDefaultCurrency(failingClient(403, 'Hanya user dengan role ADMIN/OWNER'), 4),
    ).rejects.toThrow('ADMIN/OWNER');
  });

  it('bentuk respons rusak → melempar', async () => {
    await expect(
      createCurrency(stubClient('bukan objek').client, { code: 'IDR', name: 'X' }),
    ).rejects.toThrow('tidak dikenali');
    await expect(deleteCurrency(stubClient({}).client, 4)).rejects.toThrow('tidak dikenali');
  });
});
