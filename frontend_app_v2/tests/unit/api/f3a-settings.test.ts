import { describe, expect, it } from 'vitest';
import { buildQueryPath, readListPage, readNum } from '@/api/real/_shape';
import {
  fetchRoutingConfigs,
  fetchRoutingRows,
  readRoutingPage,
  readRoutingRow,
  saveRoutingConfig,
  SETTINGS_ROUTING_PATH,
  toRoutingConfig,
  toRoutingSteps,
} from '@/api/real/settingsRouting';
import {
  createBundlingRule,
  fetchBundlingRules,
  readBundlingRulePage,
  readBundlingRuleRow,
  SETTINGS_BUNDLING_PATH,
} from '@/api/real/settingsBundling';
import {
  createLineAllocation,
  fetchLineAllocations,
  readLineAllocationPage,
  SETTINGS_LINE_ALLOCATION_PATH,
} from '@/api/real/settingsLineAllocation';
import { MODE } from '@/api/_adapter';
import type { ApiClient, ApiResponse } from '@/integrations/api-client';

/**
 * F3A.CLOSE — 3 adapter REAL settings (B22 routing, B24 bundling, B25 line-allocation).
 * Ketiganya GET+POST; routing menyimpan `steps[]` (bukan DAG) → konversi dua arah diuji.
 */

const ROUTING_BODY = {
  rows: [
    {
      id: 1,
      code: 'RT-1',
      name: 'Kaos Basic',
      description: 'draft',
      is_active: true,
      steps: [
        {
          id: 10,
          step_no: 1,
          wc_type: 'CUTTING',
          depends_on: [],
          rework_target_step: null,
          is_initial: true,
          is_terminal: false,
        },
        {
          id: 11,
          step_no: 2,
          wc_type: 'SEWING',
          depends_on: [1],
          rework_target_step: 1,
          is_initial: false,
          is_terminal: true,
        },
      ],
    },
  ],
  total_count: 1,
  has_more: false,
  next_cursor: null,
};

function stubClient(data: unknown): {
  client: ApiClient;
  gets: string[];
  posts: { path: string; body: unknown }[];
} {
  const gets: string[] = [];
  const posts: { path: string; body: unknown }[] = [];

  const client = {
    get: async <T,>(path: string): Promise<ApiResponse<T>> => {
      gets.push(path);
      return { ok: true, status: 200, data: data as T };
    },
    post: async <T,>(path: string, body?: unknown): Promise<ApiResponse<T>> => {
      posts.push({ path, body });
      return { ok: true, status: 201, data: data as T };
    },
  } as unknown as ApiClient;

  return { client, gets, posts };
}

describe('F3A.CLOSE — MODE settings*', () => {
  it('tiga key settings (B22/B24/B25) = real; sisa settings B26–B28 juga real (F5.4.CLOSE)', () => {
    expect(MODE['settingsRouting']).toBe('real');
    expect(MODE['settingsBundling']).toBe('real');
    expect(MODE['settingsLineAllocation']).toBe('real');
    expect(MODE['settingsUsers']).toBe('real');
    expect(MODE['settingsRoles']).toBe('real');
    expect(MODE['settingsDevices']).toBe('real');
  });
});

describe('F3A.CLOSE — helper _shape', () => {
  it('buildQueryPath melewati nilai kosong', () => {
    expect(buildQueryPath('/x/', { a: 1, b: null, c: '', d: false })).toBe('/x/?a=1&d=false');
    expect(buildQueryPath('/x/', {})).toBe('/x/');
  });

  it('readListPage memakai has_more (bukan has_next)', () => {
    const page = readListPage({ rows: [{ n: 1 }], has_more: true, total_count: 1, next_cursor: 9 }, (row) => ({
      n: readNum((row as Record<string, unknown>)['n']),
    }));

    expect(page).toEqual({ rows: [{ n: 1 }], total_count: 1, has_more: true, next_cursor: 9 });
    expect(readListPage({ rows: {} }, () => null)).toBeNull();
  });
});

