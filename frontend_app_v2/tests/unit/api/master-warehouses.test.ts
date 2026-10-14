import { describe, expect, it } from 'vitest';
import {
  buildMasterWarehousesPath,
  createWarehouse,
  deleteWarehouse,
  fetchWarehouse,
  fetchWarehouses,
  MASTER_WAREHOUSES_PATH,
  readDeliverySteps,
  readMasterWarehousePage,
  readMasterWarehouseRow,
  readMasterWarehouseSaved,
  readReceptionSteps,
  toMasterWarehouseBody,
  updateWarehouse,
} from '@/api/masterWarehouses';
import { MODE } from '@/api/_adapter';
import type { ApiClient, ApiResponse } from '@/integrations/api-client';
import type { MasterWarehouseInput, MasterWarehouseRow } from '@/types/master-warehouse';

/**
 * H1.3 — adapter master gudang (`/api/v1/master/warehouses/`).
 *
 * Bentuk = PERSIS `django_app/master/warehouse_services.py::warehouse_row`:
 * `{id, code, name, reception_steps, delivery_steps, active, odoo_id}` +
 * `{sync_record_id, task_id, queued}` pada POST/PUT. `active` = nama publik
 * `Warehouse.is_active`; `odoo_id` = kunci sync (push H1.3 update-only).
 */

const ROW: MasterWarehouseRow = {
  id: 3,
  code: 'WH',
  name: 'Gudang Utama',
  reception_steps: 'one_step',
  delivery_steps: 'ship_only',
  active: true,
  odoo_id: null,
};

const LIVE_BODY = {
  rows: [
    ROW,
    {
      ...ROW,
      id: 4,
      code: 'WH2',
      name: 'Gudang Bahan',
      reception_steps: 'two_steps',
      delivery_steps: 'pick_ship',
      odoo_id: 1,
      active: false,
    },
  ],
  total_count: 2,
  has_more: false,
  next_cursor: null,
};

const SAVED_BODY = { ...ROW, sync_record_id: 11, task_id: 'task-wh-1', queued: true };

