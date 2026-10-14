import { describe, expect, it } from 'vitest';
import {
  buildMasterPartnersPath,
  createPartner,
  deletePartner,
  fetchPartner,
  fetchPartners,
  MASTER_PARTNERS_PATH,
  PARTNERS_LIMIT_DEFAULT,
  PARTNERS_LIMIT_MAX,
  readMasterPartnerDetail,
  readMasterPartnerPage,
  readMasterPartnerRow,
  readMasterPartnerSaved,
  toMasterPartnerBody,
  updatePartner,
} from '@/api/masterPartners';
import { MODE, isReal } from '@/api/_adapter';
import type { ApiClient, ApiResponse } from '@/integrations/api-client';
import type { MasterPartnerInput, MasterPartnerRow } from '@/types/master-partner';

/**
 * H1.6 — adapter master Partner (`/api/v1/master/partners/`).
 *
 * Bentuk = PERSIS `django_app/master/partner_services.py::partner_row`
 * (+ `orders_count` di detail): `{id, code, name, email, phone, city, address, npwp,
 * is_customer, is_vendor, is_company, customer_rank, supplier_rank, active, odoo_id,
 * created_at, updated_at}` + `{sync_record_id, task_id, queued}` pada POST/PUT.
 */

const ROW: MasterPartnerRow = {
  id: 7,
  code: 'PTR-PT-BUYER-EXPORT',
  name: 'PT Buyer Export',
  email: 'buyer@example.com',
  phone: '+62 812',
  city: 'Bandung',
  address: 'Jl. Merdeka 10\nBlok C',
  npwp: '012345678901000',
  is_customer: true,
  is_vendor: false,
  is_company: true,
  customer_rank: 3,
  supplier_rank: 0,
  active: true,
  odoo_id: null,
  created_at: '2026-10-11T02:00:00+00:00',
  updated_at: '2026-10-11T02:00:00+00:00',
};

const LIVE_BODY = {
  rows: [
    ROW,
    {
      ...ROW,
      id: 8,
      code: 'PTR-TOKO-JAHIT-JAYA',
      name: 'Toko jahit Jaya',
      email: '',
      phone: '',
      city: 'Jakarta',
      address: '',
      npwp: '',
      is_customer: false,
      is_vendor: true,
      is_company: true,
      customer_rank: 0,
      supplier_rank: 1,
      odoo_id: 45,
      active: false,
    },
  ],
  total_count: 2,
  has_more: false,
  next_cursor: null,
};

const SAVED_BODY = {
  ...ROW,
  orders_count: 2,
  sync_record_id: 31,
  task_id: 'task-partner-1',
  queued: true,
};

