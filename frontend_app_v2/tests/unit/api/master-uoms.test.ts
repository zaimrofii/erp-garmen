import { describe, expect, it } from 'vitest';
import {
  buildMasterUomsPath,
  createUom,
  deleteUom,
  fetchUom,
  fetchUoms,
  MASTER_UOMS_PATH,
  readMasterUomPage,
  readMasterUomRow,
  readMasterUomSaved,
  readUomType,
  toMasterUomBody,
  updateUom,
} from '@/api/masterUoms';
import { MODE } from '@/api/_adapter';
import type { ApiClient, ApiResponse } from '@/integrations/api-client';
import type { MasterUomInput, MasterUomRow } from '@/types/master-uom';

/**
 * H1.2 — adapter master UoM (`/api/v1/master/uoms/`).
 *
 * Bentuk = PERSIS `django_app/master/uom_services.py::uom_row`:
 * `{id, code, name, category, uom_type, factor, rounding, active, odoo_id}` +
 * `{sync_record_id, task_id, queued}` pada POST/PUT. `active` = nama publik
 * `UoM.is_active`; `odoo_id` = kunci sync.
 */

const ROW: MasterUomRow = {
  id: 5,
  code: 'PCS',
  name: 'Pieces',
  category: 'Unit',
  uom_type: 'reference',
  factor: 1,
  rounding: 0.01,
  active: true,
  odoo_id: null,
};

const LIVE_BODY = {
  rows: [ROW, { ...ROW, id: 6, code: 'KG', name: 'Kilogram', category: 'Berat', odoo_id: 10, active: false }],
  total_count: 2,
  has_more: false,
  next_cursor: null,
};

const SAVED_BODY = { ...ROW, sync_record_id: 7, task_id: 'task-uom-1', queued: true };

