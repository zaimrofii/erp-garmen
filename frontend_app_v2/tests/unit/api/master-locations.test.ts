import { describe, expect, it } from 'vitest';
import {
  buildMasterLocationsPath,
  createLocation,
  deleteLocation,
  fetchLocation,
  fetchLocations,
  LOCATIONS_LIMIT_DEFAULT,
  LOCATIONS_LIMIT_MAX,
  LOCATION_USAGE_VALUES,
  MASTER_LOCATIONS_PATH,
  readLocationUsage,
  readMasterLocationPage,
  readMasterLocationRow,
  readMasterLocationSaved,
  toMasterLocationBody,
  updateLocation,
} from '@/api/masterLocations';
import { MODE, isReal } from '@/api/_adapter';
import type { ApiClient, ApiResponse } from '@/integrations/api-client';
import type { MasterLocationInput, MasterLocationRow } from '@/types/master-location';

/**
 * H1.4 — adapter master lokasi (`/api/v1/master/locations/`).
 *
 * Bentuk = PERSIS `django_app/master/location_services.py::location_row`:
 * `{id, code, name, usage, parent_id, parent_name, warehouse_id, warehouse_name, active,
 * odoo_id, children_count, complete_name}` + `{sync_record_id, task_id, queued}` pada
 * POST/PUT. `complete_name` = DERIVED (rantai induk), `children_count` dihitung
 * backend (satu `annotate(Count)`).
 */

const ROW: MasterLocationRow = {
  id: 12,
  code: 'WH/STOCK',
  name: 'Stok',
  usage: 'internal',
  parent_id: 3,
  parent_name: 'Gudang Utama',
  warehouse_id: 1,
  warehouse_name: 'Gudang Utama',
  active: true,
  odoo_id: null,
  children_count: 2,
  complete_name: 'Gudang Utama/Stok',
};

const LIVE_BODY = {
  rows: [
    ROW,
    {
      ...ROW,
      id: 13,
      code: 'WH/LOST',
      name: 'Kehilangan',
      usage: 'inventory',
      parent_id: null,
      parent_name: null,
      warehouse_id: null,
      warehouse_name: null,
      odoo_id: 21,
      children_count: 0,
      complete_name: 'Kehilangan',
      active: false,
    },
  ],
  total_count: 2,
  has_more: false,
  next_cursor: null,
};

const SAVED_BODY = { ...ROW, sync_record_id: 7, task_id: 'task-loc-1', queued: true };