describe('F3A.CLOSE — B22 settings/routing', () => {
  it('parse row + row→graph (auto-layout, edge rework)', () => {
    const row = readRoutingRow(ROUTING_BODY.rows[0]);

    expect(row?.steps).toHaveLength(2);
    expect(readRoutingPage({ rows: [] })?.rows).toEqual([]);
    expect(readRoutingRow('nope')).toBeNull();

    const config = toRoutingConfig(row!);

    expect(config.id).toBe(1);
    expect(config.name).toBe('Kaos Basic');
    expect(config.active).toBe(true);
    expect(config.graph.nodes.map((node) => node.id)).toEqual(['step-1', 'step-2']);
    expect(config.graph.nodes[1]?.step_no).toBe(2);
    expect(config.graph.edges.filter((edge) => edge.isRework)).toHaveLength(1);
  });

  it('graph→steps (round-trip depends_on + rework)', () => {
    const config = toRoutingConfig(readRoutingRow(ROUTING_BODY.rows[0])!);
    const steps = toRoutingSteps(config.graph);

    expect(steps).toEqual([
      { step_no: 1, wc_type: 'CUTTING', depends_on: [], rework_target_step: null },
      { step_no: 2, wc_type: 'SEWING', depends_on: [1], rework_target_step: 1 },
    ]);
  });

  it('fetchRoutingConfigs → RoutingConfig[] + path', async () => {
    const { client, gets } = stubClient(ROUTING_BODY);
    const configs = await fetchRoutingConfigs(client);

    expect(SETTINGS_ROUTING_PATH).toBe('/settings/routing/');
    expect(gets).toEqual(['/settings/routing/']);
    expect(configs[0]?.graph.nodes).toHaveLength(2);

    const { client: rawClient } = stubClient(ROUTING_BODY);
    const page = await fetchRoutingRows(rawClient, { limit: 5 });
    expect(page.total_count).toBe(1);
  });

  it('saveRoutingConfig POST body {name, steps[]}', async () => {
    const config = toRoutingConfig(readRoutingRow(ROUTING_BODY.rows[0])!);
    const { client, posts } = stubClient(ROUTING_BODY.rows[0]);
    const saved = await saveRoutingConfig(client, config);

    expect(posts[0]?.path).toBe('/settings/routing/');
    expect(posts[0]?.body).toEqual({
      name: 'Kaos Basic',
      steps: [
        { step_no: 1, wc_type: 'CUTTING', depends_on: [], rework_target_step: null },
        { step_no: 2, wc_type: 'SEWING', depends_on: [1], rework_target_step: 1 },
      ],
    });
    expect(saved.name).toBe('Kaos Basic');
  });
});

describe('F3A.CLOSE — B24 settings/bundling', () => {
  const body = {
    rows: [
      {
        id: 3,
        name: 'Kaos Basic',
        size_matrix: { S: 10, M: 12 },
        bundle_size_default: 12,
        is_active: true,
        created_at: '2026-10-01T08:00:00+07:00',
        updated_at: '2026-10-01T08:00:00+07:00',
      },
    ],
    total_count: 1,
    has_more: false,
    next_cursor: null,
  };

  it('parse matrix + path + fetch', async () => {
    const row = readBundlingRuleRow(body.rows[0]);

    expect(row?.size_matrix).toEqual({ S: 10, M: 12 });
    expect(row?.bundle_size_default).toBe(12);
    expect(readBundlingRulePage({ rows: 'x' })).toBeNull();

    expect(SETTINGS_BUNDLING_PATH).toBe('/settings/bundling/');

    const { client, gets } = stubClient(body);
    const page = await fetchBundlingRules(client, { limit: 20 });
    expect(gets).toEqual(['/settings/bundling/?limit=20']);
    expect(page.rows[0]?.name).toBe('Kaos Basic');
  });

  it('createBundlingRule POST body + default kosong', async () => {
    const { client, posts } = stubClient(body.rows[0]);
    await createBundlingRule(client, { name: 'Polo', size_matrix: { L: 8 } });
    await createBundlingRule(client, { name: 'Tanpa Matrix' });

    expect(posts[0]?.path).toBe('/settings/bundling/');
    expect(posts[0]?.body).toEqual({
      name: 'Polo',
      size_matrix: { L: 8 },
      bundle_size_default: 0,
    });
    expect(posts[1]?.body).toEqual({
      name: 'Tanpa Matrix',
      size_matrix: {},
      bundle_size_default: 0,
    });
  });
});

describe('F3A.CLOSE — B25 settings/line-allocation', () => {
  const body = {
    rows: [
      {
        id: 7,
        name: 'Sewing ke LINE-A',
        wc_type: 'SEWING',
        line_id: 2,
        line_code: 'LINE-A',
        priority: 1,
        is_active: true,
        config: { shift: 'A' },
        created_at: '2026-10-01T08:00:00+07:00',
        updated_at: '2026-10-01T08:00:00+07:00',
      },
    ],
    total_count: 1,
    has_more: false,
    next_cursor: null,
  };

  it('parse (line_code bisa null) + filter wc_type + fetch', async () => {
    const page = readLineAllocationPage(body);

    expect(page?.rows[0]?.line_code).toBe('LINE-A');
    expect(page?.rows[0]?.config).toEqual({ shift: 'A' });
    expect(readLineAllocationPage({ rows: null })).toBeNull();

    const { client, gets } = stubClient({
      ...body,
      rows: [{ ...body.rows[0], line_code: null }],
    });
    const fetched = await fetchLineAllocations(client, { wcType: 'SEWING' });

    expect(SETTINGS_LINE_ALLOCATION_PATH).toBe('/settings/line-allocation/');
    expect(gets).toEqual(['/settings/line-allocation/?wc_type=SEWING']);
    expect(fetched.rows[0]?.line_code).toBeNull();
  });

  it('createLineAllocation POST body + default priority/config', async () => {
    const { client, posts } = stubClient(body.rows[0]);
    await createLineAllocation(client, { name: 'Cutting ke LINE-B', wc_type: 'CUTTING', line_id: 3 });

    expect(posts[0]?.path).toBe('/settings/line-allocation/');
    expect(posts[0]?.body).toEqual({
      name: 'Cutting ke LINE-B',
      wc_type: 'CUTTING',
      line_id: 3,
      priority: 0,
      config: {},
    });
  });
});
