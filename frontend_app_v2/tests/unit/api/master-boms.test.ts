import { describe, expect, it } from 'vitest';
import {
  BOMS_LIMIT_DEFAULT,
  BOMS_LIMIT_MAX,
  buildMasterBomsPath,
  createBom,
  deleteBom,
  fetchBom,
  fetchBoms,
  MASTER_BOMS_PATH,
  readMasterBomDetail,
  readMasterBomLineRow,
  readMasterBomPage,
  readMasterBomRow,
  readMasterBomSaved,
  toMasterBomBody,
  updateBom,
} from '@/api/masterBoms';
import { MODE, isReal } from '@/api/_adapter';
import type { ApiClient, ApiResponse } from '@/integrations/api-client';
import type { MasterBomInput, MasterBomRow } from '@/types/master-bom';

/**
 * H1.5 — adapter master BOM (`/api/v1/master/boms/`).
 *
 * Bentuk = PERSIS `django_app/master/bom_services.py::bom_row`/`bom_detail_row`/
 * `line_row`: `{id, code, name, product_id, product_code, product_name, output_qty,
 * uom_id, uom_code, notes, active, odoo_id, lines_count, created_at, updated_at}`
 * + `lines[]` di detail + `{sync_record_id, task_id, queued}` pada POST/PUT.
 * Kuantitas baris diekspor sebagai `qty` (kolom DB-nya `product_qty`).
 */

const LINE = {
  id: 41,
  product_id: 9,
  product_code: 'KAIN-COTTON',
  product_name: 'Kain Cotton',
  qty: 1.5,
  uom_id: 3,
  uom_code: 'PCS',
  sequence: 10,
  notes: '',
  active: true,
  odoo_id: null,
};

const ROW: MasterBomRow = {
  id: 12,
  code: 'BOM-KTS-EXPORT-L',
  name: 'BOM Kaos Export L',
  product_id: 5,
  product_code: 'KTS-EXPORT-L',
  product_name: 'Kaos Export L',
  output_qty: 1,
  uom_id: 3,
  uom_code: 'PCS',
  notes: '',
  active: true,
  odoo_id: null,
  lines_count: 1,
  created_at: '2026-10-11T02:00:00+00:00',
  updated_at: '2026-10-11T02:00:00+00:00',
};

const DETAIL_BODY = { ...ROW, lines: [LINE] };

const LIVE_BODY = {
  rows: [
    ROW,
    {
      ...ROW,
      id: 13,
      code: 'BOM-KAIN',
      name: 'BOM Kain',
      product_id: null,
      product_code: null,
      product_name: null,
      output_qty: 10,
      odoo_id: 21,
      lines_count: 0,
      active: false,
    },
  ],
  total_count: 2,
  has_more: false,
  next_cursor: null,
};

const SAVED_BODY = { ...DETAIL_BODY, sync_record_id: 77, task_id: 'task-bom-1', queued: true };