const INPUT: MasterLocationInput = {
  code: ' WH/STOCK/A ',
  name: ' Rak A ',
  usage: 'view',
  parent_id: 12,
  warehouse_id: null,
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

describe('H1.4 — MODE & path master lokasi', () => {
  it('MODE.masterLocations = real (endpoint sudah ada) + konstanta path/limit', () => {
    expect(MODE['masterLocations']).toBe('real');
    expect(isReal('masterLocations')).toBe(true);
    expect(MASTER_LOCATIONS_PATH).toBe('/master/locations/');
    expect(LOCATIONS_LIMIT_DEFAULT).toBe(50);
    expect(LOCATIONS_LIMIT_MAX).toBe(200);
  });

  it('LOCATION_USAGE_VALUES = 7 nilai selection `stock.location.usage` Odoo', () => {
    expect([...LOCATION_USAGE_VALUES]).toEqual([
      'supplier',
      'view',
      'internal',
      'customer',
      'inventory',
      'production',
      'transit',
    ]);
  });

  it('buildMasterLocationsPath: param kosong dilewati, `false` tetap dikirim', () => {
    expect(buildMasterLocationsPath()).toBe('/master/locations/');
    expect(
      buildMasterLocationsPath({
        search: 'stock',
        usage: 'view',
        warehouse_id: 1,
        parent_id: 3,
        active: false,
        limit: 200,
        cursor: 40,
      }),
    ).toBe(
      '/master/locations/?search=stock&usage=view&warehouse_id=1&parent_id=3&active=false&limit=200&cursor=40',
    );
    expect(buildMasterLocationsPath({ usage: null, parent_id: null, active: null })).toBe(
      '/master/locations/',
    );
  });
});

describe('H1.4 — parsing baris (defensif, tanpa cast)', () => {
  it('readLocationUsage: 7 nilai sah, lain → internal', () => {
    for (const usage of LOCATION_USAGE_VALUES) {
      expect(readLocationUsage(usage)).toBe(usage);
    }

    expect(readLocationUsage('melayang')).toBe('internal');
    expect(readLocationUsage(null)).toBe('internal');
  });

  it('readMasterLocationRow: memetakan seluruh field + `null` tanpa id angka', () => {
    expect(readMasterLocationRow(ROW)).toEqual(ROW);
    expect(readMasterLocationRow(null)).toBeNull();
    expect(readMasterLocationRow({ id: '12' })).toBeNull();

    // Baris minimal: field hilang → nilai aman (bukan throw).
    expect(readMasterLocationRow({ id: 1 })).toEqual({
      id: 1,
      code: '',
      name: '',
      usage: 'internal',
      parent_id: null,
      parent_name: null,
      warehouse_id: null,
      warehouse_name: null,
      active: false,
      odoo_id: null,
      children_count: 0,
      complete_name: '',
    });
  });

  it('readMasterLocationPage / readMasterLocationSaved', () => {
    expect(readMasterLocationPage(null)).toBeNull();
    expect(readMasterLocationPage({ rows: 'bukan-array' })).toBeNull();
    expect(readMasterLocationPage(LIVE_BODY)?.rows).toHaveLength(2);

    expect(readMasterLocationSaved(SAVED_BODY)).toEqual({
      ...ROW,
      sync_record_id: 7,
      task_id: 'task-loc-1',
      queued: true,
    });
    expect(readMasterLocationSaved({ id: 1, queued: 'yes' })?.queued).toBe(false);
    expect(readMasterLocationSaved({ id: 1 })?.sync_record_id).toBeNull();
  });

  it('toMasterLocationBody: trim teks, usage & relasi apa adanya (`null` = akar)', () => {
    expect(toMasterLocationBody(INPUT)).toEqual({
      code: 'WH/STOCK/A',
      name: 'Rak A',
      usage: 'view',
      parent_id: 12,
      warehouse_id: null,
      active: false,
    });
  });
});

describe('H1.4 — detail & tulis (POST/PUT/DELETE)', () => {
  it('fetchLocations memanggil path + query di `/master/locations/`', async () => {
    const { client, requests } = stubClient(LIVE_BODY);

    const page = await fetchLocations(client, { usage: 'internal', active: true, limit: 50 });

    expect(requests).toEqual([
      { path: '/master/locations/?usage=internal&active=true&limit=50', method: 'GET' },
    ]);
    expect(page.total_count).toBe(2);
    expect(page.rows[0]?.complete_name).toBe('Gudang Utama/Stok');
  });

  it('fetchLocation memanggil `/master/locations/<id>/` + melempar pesan backend 404', async () => {
    const { client, requests } = stubClient(ROW);

    expect(await fetchLocation(client, 12)).toEqual(ROW);
    expect(requests).toEqual([{ path: '/master/locations/12/', method: 'GET' }]);

    await expect(
      fetchLocation(failingClient(404, 'Lokasi 9 tidak ditemukan.'), 9),
    ).rejects.toThrow(/tidak ditemukan/);
  });

  it('createLocation: POST body + parse jawaban saved', async () => {
    const { client, requests } = stubClient(SAVED_BODY);

    const saved = await createLocation(client, INPUT);

    expect(requests).toEqual([
      { path: '/master/locations/', method: 'POST', body: toMasterLocationBody(INPUT) },
    ]);
    expect(saved.id).toBe(12);
    expect(saved.usage).toBe('internal');
    expect(saved.sync_record_id).toBe(7);
    expect(saved.task_id).toBe('task-loc-1');
    expect(saved.queued).toBe(true);
  });

  it('createLocation 400 (kode duplikat) → melempar pesan backend', async () => {
    await expect(
      createLocation(failingClient(400, "Kode lokasi 'WH/STOCK' sudah dipakai lokasi lain."), INPUT),
    ).rejects.toThrow(/sudah dipakai/);
  });

  it('createLocation 403 (bukan admin/owner) → melempar pesan backend', async () => {
    await expect(createLocation(failingClient(403, 'HTTP 403'), INPUT)).rejects.toThrow(/403/);
  });

  it('updateLocation: PUT ke `/master/locations/<id>/` (termasuk menanggalkan induk)', async () => {
    const { client, requests } = stubClient({ ...SAVED_BODY, name: 'Rak A Baru' });

    const saved = await updateLocation(client, 12, { ...INPUT, parent_id: null });

    expect(requests).toEqual([
      {
        path: '/master/locations/12/',
        method: 'PUT',
        body: { ...toMasterLocationBody(INPUT), parent_id: null },
      },
    ]);
    expect(saved.name).toBe('Rak A Baru');
  });

  it('deleteLocation: DELETE (soft delete) & meneruskan pesan 400 "masih punya anak aktif"', async () => {
    const { client, requests } = stubClient({ id: 12, active: false, deleted: true });

    await deleteLocation(client, 12);
    expect(requests).toEqual([
      { path: '/master/locations/12/', method: 'DELETE', body: undefined },
    ]);

    await expect(
      deleteLocation(
        failingClient(400, "Lokasi 'WH' masih punya 1 anak aktif (WH/STOCK) — nonaktifkan dulu."),
        12,
      ),
    ).rejects.toThrow(/anak aktif/);
  });

  it('bentuk respons simpan tak dikenali → melempar pesan jelas', async () => {
    const { client } = stubClient({ ok: true });

    await expect(createLocation(client, INPUT)).rejects.toThrow(/tidak dikenali/);
  });
});
