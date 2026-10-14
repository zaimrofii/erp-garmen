import { describe, expect, it } from 'vitest';
import {
  buildMasterWorkCentersPath,
  createWorkCenter,
  deleteWorkCenter,
  fetchWorkCenter,
  fetchWorkCenters,
  MASTER_WORK_CENTERS_PATH,
  readMasterWorkCenterDetail,
  readMasterWorkCenterPage,
  readMasterWorkCenterRow,
  readMasterWorkCenterSaved,
  toMasterWorkCenterBody,
  updateWorkCenter,
  WORK_CENTERS_LIMIT_DEFAULT,
  WORK_CENTERS_LIMIT_MAX,
} from '@/api/masterWorkCenters';
import { MODE, isReal } from '@/api/_adapter';
import { SYNC_STATUS_LABELS } from '@/lib/state-display';
import type { ApiClient, ApiResponse } from '@/integrations/api-client';
import type { MasterWorkCenterInput, MasterWorkCenterRow } from '@/types/master-work-center';

/**
 * H1.7 — adapter master Work Center (`/api/v1/master/work-centers/`).
 *
 * Bentuk = PERSIS `django_app/master/api.py::work_center_row` (+ detail:
 * `active_bundles_count`, `production_lines`): `{id, code, name, wc_type,
 * capability_tags, capacity_per_hour, description, active, config, created_at,
 * updated_at}` + `{sync_record_id, sync_status, task_id, queued, mes_only}` saat simpan.
 * **Tanpa `odoo_id`** — H1.7 MES-only (tidak push/pull Odoo).
 */

const ROW: MasterWorkCenterRow = {
  id: 5,
  code: 'SEWING-1',
  name: 'Stasiun Jahit 1',
  wc_type: 'SEWING',
  capability_tags: ['JAHIT_LURUS', 'OBRAS'],
  capacity_per_hour: 40.5,
  description: 'Meja jahit utama',
  active: true,
  config: { target_per_day: 320 },
  created_at: '2026-10-11T03:00:00+00:00',
  updated_at: '2026-10-11T03:00:00+00:00',
};

const LIVE_BODY = {
  rows: [
    ROW,
    {
      ...ROW,
      id: 6,
      code: 'QC-1',
      name: 'Inspeksi',
      wc_type: 'QC',
      capability_tags: [],
      capacity_per_hour: 0,
      description: '',
      active: false,
      config: {},
    },
  ],
  total_count: 2,
  has_more: false,
  next_cursor: null,
};

const SAVED_BODY = {
  ...ROW,
  active_bundles_count: 1,
  production_lines: [{ id: 3, code: 'LINE-A', name: 'Lini A' }],
  sync_record_id: 77,
  sync_status: 'SKIPPED',
  task_id: null,
  queued: false,
  mes_only: true,
};

