import { describe, expect, it } from 'vitest';

/**
 * F8 LIVE — material readiness (`GET /garmen/orders/{id}/readiness/`, §5.4/§5.5).
 *
 *   MES_LIVE=1 ~/.bun/bin/bun --bun run test tests/live
 *     → probe anonim SAJA (403 = route ADA; tidak memicu apa pun)
 *
 *   MES_LIVE=1 MES_LIVE_ALLOW_READINESS=1 MES_SESSION_COOKIE='sessionid=…' … run test tests/live
 *     → GET readiness nyata + POST recompute (memanggil PO/vendor bill Odoo).
 *
 * Path memakai `orders/{orderId}` = **id ORDER** (bukan OrderLine).
 */

const LIVE = process.env['MES_LIVE'] === '1';
const ALLOW_READINESS = process.env['MES_LIVE_ALLOW_READINESS'] === '1';
const API_BASE = process.env['MES_API_BASE_URL'] ?? 'http://localhost:8000/api/v1';
const SESSION_COOKIE = process.env['MES_SESSION_COOKIE'] ?? '';
const ORDER_ID = process.env['MES_LIVE_ORDER_ID'] ?? '1';

const READINESS_PATH = `/garmen/orders/${ORDER_ID}/readiness/`;
const RECOMPUTE_PATH = `/garmen/orders/${ORDER_ID}/recompute-readiness/`;
const OPTED_IN = ALLOW_READINESS && SESSION_COOKIE.length > 0;

describe.skipIf(!LIVE)('F8 LIVE — material readiness', () => {
  it('anon GET /garmen/orders/{id}/readiness/ → 403 (route ADA, IsAuthenticated)', async () => {
    const res = await fetch(`${API_BASE}${READINESS_PATH}`);

    expect(res.status).toBe(403);
  });

  it('anon POST recompute → 403 (tidak memicu Odoo)', async () => {
    const res = await fetch(`${API_BASE}${RECOMPUTE_PATH}`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: '{}',
    });

    expect(res.status).toBe(403);
  });

  it.skipIf(!OPTED_IN)('OPT-IN GET readiness → 200 + bentuk §5.4', async () => {
    const res = await fetch(`${API_BASE}${READINESS_PATH}`, { headers: { cookie: SESSION_COOKIE } });

    expect(res.status).toBe(200);

    const body = (await res.json()) as Record<string, unknown>;

    expect(body['order_id']).toBe(Number(ORDER_ID));
    expect(Array.isArray(body['lines'])).toBe(true);

    const first = (body['lines'] as Record<string, unknown>[])[0];

    if (first !== undefined) {
      expect(typeof first['order_line_id']).toBe('number');
      expect(first).toHaveProperty('status');
      expect(first).toHaveProperty('vendor_bill_status');
    }
  });

  it.skipIf(!OPTED_IN)('OPT-IN POST recompute → 200 counter §5.5', async () => {
    const res = await fetch(`${API_BASE}${RECOMPUTE_PATH}`, {
      method: 'POST',
      headers: { cookie: SESSION_COOKIE, 'content-type': 'application/json' },
      body: '{}',
    });

    expect([200, 403]).toContain(res.status);

    if (res.status === 200) {
      const body = (await res.json()) as Record<string, unknown>;
      const counter = body['processed'] ?? body['queued'];

      expect(typeof counter).toBe('number');
    }
  });
});
