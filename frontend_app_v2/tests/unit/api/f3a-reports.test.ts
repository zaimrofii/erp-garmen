import { describe, expect, it } from 'vitest';
import {
  buildLineEfficiencyByWcPath,
  fetchLineEfficiencyByWc,
  LINE_EFFICIENCY_BY_WC_PATH,
  readLineEfficiencyByWcReport,
} from '@/api/real/reportsLineEfficiencyByWc';
import {
  buildReportsLeadTimePath,
  fetchLeadTime,
  LEAD_TIME_PATH,
  readLeadTimeReport,
} from '@/api/real/reportsLeadTime';
import {
  buildLeadTimeBundlesPath,
  fetchLeadTimeBundles,
  LEAD_TIME_BUNDLES_PATH,
  readLeadTimeBundlePage,
} from '@/api/real/reportsLeadTimeBundles';
import {
  buildReportsOtdPath,
  fetchOnTimeDelivery,
  ON_TIME_DELIVERY_PATH,
  readOtdReport,
} from '@/api/real/reportsOnTimeDelivery';
import {
  buildOtdOrdersPath,
  fetchOnTimeDeliveryOrders,
  ON_TIME_DELIVERY_ORDERS_PATH,
  readOtdOrderPage,
} from '@/api/real/reportsOnTimeDeliveryOrders';
import {
  fetchWipByWc,
  readWipByWcReport,
  WIP_BY_WC_PATH,
} from '@/api/real/reportsWipByWc';
import { MODE } from '@/api/_adapter';
import type { ApiClient, ApiResponse } from '@/integrations/api-client';

/**
 * F3A.CLOSE — 6 adapter REAL reports (B18/B19/B19b/B20/B20b/B21).
 * Semua bentuk diambil PERSIS dari `monitoring.py` (ListPage memakai `has_more`).
 */

const PAGE = { total_count: 1, has_more: false, next_cursor: null };

function stubClient(data: unknown): { client: ApiClient; gets: string[] } {
  const gets: string[] = [];

  const client = {
    get: async <T,>(path: string): Promise<ApiResponse<T>> => {
      gets.push(path);
      return { ok: true, status: 200, data: data as T };
    },
  } as unknown as ApiClient;

  return { client, gets };
}

describe('F3A.CLOSE — MODE 6 key reports', () => {
  it('semuanya real', () => {
    expect(MODE['reportsLineEfficiencyByWc']).toBe('real');
    expect(MODE['reportsLeadTime']).toBe('real');
    expect(MODE['reportsLeadTimeBundles']).toBe('real');
    expect(MODE['reportsOTD']).toBe('real');
    expect(MODE['reportsOnTimeDeliveryOrders']).toBe('real');
    expect(MODE['reportsWipByWc']).toBe('real');
  });
});

describe('F3A.CLOSE — B18 line-efficiency/by-wc', () => {
  const body = {
    rows: [
      {
        wc_code: 'JAHIT-01',
        wc_name: 'Jahit 01',
        bundles_done: 12,
        avg_min_per_bundle: 45.5,
        efficiency_pct: 82.3,
        pct_delta_vs_prev: -1.7,
      },
    ],
    generated_at: '2026-10-10T08:00:00+07:00',
    period: { from: '2026-09-10', to: '2026-10-10' },
  };

  it('parse + path', async () => {
    const report = readLineEfficiencyByWcReport(body);

    expect(report?.rows[0]?.efficiency_pct).toBe(82.3);
    expect(report?.rows[0]?.pct_delta_vs_prev).toBe(-1.7);
    expect(readLineEfficiencyByWcReport({ rows: null })).toBeNull();

    expect(LINE_EFFICIENCY_BY_WC_PATH).toBe('/reports/line-efficiency/by-wc/');
    expect(buildLineEfficiencyByWcPath()).toBe('/reports/line-efficiency/by-wc/');
    expect(buildLineEfficiencyByWcPath({ from: '2026-10-01' })).toBe(
      '/reports/line-efficiency/by-wc/?from=2026-10-01',
    );

    const { client, gets } = stubClient(body);
    await fetchLineEfficiencyByWc(client);
    expect(gets).toEqual(['/reports/line-efficiency/by-wc/']);
  });
});

describe('F3A.CLOSE — B19 lead-time (+stages)', () => {
  const body = {
    rows: [
      {
        bundle_code: 'BDL-1',
        created_at: '2026-10-01T08:00:00+07:00',
        finished_at: '2026-10-02T08:00:00+07:00',
        hours_total: 24,
        stages: [{ wc_code: 'CUTTING', minutes: 60 }, { wc_code: null, minutes: 30 }],
      },
    ],
    ...PAGE,
    avg_hours: 24,
  };

  it('parse (stages + wc_code null) + path', async () => {
    const report = readLeadTimeReport(body);

    expect(report?.avg_hours).toBe(24);
    expect(report?.rows[0]?.stages).toHaveLength(2);
    expect(report?.rows[0]?.stages[1]?.wc_code).toBeNull();
    expect(readLeadTimeReport({ rows: 'x' })).toBeNull();

    expect(LEAD_TIME_PATH).toBe('/reports/lead-time/');
    expect(buildReportsLeadTimePath()).toBe('/reports/lead-time/');
    expect(buildReportsLeadTimePath({ limit: 50, cursor: 0, from: '', to: '2026-10-10' })).toBe(
      '/reports/lead-time/?limit=50&cursor=0&to=2026-10-10',
    );

    const { client, gets } = stubClient(body);
    await fetchLeadTime(client, { limit: 50 });
    expect(gets).toEqual(['/reports/lead-time/?limit=50']);
  });
});