const INPUT: MasterWorkCenterInput = {
  code: ' SEWING-1 ',
  name: ' Stasiun Jahit 1 ',
  wc_type: ' SEWING ',
  capability_tags: [' JAHIT_LURUS ', '', 'OBRAS', 'obras'],
  capacity_per_hour: 40.5,
  description: ' Meja jahit utama ',
  active: true,
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

describe('H1.7 — MODE, path & label status sync', () => {
  it('MODE.masterWorkCenters = real + konstanta path/limit', () => {
    expect(MODE['masterWorkCenters']).toBe('real');
    expect(isReal('masterWorkCenters')).toBe(true);
    expect(MASTER_WORK_CENTERS_PATH).toBe('/master/work-centers/');
    expect(WORK_CENTERS_LIMIT_DEFAULT).toBe(50);
    expect(WORK_CENTERS_LIMIT_MAX).toBe(200);
  });

  it('label SKIPPED baru tersedia (MES-only) tanpa mengubah status lain', () => {
    expect(SYNC_STATUS_LABELS['SKIPPED']).toBe('Dilewati');
    expect(SYNC_STATUS_LABELS['PENDING']).toBe('Menunggu');
    expect(SYNC_STATUS_LABELS['SENT']).toBe('Terkirim');
    expect(SYNC_STATUS_LABELS['FAILED']).toBe('Gagal');
    expect(SYNC_STATUS_LABELS['DUPLICATE']).toBe('Duplikat');
  });

  it('buildMasterWorkCentersPath: param kosong dilewati, `false` tetap dikirim', () => {
    expect(buildMasterWorkCentersPath()).toBe('/master/work-centers/');
    expect(
      buildMasterWorkCentersPath({
        search: 'jahit',
        wc_type: 'SEWING',
        active: false,
        limit: 200,
        cursor: 20,
      }),
    ).toBe('/master/work-centers/?search=jahit&wc_type=SEWING&active=false&limit=200&cursor=20');
    expect(buildMasterWorkCentersPath({ active: null, wc_type: '', search: '' })).toBe(
      '/master/work-centers/',
    );
  });
});

describe('H1.7 — parsing baris (defensif, tanpa cast)', () => {
  it('readMasterWorkCenterRow: memetakan seluruh field + `null` tanpa id angka', () => {
    expect(readMasterWorkCenterRow(ROW)).toEqual(ROW);
    expect(readMasterWorkCenterRow(null)).toBeNull();
    expect(readMasterWorkCenterRow({ id: '5' })).toBeNull();

    expect(readMasterWorkCenterRow({ id: 1 })).toEqual({
      id: 1,
      code: '',
      name: '',
      wc_type: '',
      capability_tags: [],
      capacity_per_hour: 0,
      description: '',
      active: false,
      config: {},
      created_at: null,
      updated_at: null,
    });
  });

  it('readMasterWorkCenterRow: tag non-string dibuang & config non-objek jadi {}', () => {
    const row = readMasterWorkCenterRow({
      id: 9,
      capability_tags: ['OBRAS', 7, null, 'QC'],
      config: 'bukan-objek',
    });

    expect(row?.capability_tags).toEqual(['OBRAS', 'QC']);
    expect(row?.config).toEqual({});
  });

  it('detail menambah bundle aktif & lini; saved menambah jejak sync MES-only', () => {
    expect(readMasterWorkCenterDetail(ROW)?.active_bundles_count).toBe(0);
    expect(readMasterWorkCenterDetail(ROW)?.production_lines).toEqual([]);
    expect(readMasterWorkCenterDetail(null)).toBeNull();

    const detail = readMasterWorkCenterDetail({
      ...ROW,
      active_bundles_count: 2,
      production_lines: [{ id: 3, code: 'LINE-A', name: 'Lini A' }, { code: 'TANPA-ID' }],
    });
    expect(detail?.active_bundles_count).toBe(2);
    expect(detail?.production_lines).toEqual([{ id: 3, code: 'LINE-A', name: 'Lini A' }]);

    const saved = readMasterWorkCenterSaved(SAVED_BODY);
    expect(saved?.sync_record_id).toBe(77);
    expect(saved?.sync_status).toBe('SKIPPED');
    expect(saved?.task_id).toBeNull();
    expect(saved?.queued).toBe(false);
    expect(saved?.mes_only).toBe(true);
  });

  it('readMasterWorkCenterPage: `null` kalau rows bukan array; 2 baris diparse', () => {
    expect(readMasterWorkCenterPage(null)).toBeNull();
    expect(readMasterWorkCenterPage({ rows: 'bukan-array' })).toBeNull();
    expect(readMasterWorkCenterPage(LIVE_BODY)?.rows).toHaveLength(2);
    expect(readMasterWorkCenterPage(LIVE_BODY)?.rows[1]?.wc_type).toBe('QC');
    expect(readMasterWorkCenterPage(LIVE_BODY)?.total_count).toBe(2);
  });

  it('toMasterWorkCenterBody: trim teks, tag & kapasitas apa adanya (tanpa odoo_id)', () => {
    expect(toMasterWorkCenterBody(INPUT)).toEqual({
      code: 'SEWING-1',
      name: 'Stasiun Jahit 1',
      wc_type: 'SEWING',
      capability_tags: [' JAHIT_LURUS ', '', 'OBRAS', 'obras'],
      capacity_per_hour: 40.5,
      description: 'Meja jahit utama',
      active: true,
    });
    expect('odoo_id' in toMasterWorkCenterBody(INPUT)).toBe(false);
  });
});

describe('H1.7 — detail & tulis (POST/PUT/DELETE)', () => {
  it('fetchWorkCenters memanggil path + query di `/master/work-centers/`', async () => {
    const { client, requests } = stubClient(LIVE_BODY);

    const page = await fetchWorkCenters(client, { search: 'jahit', wc_type: 'SEWING', limit: 50 });

    expect(requests).toEqual([
      { path: '/master/work-centers/?search=jahit&wc_type=SEWING&limit=50', method: 'GET' },
    ]);
    expect(page.total_count).toBe(2);
    expect(page.rows[0]?.name).toBe('Stasiun Jahit 1');
  });

  it('fetchWorkCenter memanggil detail + melempar pesan backend 404', async () => {
    const { client, requests } = stubClient({
      ...ROW,
      active_bundles_count: 3,
      production_lines: [{ id: 3, code: 'LINE-A', name: 'Lini A' }],
    });

    const detail = await fetchWorkCenter(client, 5);
    expect(requests).toEqual([{ path: '/master/work-centers/5/', method: 'GET' }]);
    expect(detail.active_bundles_count).toBe(3);
    expect(detail.production_lines).toHaveLength(1);

    await expect(
      fetchWorkCenter(failingClient(404, 'Work center 9 tidak ditemukan.'), 9),
    ).rejects.toThrow(/tidak ditemukan/);
  });

  it('createWorkCenter: POST body + parse jawaban saved (MES-only)', async () => {
    const { client, requests } = stubClient(SAVED_BODY);

    const saved = await createWorkCenter(client, INPUT);

    expect(requests).toEqual([
      { path: '/master/work-centers/', method: 'POST', body: toMasterWorkCenterBody(INPUT) },
    ]);
    expect(saved.id).toBe(5);
    expect(saved.sync_status).toBe('SKIPPED');
    expect(saved.mes_only).toBe(true);
    expect(saved.queued).toBe(false);
  });

  it('createWorkCenter 400 (kode duplikat) → melempar pesan backend', async () => {
    await expect(
      createWorkCenter(
        failingClient(400, "Kode work center 'SEWING-1' sudah dipakai work center lain."),
        INPUT,
      ),
    ).rejects.toThrow(/sudah dipakai/);
  });

  it('createWorkCenter 403 (bukan admin/owner) → melempar pesan backend', async () => {
    await expect(createWorkCenter(failingClient(403, 'HTTP 403'), INPUT)).rejects.toThrow(/403/);
  });

  it('updateWorkCenter: PUT ke `/master/work-centers/<id>/`', async () => {
    const { client, requests } = stubClient({ ...SAVED_BODY, name: 'Stasiun Jahit 1 (baru)' });

    const saved = await updateWorkCenter(client, 5, INPUT);

    expect(requests).toEqual([
      { path: '/master/work-centers/5/', method: 'PUT', body: toMasterWorkCenterBody(INPUT) },
    ]);
    expect(saved.name).toBe('Stasiun Jahit 1 (baru)');
  });

  it('deleteWorkCenter: DELETE (soft delete) & melempar 400 guard bundle aktif', async () => {
    const { client, requests } = stubClient({ id: 5, active: false, deleted: true });

    await deleteWorkCenter(client, 5);
    expect(requests).toEqual([
      { path: '/master/work-centers/5/', method: 'DELETE', body: undefined },
    ]);

    await expect(
      deleteWorkCenter(
        failingClient(400, "Work center 'SEWING-1' masih dipakai 2 bundle aktif."),
        5,
      ),
    ).rejects.toThrow(/bundle aktif/);
  });

  it('bentuk respons simpan tak dikenali → melempar pesan jelas', async () => {
    const { client } = stubClient({ ok: true });

    await expect(createWorkCenter(client, INPUT)).rejects.toThrow(/tidak dikenali/);
  });
});
