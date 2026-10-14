import { describe, expect, it } from 'vitest';

/**
 * F9 + F10 LIVE — reconciliation (§6.2), audit (§6.1), dan BUKTI KETIADAAN endpoint F10.
 *
 *   MES_LIVE=1 ~/.bun/bin/bun --bun run test tests/live
 *     → probe anonim saja (tidak mengubah data, tidak memicu Odoo)
 *
 *   MES_LIVE=1 MES_LIVE_ALLOW_REPORTS=1 MES_SESSION_COOKIE='sessionid=…' … run test tests/live
 *     → GET terautentikasi reconciliation + audit + batas `days`
 *
 * CATATAN PENTING (hasil recon F9): `/api/v1/sync/odoo/records/` membalas **403** untuk anonim
 * BUKAN karena ada endpoint daftar SyncRecord, melainkan karena path itu cocok pola
 * `api/v1/sync/odoo/<str:stage>/` (`SyncOdooView`, cek auth lebih dulu). Tes di bawah mengunci
 * temuan itu supaya tidak salah disimpulkan "endpoint sync-list ADA".
 */

const LIVE = process.env['MES_LIVE'] === '1';
const ALLOW_REPORTS = process.env['MES_LIVE_ALLOW_REPORTS'] === '1';
const API_BASE = process.env['MES_API_BASE_URL'] ?? 'http://localhost:8000/api/v1';
const SESSION_COOKIE = process.env['MES_SESSION_COOKIE'] ?? '';
const OPTED_IN = ALLOW_REPORTS && SESSION_COOKIE.length > 0;

const RECONCILIATION_PATH = '/reconciliation/report/';
const AUDIT_PATH = '/audit/products-missing-odoo-id/';

describe.skipIf(!LIVE)('F9 LIVE — reconciliation & audit (route ADA, IsAuthenticated)', () => {
  it('anon GET /reconciliation/report/?days=7 → 403', async () => {
    const res = await fetch(`${API_BASE}${RECONCILIATION_PATH}?days=7`);

    expect(res.status).toBe(403);
  });

  it('anon GET /audit/products-missing-odoo-id/ → 403', async () => {
    const res = await fetch(`${API_BASE}${AUDIT_PATH}`);

    expect(res.status).toBe(403);
  });

  it('anon POST reconciliation report → 405/403 (read-only, tanpa write endpoint)', async () => {
    const res = await fetch(`${API_BASE}${RECONCILIATION_PATH}`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: '{}',
    });

    expect([403, 405]).toContain(res.status);
  });
});

describe.skipIf(!LIVE)('F10/F15 LIVE — endpoint monitoring ADA (Fase 4.4, butuh auth)', () => {
  it('GET /finance/invoices/ → 403 (endpoint ADA sejak Fase 4.4; dulu 404 → F10 revive)', async () => {
    const res = await fetch(`${API_BASE}/finance/invoices/`);

    expect(res.status).toBe(403);
    expect(res.status).not.toBe(404);
  });

  it('GET /sync/records/ → 403 (endpoint ADA sejak Fase 4.4; dulu 404 → F10 revive)', async () => {
    const res = await fetch(`${API_BASE}/sync/records/`);

    expect(res.status).toBe(403);
    expect(res.status).not.toBe(404);
  });

  it('TRAP: GET /sync/odoo/records/ → 403 dari pola `sync/odoo/<stage>/` (BUKAN list endpoint)', async () => {
    const res = await fetch(`${API_BASE}/sync/odoo/records/`);

    // 403 hanya berarti "route cocok + wajib login" — stage `records` bukan stage sah.
    expect(res.status).toBe(403);
  });
});

describe.skipIf(!LIVE)('F9 LIVE — opt-in terautentikasi', () => {
  it.skipIf(!OPTED_IN)('OPT-IN GET reconciliation → 200 + {days, count, entries}', async () => {
    const res = await fetch(`${API_BASE}${RECONCILIATION_PATH}?days=7`, {
      headers: { cookie: SESSION_COOKIE },
    });

    expect(res.status).toBe(200);

    const body = (await res.json()) as Record<string, unknown>;

    expect(body['days']).toBe(7);
    expect(typeof body['count']).toBe('number');
    expect(Array.isArray(body['entries'])).toBe(true);

    const first = (body['entries'] as Record<string, unknown>[])[0];

    if (first !== undefined) {
      expect(first).toHaveProperty('run_at');
      expect(first).toHaveProperty('product_odoo_id');
      expect(first).toHaveProperty('is_alert');
    }
  });

  it.skipIf(!OPTED_IN)('OPT-IN days=0 → 400 (validasi backend 1..90)', async () => {
    const res = await fetch(`${API_BASE}${RECONCILIATION_PATH}?days=0`, {
      headers: { cookie: SESSION_COOKIE },
    });

    expect(res.status).toBe(400);
  });

  it.skipIf(!OPTED_IN)('OPT-IN days=100 → 400', async () => {
    const res = await fetch(`${API_BASE}${RECONCILIATION_PATH}?days=100`, {
      headers: { cookie: SESSION_COOKIE },
    });

    expect(res.status).toBe(400);
  });

  it.skipIf(!OPTED_IN)(
    'OPT-IN GET audit → 200 + {count, products, used_in_open_bundles{count,limit,products}}',
    async () => {
      const res = await fetch(`${API_BASE}${AUDIT_PATH}`, { headers: { cookie: SESSION_COOKIE } });

      expect(res.status).toBe(200);

      const body = (await res.json()) as Record<string, unknown>;

      expect(typeof body['count']).toBe('number');
      expect(Array.isArray(body['products'])).toBe(true);

      const group = body['used_in_open_bundles'] as Record<string, unknown>;

      expect(typeof group['count']).toBe('number');
      expect(Array.isArray(group['products'])).toBe(true);
    },
  );
});
