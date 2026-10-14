import { describe, expect, it } from 'vitest';
import {
  buildMasterTaxesPath,
  createTax,
  deleteTax,
  fetchDefaultTax,
  fetchTax,
  fetchTaxes,
  MASTER_TAXES_PATH,
  readMasterTaxDefault,
  readMasterTaxPage,
  readMasterTaxRow,
  readMasterTaxSaved,
  readTaxAmountType,
  readTaxUse,
  setDefaultTax,
  toMasterTaxBody,
  updateTax,
} from '@/api/masterTaxes';
import { MODE } from '@/api/_adapter';
import type { ApiClient, ApiResponse } from '@/integrations/api-client';
import type { MasterTaxInput, MasterTaxRow } from '@/types/master-tax';

/**
 * H3.6 — adapter master Tax (`/api/v1/master/taxes/`).
 *
 * Bentuk = PERSIS `django_app/master/tax_services.py::tax_row`:
 * `{id, code, name, amount, amount_type, type_tax_use, price_include, is_default,
 * active, odoo_id}` + `{sync_record_id, task_id, queued}` pada POST/PUT.
 * `is_default` = penanda MES (tidak dikirim/ditarik dari Odoo); `odoo_id` = kunci sync.
 */

const ROW: MasterTaxRow = {
  id: 12,
  code: 'PPN11-SALE',
  name: 'PPN 11%',
  amount: 11,
  amount_type: 'percent',
  type_tax_use: 'sale',
  price_include: false,
  is_default: true,
  active: true,
  odoo_id: null,
};

const LIVE_BODY = {
  rows: [
    ROW,
    {
      ...ROW,
      id: 13,
      code: 'PPN11-PURCHASE',
      name: 'PPN 11% (Pembelian)',
      type_tax_use: 'purchase',
      is_default: false,
      odoo_id: 19,
    },
  ],
  total_count: 2,
  has_more: false,
  next_cursor: null,
};

const SAVED_BODY = { ...ROW, sync_record_id: 7, task_id: 'task-tax-1', queued: true };

const INPUT: MasterTaxInput = {
  code: ' PPN12-SALE ',
  name: ' PPN 12% ',
  amount: 12,
  amount_type: 'percent',
  type_tax_use: 'purchase',
  price_include: true,
  is_default: false,
  active: false,
};

interface RecordedRequest {
  path: string;
  method: string;
  body?: unknown;
}

interface Stub {
  client: ApiClient;
  requests: RecordedRequest[];
}

