import { describe, expect, it } from 'vitest';
import { fetchAqlSummary } from '@/api/real/qcAql';
import { submitDefect } from '@/api/real/qcSubmit';
import { fetchLineEfficiencyByWc } from '@/api/real/reportsLineEfficiencyByWc';
import { fetchLeadTime } from '@/api/real/reportsLeadTime';
import { fetchLeadTimeBundles } from '@/api/real/reportsLeadTimeBundles';
import { fetchOnTimeDelivery } from '@/api/real/reportsOnTimeDelivery';
import { fetchOnTimeDeliveryOrders } from '@/api/real/reportsOnTimeDeliveryOrders';
import { fetchWipByWc } from '@/api/real/reportsWipByWc';
import { createBundlingRule, fetchBundlingRules } from '@/api/real/settingsBundling';
import { createLineAllocation, fetchLineAllocations } from '@/api/real/settingsLineAllocation';
import { fetchRoutingConfigs, fetchRoutingRows } from '@/api/real/settingsRouting';
import { createApiClient } from '@/integrations/api-client';

/**
 * F3A.CLOSE LIVE — 11 endpoint baru vs backend Django yang sedang jalan.
 *
 * Dijalankan HANYA kalau `MES_LIVE=1` (default: skip supaya `bun run test` hijau tanpa backend):
 *
 *   MES_LIVE=1 ~/.bun/bin/bun --bun run test tests/live
 *   # + tulis (POST settings/defect) — HANYA kalau diizinkan:
 *   MES_LIVE=1 MES_LIVE_ALLOW_SYNC=1 … run test tests/live
 */

const LIVE = process.env['MES_LIVE'] === '1';
const BASE_URL = process.env['MES_API_BASE_URL'] ?? 'http://localhost:8000/api/v1';
const ALLOW_WRITE = process.env['MES_LIVE_ALLOW_SYNC'] === '1';

describe.skipIf(!LIVE)('F3A.CLOSE LIVE — endpoint B5/B7b/B18–B25', () => {
  const client = createApiClient({ baseUrl: BASE_URL });

  it('B5 GET /quality/aql/ → rows + period', async () => {
    const report = await fetchAqlSummary(client);

    expect(Array.isArray(report.rows)).toBe(true);
    expect(typeof report.generated_at).toBe('string');
    expect(report.period).toHaveProperty('from');
  });

  it('B18 GET /reports/line-efficiency/by-wc/ → rows', async () => {
    const report = await fetchLineEfficiencyByWc(client);

    expect(Array.isArray(report.rows)).toBe(true);
    expect(report.period).toHaveProperty('to');
  });

  it('B19 GET /reports/lead-time/ → ListPage + avg_hours', async () => {
    const report = await fetchLeadTime(client, { limit: 2 });

    expect(Array.isArray(report.rows)).toBe(true);
    expect(typeof report.avg_hours).toBe('number');
    expect(report).toHaveProperty('has_more');
  });

  it('B19b GET /reports/lead-time/bundles/ → ListPage', async () => {
    const page = await fetchLeadTimeBundles(client, { limit: 2 });

    expect(Array.isArray(page.rows)).toBe(true);
    expect(page).toHaveProperty('next_cursor');
  });

  it('B20 GET /reports/on-time-delivery/ → ListPage + otd_pct', async () => {
    const report = await fetchOnTimeDelivery(client, { limit: 2 });

    expect(Array.isArray(report.rows)).toBe(true);
    expect(typeof report.otd_pct).toBe('number');
  });

  it('B20b GET /reports/on-time-delivery/orders/ → ListPage', async () => {
    const page = await fetchOnTimeDeliveryOrders(client, { limit: 2 });

    expect(Array.isArray(page.rows)).toBe(true);
    expect(page).toHaveProperty('total_count');
  });

  it('B21 GET /reports/wip/by-wc/ → total_wip + rows', async () => {
    const report = await fetchWipByWc(client);

    expect(Array.isArray(report.rows)).toBe(true);
    expect(typeof report.total_wip).toBe('number');
  });

  it('B22 GET /settings/routing/ → ListPage + steps', async () => {
    const page = await fetchRoutingRows(client, { limit: 2 });
    const configs = await fetchRoutingConfigs(client);

    expect(Array.isArray(page.rows)).toBe(true);
    expect(Array.isArray(configs)).toBe(true);
    if (page.rows[0] !== undefined) expect(Array.isArray(page.rows[0].steps)).toBe(true);
  });

  it('B24 GET /settings/bundling/ → ListPage', async () => {
    const page = await fetchBundlingRules(client, { limit: 2 });

    expect(Array.isArray(page.rows)).toBe(true);
    expect(page).toHaveProperty('has_more');
  });

  it('B25 GET /settings/line-allocation/ → ListPage', async () => {
    const page = await fetchLineAllocations(client, { limit: 2 });

    expect(Array.isArray(page.rows)).toBe(true);
    expect(page).toHaveProperty('has_more');
  });

  it.skipIf(!ALLOW_WRITE)('POST /quality/defects/ + /settings/* (menulis data!)', async () => {
    const submit = await submitDefect(client, {
      bundle_id: Number(process.env['MES_LIVE_BUNDLE_ID'] ?? '0'),
      defect_type: 'lainnya',
      qty: 1,
      reason: 'live smoke test',
      action: 'rework',
    });

    expect(submit.ok).toBe(true);

    const bundling = await createBundlingRule(client, {
      name: `LIVE-${Date.now()}`,
      bundle_size_default: 1,
    });

    expect(bundling.name.startsWith('LIVE-')).toBe(true);

    const alloc = await createLineAllocation(client, {
      name: `LIVE-${Date.now()}`,
      wc_type: 'CUTTING',
      line_id: Number(process.env['MES_LIVE_LINE_ID'] ?? '1'),
    });

    expect(alloc.wc_type).toBe('CUTTING');
  });
});