describe('F3A.CLOSE — B19b lead-time/bundles (flat)', () => {
  const body = {
    rows: [{ bundle_code: 'BDL-2', hours_total: 8.5, wc_count: 3, done_at: null }],
    ...PAGE,
  };

  it('parse + path + fetch', async () => {
    const page = readLeadTimeBundlePage(body);

    expect(page?.rows[0]).toEqual({
      bundle_code: 'BDL-2',
      hours_total: 8.5,
      wc_count: 3,
      done_at: null,
    });
    expect(readLeadTimeBundlePage({ rows: undefined })).toBeNull();

    expect(LEAD_TIME_BUNDLES_PATH).toBe('/reports/lead-time/bundles/');
    expect(buildLeadTimeBundlesPath({ cursor: 4 })).toBe('/reports/lead-time/bundles/?cursor=4');

    const { client, gets } = stubClient(body);
    const fetched = await fetchLeadTimeBundles(client, { limit: 10 });
    expect(gets).toEqual(['/reports/lead-time/bundles/?limit=10']);
    expect(fetched.rows).toHaveLength(1);
  });
});

describe('F3A.CLOSE — B20 on-time-delivery (+otd_pct)', () => {
  const body = {
    rows: [
      {
        order_code: 'SO-1',
        deadline: '2026-10-05T00:00:00+07:00',
        finished_at: '2026-10-06T10:00:00+07:00',
        on_time: false,
        delay_hours: 34.5,
      },
      { order_code: 'SO-2', deadline: null, finished_at: null, on_time: null, delay_hours: 0 },
    ],
    ...PAGE,
    otd_pct: 50,
  };

  it('parse (on_time null dipertahankan) + path + fetch', async () => {
    const report = readOtdReport(body);

    expect(report?.otd_pct).toBe(50);
    expect(report?.rows[0]?.on_time).toBe(false);
    expect(report?.rows[1]?.on_time).toBeNull();
    expect(readOtdReport({ rows: 0 })).toBeNull();

    expect(ON_TIME_DELIVERY_PATH).toBe('/reports/on-time-delivery/');
    expect(buildReportsOtdPath({ onTime: false })).toBe('/reports/on-time-delivery/?on_time=false');
    expect(buildReportsOtdPath({ onTime: null })).toBe('/reports/on-time-delivery/');

    const { client, gets } = stubClient(body);
    const fetched = await fetchOnTimeDelivery(client);
    expect(gets).toEqual(['/reports/on-time-delivery/']);
    expect(fetched.rows[1]?.on_time).toBeNull();
  });
});

describe('F3A.CLOSE — B20b on-time-delivery/orders', () => {
  const body = {
    rows: [
      {
        order_code: 'SO-3',
        deadline: '2026-10-01T00:00:00+07:00',
        last_wo_finished: '2026-10-01T09:00:00+07:00',
        on_time: true,
        wo_count: 4,
      },
    ],
    ...PAGE,
  };

  it('parse + path + fetch', async () => {
    const page = readOtdOrderPage(body);

    expect(page?.rows[0]).toEqual({
      order_code: 'SO-3',
      deadline: '2026-10-01T00:00:00+07:00',
      last_wo_finished: '2026-10-01T09:00:00+07:00',
      on_time: true,
      wo_count: 4,
    });
    expect(readOtdOrderPage({ rows: 'x' })).toBeNull();

    expect(ON_TIME_DELIVERY_ORDERS_PATH).toBe('/reports/on-time-delivery/orders/');
    expect(buildOtdOrdersPath()).toBe('/reports/on-time-delivery/orders/');

    const { client, gets } = stubClient(body);
    await fetchOnTimeDeliveryOrders(client, { limit: 5 });
    expect(gets).toEqual(['/reports/on-time-delivery/orders/?limit=5']);
  });
});

describe('F3A.CLOSE — B21 wip/by-wc (custom, bukan ListPage)', () => {
  const body = {
    rows: [
      {
        wc_code: 'SEWING',
        wc_name: 'Sewing',
        wip_qty: 120,
        queue_depth: 6,
        oldest_bundle_age_hours: 12.5,
      },
    ],
    total_wip: 120,
    generated_at: '2026-10-10T08:00:00+07:00',
  };

  it('parse + path + fetch', async () => {
    const report = readWipByWcReport(body);

    expect(report?.total_wip).toBe(120);
    expect(report?.rows[0]?.oldest_bundle_age_hours).toBe(12.5);
    expect(readWipByWcReport({ rows: {} })).toBeNull();

    expect(WIP_BY_WC_PATH).toBe('/reports/wip/by-wc/');

    const { client, gets } = stubClient(body);
    const fetched = await fetchWipByWc(client);
    expect(gets).toEqual(['/reports/wip/by-wc/']);
    expect(fetched.rows).toHaveLength(1);
  });
});
