import { describe, expect, it } from 'vitest';
import {
  fetchCompany,
  readCompanyCurrency,
  readCompanyEnvelope,
  readCompanyRow,
  SETTINGS_COMPANY_PATH,
  toCompanyBody,
  updateCompany,
} from '@/api/company';
import { MODE, isReal } from '@/api/_adapter';
import type { ApiClient, ApiResponse } from '@/integrations/api-client';
import type { CompanyRow } from '@/types/company';

/**
 * H5.1 — adapter Company Profile (`/api/v1/settings/company/`, SINGLETON).
 *
 * Bentuk baris = PERSIS `django_app/master/company_services.py::company_row`:
 * `{id, name, legal_name, address, city, country, phone, email, npwp, website,
 * logo_url, currency_id, currency, timezone, is_active, created_at, updated_at}`.
 * **MES-only** (tanpa `task_id`/`queued`).
 */

const ROW: CompanyRow = {
  id: 1,
  name: 'PT Garmen Jaya',
  legal_name: 'PT Garmen Jaya Sejahtera',
  address: 'Jl. Industri 1',
  city: 'Bandung',
  country: 'ID',
  phone: '022-123456',
  email: 'admin@garmen.test',
  npwp: '012345678901000',
  website: 'https://garmen.test',
  logo_url: 'https://garmen.test/logo.png',
  currency_id: 4,
  currency: { id: 4, code: 'IDR', name: 'Rupiah', symbol: 'Rp' },
  timezone: 'Asia/Jakarta',
  is_active: true,
  created_at: '2026-10-14T03:00:00+00:00',
  updated_at: '2026-10-14T04:00:00+00:00',
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

describe('H5.1 — MODE, path & parsing', () => {
  it('MODE.company = real + path singleton', () => {
    expect(MODE['company']).toBe('real');
    expect(isReal('company')).toBe(true);
    expect(SETTINGS_COMPANY_PATH).toBe('/settings/company/');
  });

  it('readCompanyRow/Envelope/Currency (bentuk backend apa adanya)', () => {
    const row = readCompanyRow(ROW);

    expect(Object.keys(row ?? {}).sort()).toEqual(
      [
        'address',
        'city',
        'country',
        'created_at',
        'currency',
        'currency_id',
        'email',
        'id',
        'is_active',
        'legal_name',
        'logo_url',
        'name',
        'npwp',
        'phone',
        'timezone',
        'updated_at',
        'website',
      ].sort(),
    );
    expect(row?.currency?.code).toBe('IDR');
    expect(row?.npwp).toBe('012345678901000');

    expect(readCompanyEnvelope({ company: ROW })?.name).toBe('PT Garmen Jaya');
    expect(readCompanyEnvelope({ company: null })).toBeNull();
    expect(readCompanyCurrency(ROW.currency)?.symbol).toBe('Rp');
    expect(readCompanyCurrency(null)).toBeNull();
    expect(readCompanyRow({})).toBeNull();
    expect(readCompanyRow('bukan objek')).toBeNull();
  });

  it('toCompanyBody hanya membawa field yang dikirim (country auto-upper)', () => {
    expect(toCompanyBody({ name: ' PT A ', country: 'id' })).toEqual({
      name: 'PT A',
      country: 'ID',
    });
    expect(toCompanyBody({ currency_id: null, active: false })).toEqual({
      currency_id: null,
      active: false,
    });
  });
});

describe('H5.1 — HTTP adapter', () => {
  it('fetchCompany GET (null = belum diisi, bukan error)', async () => {
    const kosong = stubClient({ company: null });

    expect(await fetchCompany(kosong.client)).toBeNull();
    expect(kosong.requests).toEqual([{ path: '/settings/company/', method: 'GET' }]);

    const ada = stubClient({ company: ROW });

    expect((await fetchCompany(ada.client))?.city).toBe('Bandung');
  });

  it('updateCompany PUT (body terkirim + baris hasil)', async () => {
    const stub = stubClient({ company: { ...ROW, city: 'Solo' } });

    const saved = await updateCompany(stub.client, { name: 'PT Garmen Jaya', city: 'Solo' });

    expect(stub.requests).toEqual([
      {
        path: '/settings/company/',
        method: 'PUT',
        body: { name: 'PT Garmen Jaya', city: 'Solo' },
      },
    ]);
    expect(saved.city).toBe('Solo');
  });

  it('gagal HTTP 403/400 & bentuk respons rusak → melempar', async () => {
    await expect(
      updateCompany(failingClient(403, 'Hanya user dengan role ADMIN/OWNER'), { name: 'X' }),
    ).rejects.toThrow('ADMIN/OWNER');
    await expect(
      updateCompany(failingClient(400, "Field 'name' wajib diisi."), { city: 'Bandung' }),
    ).rejects.toThrow('wajib diisi');
    await expect(
      updateCompany(stubClient({ company: null }).client, { name: 'X' }),
    ).rejects.toThrow('tidak dikenali');
  });
});