const INPUT: MasterUomInput = {
  code: ' PCS ',
  name: ' Pieces ',
  category: ' Unit ',
  uom_type: 'smaller',
  factor: 0.5,
  rounding: 0.001,
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

describe('H1.2 — MODE & path master UoM', () => {
  it('MODE.masterUoms = real (endpoint H1.2 ADA di backend)', () => {
    expect(MODE['masterUoms']).toBe('real');
    expect(MASTER_UOMS_PATH).toBe('/master/uoms/');
  });

  it('buildMasterUomsPath: default tanpa query, param terisi saja yang dikirim', () => {
    expect(buildMasterUomsPath()).toBe('/master/uoms/');
    expect(buildMasterUomsPath({ search: 'pcs' })).toBe('/master/uoms/?search=pcs');
    expect(buildMasterUomsPath({ active: true })).toBe('/master/uoms/?active=true');
    expect(buildMasterUomsPath({ active: false })).toBe('/master/uoms/?active=false');
    expect(buildMasterUomsPath({ limit: 200, cursor: 20, active: null })).toBe(
      '/master/uoms/?limit=200&cursor=20',
    );
  });

  it('fetchUoms memanggil path terfilter & mengembalikan envelope ListPage', async () => {
    const { client, requests } = stubClient(LIVE_BODY);

    const page = await fetchUoms(client, { search: 'pcs', active: true, limit: 50 });

    expect(requests).toEqual([
      { path: '/master/uoms/?search=pcs&active=true&limit=50', method: 'GET' },
    ]);
    expect(page.rows).toHaveLength(2);
    expect(page.total_count).toBe(2);
    expect(page.has_more).toBe(false);
    expect(page.next_cursor).toBeNull();
    expect(page.rows[0]).toEqual(ROW);
    expect(page.rows[1]?.odoo_id).toBe(10);
    expect(page.rows[1]?.active).toBe(false);
  });
});

describe('H1.2 — reader baris & page', () => {
  it('readMasterUomRow: baris rusak dibuang; faktor/rounding aman', () => {
    expect(readMasterUomRow({ code: 'PCS' })).toBeNull();
    expect(readMasterUomRow({ id: '5' })).toBeNull();
    expect(readMasterUomRow(null)).toBeNull();
    expect(readMasterUomRow({ id: 1, factor: 'x', rounding: null })?.factor).toBe(0);
  });

  it('readUomType: hanya bigger/smaller/reference; lain → reference', () => {
    expect(readUomType('bigger')).toBe('bigger');
    expect(readUomType('smaller')).toBe('smaller');
    expect(readUomType('reference')).toBe('reference');
    expect(readUomType('BESAR')).toBe('reference');
    expect(readUomType(undefined)).toBe('reference');
  });

  it('readMasterUomPage / readMasterUomSaved', () => {
    expect(readMasterUomPage(null)).toBeNull();
    expect(readMasterUomPage({ rows: 'bukan-array' })).toBeNull();
    expect(readMasterUomPage(LIVE_BODY)?.rows).toHaveLength(2);

    expect(readMasterUomSaved(SAVED_BODY)).toEqual({
      ...ROW,
      sync_record_id: 7,
      task_id: 'task-uom-1',
      queued: true,
    });
    expect(readMasterUomSaved({ id: 1, queued: 'yes' })?.queued).toBe(false);
  });

  it('toMasterUomBody: trim teks, angka & uom_type apa adanya', () => {
    expect(toMasterUomBody(INPUT)).toEqual({
      code: 'PCS',
      name: 'Pieces',
      category: 'Unit',
      uom_type: 'smaller',
      factor: 0.5,
      rounding: 0.001,
      active: false,
    });
  });
});

describe('H1.2 — detail & tulis (POST/PUT/DELETE)', () => {
  it('fetchUom memanggil `/master/uoms/<id>/` dan melempar pesan backend saat 404', async () => {
    const { client, requests } = stubClient(ROW);

    expect(await fetchUom(client, 5)).toEqual(ROW);
    expect(requests).toEqual([{ path: '/master/uoms/5/', method: 'GET' }]);

    await expect(fetchUom(failingClient(404, 'UoM 9 tidak ditemukan.'), 9)).rejects.toThrow(
      /tidak ditemukan/,
    );
  });

  it('createUom: POST body + parse jawaban saved', async () => {
    const { client, requests } = stubClient(SAVED_BODY);

    const saved = await createUom(client, INPUT);

    expect(requests).toEqual([
      { path: '/master/uoms/', method: 'POST', body: toMasterUomBody(INPUT) },
    ]);
    expect(saved.id).toBe(5);
    expect(saved.sync_record_id).toBe(7);
    expect(saved.task_id).toBe('task-uom-1');
    expect(saved.queued).toBe(true);
  });

  it('createUom 400 (kode duplikat) → melempar pesan backend', async () => {
    await expect(
      createUom(failingClient(400, "Kode UoM 'PCS' sudah dipakai UoM lain."), INPUT),
    ).rejects.toThrow(/sudah dipakai/);
  });

  it('createUom 403 (bukan admin/owner) → melempar pesan backend', async () => {
    await expect(createUom(failingClient(403, 'HTTP 403'), INPUT)).rejects.toThrow(/403/);
  });

  it('updateUom: PUT ke `/master/uoms/<id>/`', async () => {
    const { client, requests } = stubClient({ ...SAVED_BODY, name: 'Pieces baru' });

    const saved = await updateUom(client, 5, INPUT);

    expect(requests).toEqual([
      { path: '/master/uoms/5/', method: 'PUT', body: toMasterUomBody(INPUT) },
    ]);
    expect(saved.name).toBe('Pieces baru');
  });

  it('deleteUom: DELETE (soft delete di backend) & melempar saat gagal', async () => {
    const { client, requests } = stubClient({ id: 5, active: false, deleted: true });

    await deleteUom(client, 5);
    expect(requests).toEqual([{ path: '/master/uoms/5/', method: 'DELETE', body: undefined }]);

    await expect(deleteUom(failingClient(403, 'HTTP 403'), 5)).rejects.toThrow(/403/);
  });

  it('bentuk respons simpan tak dikenali → melempar pesan jelas', async () => {
    const { client } = stubClient({ ok: true });

    await expect(createUom(client, INPUT)).rejects.toThrow(/tidak dikenali/);
  });
});