const INPUT: MasterBomInput = {
  code: ' BOM-KTS ',
  name: ' BOM Kaos ',
  product_id: 5,
  output_qty: 2,
  uom_id: 3,
  notes: ' catatan ',
  active: false,
  lines: [
    { id: 41, odoo_id: null, product_id: 9, qty: 1.5, uom_id: 3, sequence: 10, notes: ' a ' },
    { product_id: 7, qty: 0.5, uom_id: null, sequence: 20, notes: '' },
  ],
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


describe('H1.5 — MODE & path master BOM', () => {
  it('MODE.masterBoms = real (endpoint sudah ada) + konstanta path/limit', () => {
    expect(MODE['masterBoms']).toBe('real');
    expect(isReal('masterBoms')).toBe(true);
    expect(MASTER_BOMS_PATH).toBe('/master/boms/');
    expect(BOMS_LIMIT_DEFAULT).toBe(50);
    expect(BOMS_LIMIT_MAX).toBe(200);
  });

  it('buildMasterBomsPath: param kosong dilewati, `false` tetap dikirim', () => {
    expect(buildMasterBomsPath()).toBe('/master/boms/');
    expect(
      buildMasterBomsPath({
        search: 'kaos',
        product_id: 5,
        active: false,
        limit: 200,
        cursor: 20,
      }),
    ).toBe('/master/boms/?search=kaos&product_id=5&active=false&limit=200&cursor=20');
    expect(buildMasterBomsPath({ product_id: null, active: null })).toBe('/master/boms/');
  });
});

describe('H1.5 — parsing baris (defensif, tanpa cast)', () => {
  it('readMasterBomRow: memetakan seluruh field + `null` tanpa id angka', () => {
    expect(readMasterBomRow(ROW)).toEqual(ROW);
    expect(readMasterBomRow(null)).toBeNull();
    expect(readMasterBomRow({ id: '12' })).toBeNull();

    expect(readMasterBomRow({ id: 1 })).toEqual({
      id: 1,
      code: '',
      name: '',
      product_id: null,
      product_code: null,
      product_name: null,
      output_qty: 0,
      uom_id: null,
      uom_code: null,
      notes: '',
      active: false,
      odoo_id: null,
      lines_count: 0,
      created_at: null,
      updated_at: null,
    });
  });

  it('readMasterBomLineRow: qty + sequence + odoo_id; `null` tanpa id', () => {
    expect(readMasterBomLineRow(LINE)).toEqual(LINE);
    expect(readMasterBomLineRow({ id: 1 })?.qty).toBe(0);
    expect(readMasterBomLineRow({ id: 1 })?.sequence).toBe(0);
    expect(readMasterBomLineRow({ id: 1 })?.odoo_id).toBeNull();
    expect(readMasterBomLineRow(null)).toBeNull();
  });

  it('readMasterBomDetail: `lines[]` diparse; item rusak dibuang; tanpa lines → []', () => {
    expect(readMasterBomDetail(DETAIL_BODY)?.lines).toEqual([LINE]);
    expect(readMasterBomDetail({ ...ROW, lines: [LINE, { id: 'x' }] })?.lines).toEqual([LINE]);
    expect(readMasterBomDetail({ ...ROW, lines: 'bukan-array' })?.lines).toEqual([]);
    expect(readMasterBomDetail(ROW)?.lines).toEqual([]);
    expect(readMasterBomDetail(null)).toBeNull();
  });

  it('readMasterBomPage / readMasterBomSaved', () => {
    expect(readMasterBomPage(null)).toBeNull();
    expect(readMasterBomPage({ rows: 'bukan-array' })).toBeNull();
    expect(readMasterBomPage(LIVE_BODY)?.rows).toHaveLength(2);
    expect(readMasterBomPage(LIVE_BODY)?.rows[1]?.lines_count).toBe(0);

    const saved = readMasterBomSaved(SAVED_BODY);
    expect(saved?.sync_record_id).toBe(77);
    expect(saved?.task_id).toBe('task-bom-1');
    expect(saved?.queued).toBe(true);
    expect(saved?.lines).toHaveLength(1);
    expect(readMasterBomSaved({ id: 1 })?.queued).toBe(false);
  });

  it('toMasterBomBody: trim teks + baris dipetakan (id/odoo_id null dibuang)', () => {
    expect(toMasterBomBody(INPUT)).toEqual({
      code: 'BOM-KTS',
      name: 'BOM Kaos',
      product_id: 5,
      output_qty: 2,
      uom_id: 3,
      notes: 'catatan',
      active: false,
      lines: [
        { id: 41, product_id: 9, qty: 1.5, uom_id: 3, sequence: 10, notes: 'a' },
        { product_id: 7, qty: 0.5, uom_id: null, sequence: 20, notes: '' },
      ],
    });
  });
});

describe('H1.5 — detail & tulis (POST/PUT/DELETE)', () => {
  it('fetchBoms memanggil path + query di `/master/boms/`', async () => {
    const { client, requests } = stubClient(LIVE_BODY);

    const page = await fetchBoms(client, { search: 'kaos', active: true, limit: 50 });

    expect(requests).toEqual([
      { path: '/master/boms/?search=kaos&active=true&limit=50', method: 'GET' },
    ]);
    expect(page.total_count).toBe(2);
    expect(page.rows[0]?.code).toBe('BOM-KTS-EXPORT-L');
  });

  it('fetchBom memanggil `/master/boms/<id>/` + melempar pesan backend 404', async () => {
    const { client, requests } = stubClient(DETAIL_BODY);

    const detail = await fetchBom(client, 12);
    expect(requests).toEqual([{ path: '/master/boms/12/', method: 'GET' }]);
    expect(detail.lines).toHaveLength(1);

    await expect(fetchBom(failingClient(404, 'BOM 9 tidak ditemukan.'), 9)).rejects.toThrow(
      /tidak ditemukan/,
    );
  });

  it('createBom: POST body + parse jawaban saved (termasuk lines)', async () => {
    const { client, requests } = stubClient(SAVED_BODY);

    const saved = await createBom(client, INPUT);

    expect(requests).toEqual([
      { path: '/master/boms/', method: 'POST', body: toMasterBomBody(INPUT) },
    ]);
    expect(saved.id).toBe(12);
    expect(saved.sync_record_id).toBe(77);
    expect(saved.queued).toBe(true);
    expect(saved.lines[0]?.qty).toBe(1.5);
  });

  it('createBom 400 (siklus/validasi) → melempar pesan backend', async () => {
    await expect(
      createBom(failingClient(400, 'Siklus BOM terdeteksi: produk KAIN muncul lagi.'), INPUT),
    ).rejects.toThrow(/Siklus BOM/);
  });

  it('createBom 403 (bukan admin/owner) → melempar pesan backend', async () => {
    await expect(createBom(failingClient(403, 'HTTP 403'), INPUT)).rejects.toThrow(/403/);
  });

  it('updateBom: PUT ke `/master/boms/<id>/` (lines menggantikan baris aktif)', async () => {
    const { client, requests } = stubClient({ ...SAVED_BODY, name: 'BOM Kaos Baru' });

    const saved = await updateBom(client, 12, INPUT);

    expect(requests).toEqual([
      { path: '/master/boms/12/', method: 'PUT', body: toMasterBomBody(INPUT) },
    ]);
    expect(saved.name).toBe('BOM Kaos Baru');
  });

  it('deleteBom: DELETE (soft delete) & melempar error HTTP', async () => {
    const { client, requests } = stubClient({ id: 12, active: false, deleted: true });

    await deleteBom(client, 12);
    expect(requests).toEqual([{ path: '/master/boms/12/', method: 'DELETE', body: undefined }]);

    await expect(deleteBom(failingClient(403, 'HTTP 403'), 12)).rejects.toThrow(/403/);
  });

  it('bentuk respons simpan tak dikenali → melempar pesan jelas', async () => {
    const { client } = stubClient({ ok: true });

    await expect(createBom(client, INPUT)).rejects.toThrow(/tidak dikenali/);
  });
});