const INPUT: MasterPartnerInput = {
  code: ' PTR-BUYER ',
  name: ' PT Buyer Export ',
  email: ' buyer@example.com ',
  phone: ' +62 812 ',
  city: ' Bandung ',
  address: ' Jl. Merdeka 10 ',
  npwp: ' 01.234.567.8-901.000 ',
  is_customer: true,
  is_vendor: true,
  is_company: true,
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

describe('H1.6 — MODE & path master partner', () => {
  it('MODE.masterPartners = real (endpoint sudah ada) + konstanta path/limit', () => {
    expect(MODE['masterPartners']).toBe('real');
    expect(isReal('masterPartners')).toBe(true);
    expect(MASTER_PARTNERS_PATH).toBe('/master/partners/');
    expect(PARTNERS_LIMIT_DEFAULT).toBe(50);
    expect(PARTNERS_LIMIT_MAX).toBe(200);
  });

  it('buildMasterPartnersPath: param kosong dilewati, `false` tetap dikirim', () => {
    expect(buildMasterPartnersPath()).toBe('/master/partners/');
    expect(
      buildMasterPartnersPath({
        search: 'kain',
        is_customer: true,
        is_vendor: false,
        active: false,
        limit: 200,
        cursor: 20,
      }),
    ).toBe(
      '/master/partners/?search=kain&is_customer=true&is_vendor=false&active=false&limit=200&cursor=20',
    );
    expect(buildMasterPartnersPath({ is_customer: null, is_vendor: null, active: null })).toBe(
      '/master/partners/',
    );
  });
});

describe('H1.6 — parsing baris (defensif, tanpa cast)', () => {
  it('readMasterPartnerRow: memetakan seluruh field + `null` tanpa id angka', () => {
    expect(readMasterPartnerRow(ROW)).toEqual(ROW);
    expect(readMasterPartnerRow(null)).toBeNull();
    expect(readMasterPartnerRow({ id: '7' })).toBeNull();

    expect(readMasterPartnerRow({ id: 1 })).toEqual({
      id: 1,
      code: '',
      name: '',
      email: '',
      phone: '',
      city: '',
      address: '',
      npwp: '',
      is_customer: false,
      is_vendor: false,
      is_company: false,
      customer_rank: 0,
      supplier_rank: 0,
      active: false,
      odoo_id: null,
      created_at: null,
      updated_at: null,
    });
  });

  it('readMasterPartnerDetail menambah `orders_count`; readMasterPartnerSaved menambah info sync', () => {
    expect(readMasterPartnerDetail(ROW)?.orders_count).toBe(0);
    expect(readMasterPartnerDetail({ ...ROW, orders_count: 4 })?.orders_count).toBe(4);
    expect(readMasterPartnerDetail(null)).toBeNull();

    const saved = readMasterPartnerSaved(SAVED_BODY);
    expect(saved?.orders_count).toBe(2);
    expect(saved?.sync_record_id).toBe(31);
    expect(saved?.task_id).toBe('task-partner-1');
    expect(saved?.queued).toBe(true);
    expect(readMasterPartnerSaved({ id: 1 })?.queued).toBe(false);
  });

  it('readMasterPartnerPage: `null` kalau rows bukan array; 2 baris diparse', () => {
    expect(readMasterPartnerPage(null)).toBeNull();
    expect(readMasterPartnerPage({ rows: 'bukan-array' })).toBeNull();
    expect(readMasterPartnerPage(LIVE_BODY)?.rows).toHaveLength(2);
    expect(readMasterPartnerPage(LIVE_BODY)?.rows[1]?.is_vendor).toBe(true);
    expect(readMasterPartnerPage(LIVE_BODY)?.total_count).toBe(2);
  });

  it('toMasterPartnerBody: trim teks & flag apa adanya (NPWP dinormalisasi backend)', () => {
    expect(toMasterPartnerBody(INPUT)).toEqual({
      code: 'PTR-BUYER',
      name: 'PT Buyer Export',
      email: 'buyer@example.com',
      phone: '+62 812',
      city: 'Bandung',
      address: 'Jl. Merdeka 10',
      npwp: '01.234.567.8-901.000',
      is_customer: true,
      is_vendor: true,
      is_company: true,
      active: false,
    });
  });
});

describe('H1.6 — detail & tulis (POST/PUT/DELETE)', () => {
  it('fetchPartners memanggil path + query di `/master/partners/`', async () => {
    const { client, requests } = stubClient(LIVE_BODY);

    const page = await fetchPartners(client, { search: 'kain', is_vendor: true, limit: 50 });

    expect(requests).toEqual([
      { path: '/master/partners/?search=kain&is_vendor=true&limit=50', method: 'GET' },
    ]);
    expect(page.total_count).toBe(2);
    expect(page.rows[0]?.name).toBe('PT Buyer Export');
  });

  it('fetchPartner memanggil `/master/partners/<id>/` + melempar pesan backend 404', async () => {
    const { client, requests } = stubClient({ ...ROW, orders_count: 3 });

    const detail = await fetchPartner(client, 7);
    expect(requests).toEqual([{ path: '/master/partners/7/', method: 'GET' }]);
    expect(detail.orders_count).toBe(3);

    await expect(fetchPartner(failingClient(404, 'Partner 9 tidak ditemukan.'), 9)).rejects.toThrow(
      /tidak ditemukan/,
    );
  });

  it('createPartner: POST body + parse jawaban saved', async () => {
    const { client, requests } = stubClient(SAVED_BODY);

    const saved = await createPartner(client, INPUT);

    expect(requests).toEqual([
      { path: '/master/partners/', method: 'POST', body: toMasterPartnerBody(INPUT) },
    ]);
    expect(saved.id).toBe(7);
    expect(saved.sync_record_id).toBe(31);
    expect(saved.queued).toBe(true);
    expect(saved.orders_count).toBe(2);
  });

  it('createPartner 400 (peran/NPWP) → melempar pesan backend', async () => {
    await expect(
      createPartner(
        failingClient(400, 'Partner harus minimal salah satu: pelanggan (is_customer) atau supplier (is_vendor).'),
        INPUT,
      ),
    ).rejects.toThrow(/minimal salah satu/);
  });

  it('createPartner 403 (bukan admin/owner) → melempar pesan backend', async () => {
    await expect(createPartner(failingClient(403, 'HTTP 403'), INPUT)).rejects.toThrow(/403/);
  });

  it('updatePartner: PUT ke `/master/partners/<id>/`', async () => {
    const { client, requests } = stubClient({ ...SAVED_BODY, name: 'PT Buyer Export (baru)' });

    const saved = await updatePartner(client, 7, INPUT);

    expect(requests).toEqual([
      { path: '/master/partners/7/', method: 'PUT', body: toMasterPartnerBody(INPUT) },
    ]);
    expect(saved.name).toBe('PT Buyer Export (baru)');
  });

  it('deletePartner: DELETE (soft delete) & melempar error HTTP', async () => {
    const { client, requests } = stubClient({ id: 7, active: false, deleted: true });

    await deletePartner(client, 7);
    expect(requests).toEqual([{ path: '/master/partners/7/', method: 'DELETE', body: undefined }]);

    await expect(deletePartner(failingClient(403, 'HTTP 403'), 7)).rejects.toThrow(/403/);
  });

  it('bentuk respons simpan tak dikenali → melempar pesan jelas', async () => {
    const { client } = stubClient({ ok: true });

    await expect(createPartner(client, INPUT)).rejects.toThrow(/tidak dikenali/);
  });
});