const INPUT: MasterWarehouseInput = {
  code: ' WH3 ',
  name: ' Gudang Ketiga ',
  reception_steps: 'three_steps',
  delivery_steps: 'pick_pack_ship',
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

describe('H1.3 — MODE & path master gudang', () => {
  it('MODE.masterWarehouses = real (endpoint H1.3 ADA di backend)', () => {
    expect(MODE['masterWarehouses']).toBe('real');
    expect(MASTER_WAREHOUSES_PATH).toBe('/master/warehouses/');
  });

  it('buildMasterWarehousesPath: default tanpa query, param terisi saja yang dikirim', () => {
    expect(buildMasterWarehousesPath()).toBe('/master/warehouses/');
    expect(buildMasterWarehousesPath({ search: 'wh' })).toBe('/master/warehouses/?search=wh');
    expect(buildMasterWarehousesPath({ active: true })).toBe('/master/warehouses/?active=true');
    expect(buildMasterWarehousesPath({ active: false })).toBe('/master/warehouses/?active=false');
    expect(buildMasterWarehousesPath({ limit: 200, cursor: 20, active: null })).toBe(
      '/master/warehouses/?limit=200&cursor=20',
    );
  });

  it('fetchWarehouses memanggil path terfilter & mengembalikan envelope ListPage', async () => {
    const { client, requests } = stubClient(LIVE_BODY);

    const page = await fetchWarehouses(client, { search: 'wh', active: true, limit: 50 });

    expect(requests).toEqual([
      { path: '/master/warehouses/?search=wh&active=true&limit=50', method: 'GET' },
    ]);
    expect(page.rows).toHaveLength(2);
    expect(page.total_count).toBe(2);
    expect(page.has_more).toBe(false);
    expect(page.next_cursor).toBeNull();
    expect(page.rows[0]).toEqual(ROW);
    expect(page.rows[1]?.reception_steps).toBe('two_steps');
    expect(page.rows[1]?.delivery_steps).toBe('pick_ship');
    expect(page.rows[1]?.odoo_id).toBe(1);
    expect(page.rows[1]?.active).toBe(false);
  });
});

describe('H1.3 — reader baris & page', () => {
  it('readMasterWarehouseRow: baris rusak dibuang', () => {
    expect(readMasterWarehouseRow({ code: 'WH' })).toBeNull();
    expect(readMasterWarehouseRow({ id: '3' })).toBeNull();
    expect(readMasterWarehouseRow(null)).toBeNull();
    expect(readMasterWarehouseRow({ id: 1, code: 'WH' })?.name).toBe('');
  });

  it('readReceptionSteps/readDeliverySteps: nilai tak dikenal → default Odoo', () => {
    expect(readReceptionSteps('two_steps')).toBe('two_steps');
    expect(readReceptionSteps('three_steps')).toBe('three_steps');
    expect(readReceptionSteps('diam_diam')).toBe('one_step');

    expect(readDeliverySteps('pick_ship')).toBe('pick_ship');
    expect(readDeliverySteps('pick_pack_ship')).toBe('pick_pack_ship');
    expect(readDeliverySteps('kirim_langsung')).toBe('ship_only');
  });

  it('readMasterWarehousePage / readMasterWarehouseSaved', () => {
    expect(readMasterWarehousePage(null)).toBeNull();
    expect(readMasterWarehousePage({ rows: 'bukan-array' })).toBeNull();
    expect(readMasterWarehousePage(LIVE_BODY)?.rows).toHaveLength(2);

    expect(readMasterWarehouseSaved(SAVED_BODY)).toEqual({
      ...ROW,
      sync_record_id: 11,
      task_id: 'task-wh-1',
      queued: true,
    });
    expect(readMasterWarehouseSaved({ id: 1, queued: 'yes' })?.queued).toBe(false);
  });

  it('toMasterWarehouseBody: trim teks, steps & active apa adanya', () => {
    expect(toMasterWarehouseBody(INPUT)).toEqual({
      code: 'WH3',
      name: 'Gudang Ketiga',
      reception_steps: 'three_steps',
      delivery_steps: 'pick_pack_ship',
      active: false,
    });
  });
});

describe('H1.3 — detail & tulis (POST/PUT/DELETE)', () => {
  it('fetchWarehouse memanggil `/master/warehouses/<id>/` + melempar pesan backend 404', async () => {
    const { client, requests } = stubClient(ROW);

    expect(await fetchWarehouse(client, 3)).toEqual(ROW);
    expect(requests).toEqual([{ path: '/master/warehouses/3/', method: 'GET' }]);

    await expect(
      fetchWarehouse(failingClient(404, 'Gudang 9 tidak ditemukan.'), 9),
    ).rejects.toThrow(/tidak ditemukan/);
  });

  it('createWarehouse: POST body + parse jawaban saved', async () => {
    const { client, requests } = stubClient(SAVED_BODY);

    const saved = await createWarehouse(client, INPUT);

    expect(requests).toEqual([
      { path: '/master/warehouses/', method: 'POST', body: toMasterWarehouseBody(INPUT) },
    ]);
    expect(saved.id).toBe(3);
    expect(saved.sync_record_id).toBe(11);
    expect(saved.task_id).toBe('task-wh-1');
    expect(saved.queued).toBe(true);
  });

  it('createWarehouse 400 (kode duplikat) → melempar pesan backend', async () => {
    await expect(
      createWarehouse(failingClient(400, "Kode gudang 'WH3' sudah dipakai gudang lain."), INPUT),
    ).rejects.toThrow(/sudah dipakai/);
  });

  it('createWarehouse 403 (bukan admin/owner) → melempar pesan backend', async () => {
    await expect(createWarehouse(failingClient(403, 'HTTP 403'), INPUT)).rejects.toThrow(/403/);
  });

  it('updateWarehouse: PUT ke `/master/warehouses/<id>/`', async () => {
    const { client, requests } = stubClient({ ...SAVED_BODY, name: 'Gudang Baru' });

    const saved = await updateWarehouse(client, 3, INPUT);

    expect(requests).toEqual([
      { path: '/master/warehouses/3/', method: 'PUT', body: toMasterWarehouseBody(INPUT) },
    ]);
    expect(saved.name).toBe('Gudang Baru');
  });

  it('deleteWarehouse: DELETE (soft delete di backend) & melempar saat gagal', async () => {
    const { client, requests } = stubClient({ id: 3, active: false, deleted: true });

    await deleteWarehouse(client, 3);
    expect(requests).toEqual([
      { path: '/master/warehouses/3/', method: 'DELETE', body: undefined },
    ]);

    await expect(deleteWarehouse(failingClient(403, 'HTTP 403'), 3)).rejects.toThrow(/403/);
  });

  it('bentuk respons simpan tak dikenali → melempar pesan jelas', async () => {
    const { client } = stubClient({ ok: true });

    await expect(createWarehouse(client, INPUT)).rejects.toThrow(/tidak dikenali/);
  });
});