function stubClient(data: unknown): Stub {
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

describe('H3.6 — MODE & path master Tax', () => {
  it('MODE.masterTaxes = real (endpoint H3.6 ADA di backend)', () => {
    expect(MODE['masterTaxes']).toBe('real');
    expect(MASTER_TAXES_PATH).toBe('/master/taxes/');
  });

  it('buildMasterTaxesPath: default tanpa query, param terisi saja yang dikirim', () => {
    expect(buildMasterTaxesPath()).toBe('/master/taxes/');
    expect(buildMasterTaxesPath({ search: 'ppn', type_tax_use: 'sale' })).toBe(
      '/master/taxes/?search=ppn&type_tax_use=sale',
    );
    expect(buildMasterTaxesPath({ active: false })).toBe('/master/taxes/?active=false');
    expect(buildMasterTaxesPath({ search: '', limit: 200, cursor: 50 })).toBe(
      '/master/taxes/?limit=200&cursor=50',
    );
  });

  it('readTaxUse/readTaxAmountType: nilai sah saja; lain → default', () => {
    expect(readTaxUse('sale')).toBe('sale');
    expect(readTaxUse('purchase')).toBe('purchase');
    expect(readTaxUse('none')).toBe('none');
    expect(readTaxUse('both')).toBe('sale');
    expect(readTaxUse(undefined)).toBe('sale');

    expect(readTaxAmountType('fixed')).toBe('fixed');
    expect(readTaxAmountType('percent')).toBe('percent');
    expect(readTaxAmountType('division')).toBe('percent');
  });
});

describe('H3.6 — parsing baris & payload', () => {
  it('readMasterTaxRow: field lengkap + fallback aman', () => {
    expect(readMasterTaxRow(ROW)).toEqual(ROW);
    expect(readMasterTaxRow({ id: '12' })).toBeNull();
    expect(readMasterTaxRow(null)).toBeNull();

    const sparse = readMasterTaxRow({ id: 3, amount: 'x' });
    expect(sparse).not.toBeNull();
    expect(sparse?.amount).toBe(0);
    expect(sparse?.is_default).toBe(false);
    expect(sparse?.odoo_id).toBeNull();
  });

  it('readMasterTaxPage / readMasterTaxSaved / readMasterTaxDefault', () => {
    expect(readMasterTaxPage(null)).toBeNull();
    expect(readMasterTaxPage(LIVE_BODY)?.rows).toHaveLength(2);

    expect(readMasterTaxSaved(SAVED_BODY)).toEqual({
      ...ROW,
      sync_record_id: 7,
      task_id: 'task-tax-1',
      queued: true,
    });
    expect(readMasterTaxSaved({ id: 1, queued: 'yes' })?.queued).toBe(false);

    // `default/` membalas `{tax: …}`; `null` = belum ada pajak sama sekali.
    expect(readMasterTaxDefault({ tax: ROW })).toEqual(ROW);
    expect(readMasterTaxDefault({ tax: null })).toBeNull();
    expect(readMasterTaxDefault('bukan-objek')).toBeNull();
  });

  it('toMasterTaxBody: trim teks, angka & selection apa adanya', () => {
    expect(toMasterTaxBody(INPUT)).toEqual({
      code: 'PPN12-SALE',
      name: 'PPN 12%',
      amount: 12,
      amount_type: 'percent',
      type_tax_use: 'purchase',
      price_include: true,
      is_default: false,
      active: false,
    });
  });
});


describe('H3.6 — daftar, detail & tulis', () => {
  it('fetchTaxes memanggil path + query yang benar', async () => {
    const { client, requests } = stubClient(LIVE_BODY);

    const page = await fetchTaxes(client, { search: 'ppn', type_tax_use: 'purchase', limit: 200 });

    expect(requests).toEqual([
      { path: '/master/taxes/?search=ppn&type_tax_use=purchase&limit=200', method: 'GET' },
    ]);
    expect(page.total_count).toBe(2);
  });

  it('fetchTax memanggil `/master/taxes/<id>/` dan melempar pesan backend saat 404', async () => {
    const { client, requests } = stubClient(ROW);

    expect(await fetchTax(client, 12)).toEqual(ROW);
    expect(requests).toEqual([{ path: '/master/taxes/12/', method: 'GET' }]);

    await expect(fetchTax(failingClient(404, 'Tax 9 tidak ditemukan.'), 9)).rejects.toThrow(
      /tidak ditemukan/,
    );
  });

  it('createTax: POST body + parse jawaban saved', async () => {
    const { client, requests } = stubClient(SAVED_BODY);

    const saved = await createTax(client, INPUT);

    expect(requests).toEqual([
      { path: '/master/taxes/', method: 'POST', body: toMasterTaxBody(INPUT) },
    ]);
    expect(saved.id).toBe(12);
    expect(saved.sync_record_id).toBe(7);
    expect(saved.queued).toBe(true);
  });

  it('createTax 400 (kode duplikat / amount negatif) & 403 → melempar pesan backend', async () => {
    await expect(
      createTax(failingClient(400, "Kode Tax 'PPN11-SALE' sudah dipakai pajak lain."), INPUT),
    ).rejects.toThrow(/sudah dipakai/);

    await expect(
      createTax(failingClient(400, "Field 'amount' tidak boleh negatif."), INPUT),
    ).rejects.toThrow(/negatif/);

    await expect(createTax(failingClient(403, 'HTTP 403'), INPUT)).rejects.toThrow(/403/);
  });

  it('updateTax: PUT ke `/master/taxes/<id>/`', async () => {
    const { client, requests } = stubClient({ ...SAVED_BODY, amount: 11 });

    const saved = await updateTax(client, 12, INPUT);

    expect(requests).toEqual([
      { path: '/master/taxes/12/', method: 'PUT', body: toMasterTaxBody(INPUT) },
    ]);
    expect(saved.amount).toBe(11);
  });

  it('deleteTax: DELETE (soft delete di backend) & melempar saat gagal', async () => {
    const { client, requests } = stubClient({ id: 12, active: false, deleted: true });

    await deleteTax(client, 12);
    expect(requests).toEqual([{ path: '/master/taxes/12/', method: 'DELETE', body: undefined }]);

    await expect(deleteTax(failingClient(403, 'HTTP 403'), 12)).rejects.toThrow(/403/);
  });

  it('setDefaultTax: POST `set-default/` + parse baris pajak', async () => {
    const { client, requests } = stubClient(ROW);

    const row = await setDefaultTax(client, 12);

    expect(requests).toEqual([
      { path: '/master/taxes/12/set-default/', method: 'POST', body: {} },
    ]);
    expect(row.is_default).toBe(true);
  });

  it('fetchDefaultTax: GET `default/` — `{tax: null}` → null (bukan melempar)', async () => {
    const withTax = stubClient({ tax: ROW });
    expect(await fetchDefaultTax(withTax.client)).toEqual(ROW);
    expect(withTax.requests).toEqual([{ path: '/master/taxes/default/', method: 'GET' }]);

    const empty = stubClient({ tax: null });
    expect(await fetchDefaultTax(empty.client)).toBeNull();
  });

  it('bentuk respons simpan tak dikenali → melempar pesan jelas', async () => {
    const { client } = stubClient({ ok: true });

    await expect(createTax(client, INPUT)).rejects.toThrow(/tidak dikenali/);
  });
});

