import { describe, expect, it } from 'vitest';
import {
  addRoutingStep,
  buildMasterRoutingsPath,
  createRouting,
  deleteRouting,
  fetchRouting,
  fetchRoutings,
  MASTER_ROUTINGS_PATH,
  readMasterRoutingDetail,
  readMasterRoutingPage,
  readMasterRoutingRow,
  readMasterRoutingSaved,
  readMasterRoutingStepRow,
  removeRoutingStep,
  ROUTINGS_LIMIT_DEFAULT,
  ROUTINGS_LIMIT_MAX,
  routingDetailPath,
  routingStepPath,
  routingStepsPath,
  stripUndefined,
  toMasterRoutingBody,
  toMasterRoutingCreateBody,
  toMasterRoutingStepBody,
  updateRouting,
  updateRoutingStep,
} from '@/api/masterRoutings';
import {
  createMasterRouting as realCreateRouting,
  createRoutingStep as realCreateStep,
  deleteMasterRouting as realDeleteRouting,
  deleteRoutingStep as realDeleteStep,
  fetchMasterRouting as realFetchRouting,
  fetchMasterRoutings as realFetchRoutings,
  updateMasterRouting as realUpdateRouting,
  updateRoutingStep as realUpdateStep,
} from '@/api/real/masterRoutings';
import { MODE, isReal } from '@/api/_adapter';
import { SETTINGS_ROUTING_PATH } from '@/api/real/settingsRouting';
import type { ApiClient, ApiResponse } from '@/integrations/api-client';

/**
 * H1.9 — adapter master Routing DAG.
 *
 * Endpoint = **B22 yang di-extend di tempat** (`/api/v1/settings/routing/…`), jadi
 * `MASTER_ROUTINGS_PATH` harus SAMA dengan `SETTINGS_ROUTING_PATH` (F3A) — tidak ada
 * endpoint paralel `/master/routings/`. Bentuk baris = persis
 * `django_app/apps_industry/garment/api/settings/views.py::serialize_routing`
 * (+ detail: `capability_tags`, `steps_count`, `nodes[]`, `edges[]`, timestamps).
 */

const STEP_1 = {
  id: 11,
  step_no: 1,
  wc_type: 'CUTTING',
  depends_on: [] as number[],
  rework_target_step: null,
  is_initial: true,
  is_terminal: false,
};

const STEP_2 = {
  id: 12,
  step_no: 2,
  wc_type: 'SEWING',
  depends_on: [1],
  rework_target_step: null,
  is_initial: false,
  is_terminal: true,
};

const ROW = {
  id: 7,
  code: 'RT-H19',
  name: 'Routing H1.9',
  description: 'sablon dulu',
  is_active: true,
  steps: [STEP_1, STEP_2],
};

const DETAIL = {
  ...ROW,
  capability_tags: ['JAHIT', 'OBRAS'],
  steps_count: 2,
  nodes: [
    { id: 11, label: 'CUTTING', step_no: 1 },
    { id: 12, label: 'SEWING', step_no: 2 },
  ],
  edges: [{ from: 11, to: 12, overlap_pct: 0, is_rework: false }],
  created_at: '2026-10-11T04:00:00+00:00',
  updated_at: '2026-10-11T05:00:00+00:00',
};

describe('H1.9 — MODE & path', () => {
  it('MODE.masterRoutings = real, path = B22 settings routing, sub-resource detail/step', () => {
    expect(MODE['masterRoutings']).toBe('real');
    expect(isReal('masterRoutings')).toBe(true);
    expect(MASTER_ROUTINGS_PATH).toBe(SETTINGS_ROUTING_PATH);
    expect(MASTER_ROUTINGS_PATH).toBe('/settings/routing/');
    expect(ROUTINGS_LIMIT_DEFAULT).toBe(50);
    expect(ROUTINGS_LIMIT_MAX).toBe(200);

    expect(routingDetailPath(7)).toBe('/settings/routing/7/');
    expect(routingStepsPath(7)).toBe('/settings/routing/7/steps/');
    expect(routingStepPath(7, 12)).toBe('/settings/routing/7/steps/12/');
  });

  it('buildMasterRoutingsPath hanya mengirim limit/cursor (shape list B22 tidak berubah)', () => {
    expect(buildMasterRoutingsPath()).toBe('/settings/routing/');
    expect(buildMasterRoutingsPath({ limit: 200, cursor: 50 })).toBe(
      '/settings/routing/?limit=200&cursor=50',
    );
    expect(buildMasterRoutingsPath({ limit: null, cursor: null })).toBe('/settings/routing/');
  });
});

