import { describe, expect, it } from 'vitest';
import {
  buildMasterProductionLinesPath,
  createProductionLine,
  deleteProductionLine,
  fetchProductionLine,
  fetchProductionLines,
  MASTER_PRODUCTION_LINES_PATH,
  PRODUCTION_LINES_LIMIT_DEFAULT,
  PRODUCTION_LINES_LIMIT_MAX,
  readMasterProductionLineDetail,
  readMasterProductionLinePage,
  readMasterProductionLineRow,
  readMasterProductionLineSaved,
  toMasterProductionLineBody,
  updateProductionLine,
} from '@/api/masterProductionLines';
import { MODE, isReal } from '@/api/_adapter';
import type { ApiClient, ApiResponse } from '@/integrations/api-client';
import type {
  MasterProductionLineInput,
  MasterProductionLineRow,
} from '@/types/master-production-line';

/**
 * H1.8 — adapter master Production Line (`/api/v1/master/production-lines/`).
 *
 * Bentuk = PERSIS `django_app/master/production_line_services.py::production_line_row`
 * (+ detail: `work_centers[]`, `active_bundles_count`): `{id, code, name, description,
 * capability_tags, work_centers_count, work_center_ids, work_center_names,
 * allocation_rules_count, active, created_at, updated_at}` + `{sync_record_id,
 * sync_status, task_id, queued, mes_only}` saat simpan. **Tanpa `odoo_id`** — MES-only.
 */

const ROW: MasterProductionLineRow = {
  id: 3,
  code: 'LINE-A',
  name: 'Lini Jahit A',
  description: 'Lini utama shift 1',
  capability_tags: ['JAHIT', 'OBRAS'],
  work_centers_count: 2,
  work_center_ids: [5, 6],
  work_center_names: ['CUTTING-1', 'SEWING-1'],
  allocation_rules_count: 1,
  active: true,
  created_at: '2026-10-11T04:00:00+00:00',
  updated_at: '2026-10-11T04:00:00+00:00',
};

const SAVED_BODY = {
  ...ROW,
  work_centers: [
    { id: 5, code: 'CUTTING-1', name: 'Stasiun CUTTING-1' },
    { id: 6, code: 'SEWING-1', name: 'Stasiun SEWING-1' },
  ],
  active_bundles_count: 0,
  sync_record_id: 91,
  sync_status: 'SKIPPED',
  task_id: null,
  queued: false,
  mes_only: true,
};