describe('H1.9 — parsing respons', () => {
  it('readMasterRoutingRow/Page membaca shape F3A apa adanya', () => {
    const row = readMasterRoutingRow(ROW);

    expect(row).not.toBeNull();
    expect(Object.keys(row ?? {}).sort()).toEqual([
      'code',
      'description',
      'id',
      'is_active',
      'name',
      'steps',
    ]);
    expect(row?.steps[1]).toEqual(STEP_2);

    const page = readMasterRoutingPage({
      rows: [ROW],
      total_count: 1,
      has_more: false,
      next_cursor: null,
    });

    expect(page?.total_count).toBe(1);
    expect(page?.rows[0]?.code).toBe('RT-H19');
  });

  it('readMasterRoutingDetail menambah field H1.9 tanpa menghapus field B22', () => {
    const detail = readMasterRoutingDetail(DETAIL);

    expect(detail?.capability_tags).toEqual(['JAHIT', 'OBRAS']);
    expect(detail?.steps_count).toBe(2);
    expect(detail?.nodes).toEqual([
      { id: 11, label: 'CUTTING', step_no: 1 },
      { id: 12, label: 'SEWING', step_no: 2 },
    ]);
    expect(detail?.edges).toEqual([
      { from: 11, to: 12, overlap_pct: 0, is_rework: false },
    ]);
    expect(detail?.created_at).toBe('2026-10-11T04:00:00+00:00');
    expect(detail?.steps[0]?.step_no).toBe(1);
    // respons tulis membaca detail yang sama; bentuk asing → null
    expect(readMasterRoutingSaved(DETAIL)?.code).toBe('RT-H19');
    expect(readMasterRoutingSaved('bukan objek')).toBeNull();
    expect(readMasterRoutingDetail(null)).toBeNull();
  });

  it('readMasterRoutingStepRow membaca satu step (termasuk rework)', () => {
    const step = readMasterRoutingStepRow({
      id: 13,
      step_no: 3,
      wc_type: 'QC',
      depends_on: [1, 2],
      rework_target_step: 2,
      is_initial: false,
      is_terminal: true,
    });

    expect(step?.depends_on).toEqual([1, 2]);
    expect(step?.rework_target_step).toBe(2);
    expect(readMasterRoutingStepRow('bukan objek')).toBeNull();
  });
});

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

describe('H1.9 — body payload', () => {
  it('toMasterRoutingBody hanya membawa field yang dikirim', () => {
    expect(toMasterRoutingBody({ name: 'Baru' })).toEqual({ name: 'Baru' });
    expect(
      toMasterRoutingBody({
        name: 'Baru',
        code: 'RT-2',
        description: 'd',
        capability_tags: ['JAHIT'],
        active: false,
      }),
    ).toEqual({
      name: 'Baru',
      code: 'RT-2',
      description: 'd',
      capability_tags: ['JAHIT'],
      active: false,
    });
  });

  it('toMasterRoutingCreateBody memakai bentuk B22 (steps[] dengan step_no)', () => {
    expect(
      toMasterRoutingCreateBody({
        name: 'Routing Baru',
        steps: [
          { step_no: 1, wc_type: 'CUTTING', depends_on: [] },
          { step_no: 2, wc_type: 'SEWING', depends_on: [1], rework_target_step: null },
        ],
      }),
    ).toEqual({
      name: 'Routing Baru',
      steps: [
        { step_no: 1, wc_type: 'CUTTING', depends_on: [] },
        { step_no: 2, wc_type: 'SEWING', depends_on: [1], rework_target_step: null },
      ],
    });
  });

  it('toMasterRoutingStepBody mengirim id, mempertahankan list kosong, stripUndefined', () => {
    expect(
      toMasterRoutingStepBody({
        label: 'QC',
        order: 30,
        work_center_id: 5,
        depends_on_step_ids: [],
      }),
    ).toEqual({ label: 'QC', order: 30, work_center_id: 5, depends_on_step_ids: [] });
    expect(toMasterRoutingStepBody({ rework_target_step_id: null })).toEqual({
      rework_target_step_id: null,
    });
    expect(stripUndefined({ a: 1, b: undefined, c: null })).toEqual({ a: 1, c: null });
  });
});