const INPUT: MasterProductionLineInput = {
  code: ' LINE-A ',
  name: ' Lini Jahit A ',
  description: ' Lini utama shift 1 ',
  capability_tags: ['JAHIT', 'OBRAS'],
  work_center_ids: [5, 6],
  active: false,
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

describe('H1.8 — MODE, path & parsing baris', () => {
  it('MODE.masterProductionLines = real + path/limit + query builder', () => {
    expect(MODE['masterProductionLines']).toBe('real');
    expect(isReal('masterProductionLines')).toBe(true);
    expect(MASTER_PRODUCTION_LINES_PATH).toBe('/master/production-lines/');
    expect(PRODUCTION_LINES_LIMIT_DEFAULT).toBe(50);
    expect(PRODUCTION_LINES_LIMIT_MAX).toBe(200);

    expect(buildMasterProductionLinesPath()).toBe('/master/production-lines/');
    expect(
      buildMasterProductionLinesPath({
        search: 'jahit',
        capability_tag: 'JAHIT',
        work_center: 6,
        active: false,
        limit: 200,
        cursor: 20,
      }),
    ).toBe(
      '/master/production-lines/?search=jahit&capability_tag=JAHIT&work_center=6&active=false&limit=200&cursor=20',
    );
    expect(buildMasterProductionLinesPath({ active: null, search: '' })).toBe(
      '/master/production-lines/',
    );
  });

  it('readMasterProductionLineRow memetakan seluruh field & defensif tanpa id angka', () => {
    expect(readMasterProductionLineRow(ROW)).toEqual(ROW);
    expect(readMasterProductionLineRow(null)).toBeNull();
    expect(readMasterProductionLineRow({ id: '3' })).toBeNull();

    const minimal = readMasterProductionLineRow({ id: 1, work_center_ids: ['x', 2] });
    expect(minimal?.capability_tags).toEqual([]);
    expect(minimal?.work_center_ids).toEqual([2]); // non-angka dibuang
    expect(minimal?.work_centers_count).toBe(0);
    expect(minimal?.active).toBe(false);
  });

  it('detail menambah work_centers[] + bundle aktif; saved menambah jejak sync MES-only', () => {
    const detail = readMasterProductionLineDetail(SAVED_BODY);

    expect(detail?.work_centers).toEqual([
      { id: 5, code: 'CUTTING-1', name: 'Stasiun CUTTING-1' },
      { id: 6, code: 'SEWING-1', name: 'Stasiun SEWING-1' },
    ]);
    expect(detail?.active_bundles_count).toBe(0);
    expect(
      readMasterProductionLineDetail({ ...ROW, work_centers: [{ code: 'TANPA-ID' }] })?.work_centers,
    ).toEqual([]);

    const saved = readMasterProductionLineSaved(SAVED_BODY);
    expect(saved?.sync_record_id).toBe(91);
    expect(saved?.sync_status).toBe('SKIPPED');
    expect(saved?.task_id).toBeNull();
    expect(saved?.queued).toBe(false);
    expect(saved?.mes_only).toBe(true);
  });

  it('page `null` kalau rows bukan array; body trim teks (tanpa odoo_id)', () => {
    expect(readMasterProductionLinePage(null)).toBeNull();
    expect(readMasterProductionLinePage({ rows: 'x' })).toBeNull();
    expect(
      readMasterProductionLinePage({
        rows: [ROW],
        total_count: 1,
        has_more: false,
        next_cursor: null,
      })?.rows[0]?.code,
    ).toBe('LINE-A');

    expect(toMasterProductionLineBody(INPUT)).toEqual({
      code: 'LINE-A',
      name: 'Lini Jahit A',
      description: 'Lini utama shift 1',
      capability_tags: ['JAHIT', 'OBRAS'],
      work_center_ids: [5, 6],
      active: false,
    });
    expect('odoo_id' in toMasterProductionLineBody(INPUT)).toBe(false);
  });
});

describe('H1.8 — list & tulis (POST/PUT/DELETE)', () => {
  it('fetchProductionLines memanggil query; fetchProductionLine detail + error 404', async () => {
    const { client, requests } = stubClient({
      rows: [ROW],
      total_count: 1,
      has_more: false,
      next_cursor: null,
    });

    const page = await fetchProductionLines(client, { capability_tag: 'JAHIT', limit: 50 });
    expect(requests).toEqual([
      { path: '/master/production-lines/?capability_tag=JAHIT&limit=50', method: 'GET' },
    ]);
    expect(page.rows[0]?.work_center_names).toEqual(['CUTTING-1', 'SEWING-1']);

    const detailClient = stubClient(SAVED_BODY);
    const detail = await fetchProductionLine(detailClient.client, 3);
    expect(detailClient.requests).toEqual([
      { path: '/master/production-lines/3/', method: 'GET' },
    ]);
    expect(detail.work_centers).toHaveLength(2);

    await expect(
      fetchProductionLine(failingClient(404, 'Production line 9 tidak ditemukan.'), 9),
    ).rejects.toThrow(/tidak ditemukan/);
  });

  it('createProductionLine: POST body (work_center_ids replace penuh) + saved MES-only', async () => {
    const { client, requests } = stubClient(SAVED_BODY);

    const saved = await createProductionLine(client, INPUT);

    expect(requests).toEqual([
      {
        path: '/master/production-lines/',
        method: 'POST',
        body: toMasterProductionLineBody(INPUT),
      },
    ]);
    expect(saved.id).toBe(3);
    expect(saved.sync_status).toBe('SKIPPED');
    expect(saved.mes_only).toBe(true);
    expect(saved.task_id).toBeNull();
  });

  it('createProductionLine 400/403 → melempar pesan backend; bentuk aneh → pesan jelas', async () => {
    await expect(
      createProductionLine(
        failingClient(400, "Kode production line 'LINE-A' sudah dipakai line lain."),
        INPUT,
      ),
    ).rejects.toThrow(/sudah dipakai/);
    await expect(createProductionLine(failingClient(403, 'HTTP 403'), INPUT)).rejects.toThrow(
      /403/,
    );

    const { client } = stubClient({ ok: true });
    await expect(createProductionLine(client, INPUT)).rejects.toThrow(/tidak dikenali/);
  });

  it('updateProductionLine PUT & deleteProductionLine DELETE + guard bundle aktif 400', async () => {
    const { client, requests } = stubClient({ ...SAVED_BODY, name: 'Lini Baru' });

    const saved = await updateProductionLine(client, 3, INPUT);
    expect(requests).toEqual([
      {
        path: '/master/production-lines/3/',
        method: 'PUT',
        body: toMasterProductionLineBody(INPUT),
      },
    ]);
    expect(saved.name).toBe('Lini Baru');

    const deleteClient = stubClient({ id: 3, active: false, deleted: true });
    await deleteProductionLine(deleteClient.client, 3);
    expect(deleteClient.requests).toEqual([
      { path: '/master/production-lines/3/', method: 'DELETE', body: undefined },
    ]);

    await expect(
      deleteProductionLine(
        failingClient(400, "Production line 'LINE-A' masih dipakai 2 bundle aktif."),
        3,
      ),
    ).rejects.toThrow(/bundle aktif/);
  });
});