describe('H1.9 — HTTP adapter', () => {
  it('GET: list B22 + detail; barrel masterRoutings ter-wire REAL (pickAdapter)', async () => {
    for (const fn of [
      fetchRoutings,
      fetchRouting,
      createRouting,
      updateRouting,
      deleteRouting,
      addRoutingStep,
      updateRoutingStep,
      removeRoutingStep,
    ]) {
      expect(typeof fn).toBe('function');
    }

    const page = stubClient({ rows: [ROW], total_count: 1, has_more: false, next_cursor: null });

    const list = await realFetchRoutings(page.client, { limit: 200 });

    expect(page.requests).toEqual([{ path: '/settings/routing/?limit=200', method: 'GET' }]);
    expect(list.rows[0]?.code).toBe('RT-H19');

    const one = stubClient(DETAIL);

    const detail = await realFetchRouting(one.client, 7);

    expect(one.requests).toEqual([{ path: '/settings/routing/7/', method: 'GET' }]);
    expect(detail.steps_count).toBe(2);
  });

  it('createMasterRouting POST list (B22) membawa steps[]', async () => {
    const stub = stubClient(DETAIL);

    const saved = await realCreateRouting(stub.client, {
      name: 'Routing Baru',
      steps: [{ step_no: 1, wc_type: 'CUTTING', depends_on: [] }],
    });

    expect(stub.requests).toEqual([
      {
        path: '/settings/routing/',
        method: 'POST',
        body: {
          name: 'Routing Baru',
          steps: [{ step_no: 1, wc_type: 'CUTTING', depends_on: [] }],
        },
      },
    ]);
    expect(saved.capability_tags).toEqual(['JAHIT', 'OBRAS']);
  });

  it('updateMasterRouting PUT + deleteMasterRouting DELETE + step CRUD /steps/', async () => {
    const stub = stubClient({ ...DETAIL, is_active: false });

    await realUpdateRouting(stub.client, 7, { name: 'Setelah PUT', active: false });
    const removed = await realDeleteRouting(stub.client, 7);

    expect(stub.requests).toEqual([
      {
        path: '/settings/routing/7/',
        method: 'PUT',
        body: { name: 'Setelah PUT', active: false },
      },
      { path: '/settings/routing/7/', method: 'DELETE', body: undefined },
    ]);
    expect(removed.is_active).toBe(false);

    const steps = stubClient(DETAIL);

    await realCreateStep(steps.client, 7, { label: 'QC', depends_on_step_ids: [12] });
    await realUpdateStep(steps.client, 7, 12, { label: 'FINISHING' });
    await realDeleteStep(steps.client, 7, 12);

    expect(steps.requests).toEqual([
      {
        path: '/settings/routing/7/steps/',
        method: 'POST',
        body: { label: 'QC', depends_on_step_ids: [12] },
      },
      {
        path: '/settings/routing/7/steps/12/',
        method: 'PUT',
        body: { label: 'FINISHING' },
      },
      { path: '/settings/routing/7/steps/12/', method: 'DELETE', body: undefined },
    ]);
  });

  it('gagal HTTP → melempar (pesan backend dipakai Toast)', async () => {
    await expect(realFetchRouting(failingClient(403, 'Dilarang'), 7)).rejects.toThrow(
      'Dilarang',
    );
    await expect(
      realDeleteRouting(failingClient(400, 'masih dipakai 1 rule tag-router aktif'), 7),
    ).rejects.toThrow('masih dipakai 1 rule tag-router aktif');
  });
});


