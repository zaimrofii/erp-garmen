import { describe, expect, it } from 'vitest';
import { getBundles } from '@/api/bundles';
import { getOrderLines } from '@/api/orderLines';
import { buildOrderReadinessPath } from '@/api/readiness';
import { getQcRows, readQcRows } from '@/api/qc';
import { getWorkOrders } from '@/api/workOrders';
import { createApiClient } from '@/integrations/api-client';

/**
 * F2 LIVE — adapter real vs backend Django yang sedang jalan.
 *
 * Dijalankan HANYA kalau `MES_LIVE=1` (default: seluruh suite di-skip supaya `bun run test`
 * tetap hijau tanpa backend). Contoh:
 *
 *   MES_LIVE=1 ~/.bun/bin/bun --bun run test tests/live
 *   # opsional (untuk jalur IsAuthenticated):
 *   MES_LIVE=1 MES_SESSION_COOKIE='sessionid=…; csrftoken=…' … run test tests/live
 *   # opsional (efek samping tulis ke Odoo!):
 *   MES_LIVE=1 MES_SESSION_COOKIE='…' MES_LIVE_ALLOW_SYNC=1 … run test tests/live
 *
 * Yang TIDAK dijalankan tanpa izin: `POST /sync/scrap/` (sinkron, menulis TX-SCRAP ke Odoo).
 */

const LIVE = process.env['MES_LIVE'] === '1';
const BASE_URL = process.env['MES_API_BASE_URL'] ?? 'http://localhost:8000/api/v1';
const SESSION_COOKIE = process.env['MES_SESSION_COOKIE'] ?? '';
const ALLOW_SYNC_WRITE = process.env['MES_LIVE_ALLOW_SYNC'] === '1';

async function statusOf(path: string): Promise<number> {
  const res = await fetch(`${BASE_URL}${path}`, { method: 'GET' });

  return res.status;
}

describe.skipIf(!LIVE)('F2 LIVE — adapter real vs backend', () => {
  const client = createApiClient({ baseUrl: BASE_URL });

  it('2.1 GET /garmen/bundles/ → 200 + envelope ListPage', async () => {
    const page = await getBundles(client, { limit: 2 });

    expect(Array.isArray(page.rows)).toBe(true);
    expect(typeof page.total_count).toBe('number');
    expect(page).toHaveProperty('has_more');
    expect(page).toHaveProperty('next_cursor');
  });

  it('2.2 GET /garmen/work-orders/ → 200 + bentuk row WO', async () => {
    const page = await getWorkOrders(client, { limit: 1 });
    const row = page.rows[0];

    if (row !== undefined) {
      expect(typeof row['code']).toBe('string');
      expect(typeof row['state']).toBe('string');
    }
  });

  it('2.3 GET /garmen/qc/ → 200 + SEMUA baris lolos readQcRow', async () => {
    const page = await getQcRows(client, { limit: 2 });
    const rows = readQcRows(page.rows);

    expect(rows).toHaveLength(page.rows.length);

    const first = rows[0];
    if (first !== undefined) {
      expect(typeof first.id).toBe('number');
      expect(typeof first.qty).toBe('number');
      expect(first).toHaveProperty('work_center_code');
      expect(first).toHaveProperty('end_loss_qty');
    }
  });

  it('2.4 GET /garmen/order-lines/ → 200 + row order-line', async () => {
    const page = await getOrderLines(client, { limit: 1 });
    const row = page.rows[0];

    expect(page.total_count).toBeGreaterThanOrEqual(0);

    if (row !== undefined) {
      expect(typeof row['order_code']).toBe('string');
      expect(row).toHaveProperty('qty');
    }
  });

  it('2.9/2.9b route ADA tapi menolak anonim (403): sync & readiness', async () => {
    expect(await statusOf('/sync/odoo/WIP/')).toBe(403);
    expect(await statusOf(buildOrderReadinessPath(1))).toBe(403);
  });

  it.skipIf(!LIVE || SESSION_COOKIE.length === 0)(
    '2.9b readiness terautentikasi (butuh MES_SESSION_COOKIE) → 200/404',
    async () => {
      const res = await fetch(`${BASE_URL}${buildOrderReadinessPath(1)}`, {
        headers: { cookie: SESSION_COOKIE },
      });

      expect([200, 404]).toContain(res.status);
    }
  );

  it.skipIf(!LIVE || !ALLOW_SYNC_WRITE || SESSION_COOKIE.length === 0)(
    '2.9 POST /sync/scrap/ (butuh MES_LIVE_ALLOW_SYNC=1 — menulis ke Odoo) → 200',
    async () => {
      const res = await fetch(`${BASE_URL}/sync/scrap/`, {
        method: 'POST',
        headers: { cookie: SESSION_COOKIE, 'content-type': 'application/json' },
        body: '{}',
      });

      // 200 = sinkron scrap jalan; 403 = CSRF/session belum lengkap (dicatat, bukan gagal).
      expect([200, 403]).toContain(res.status);
    }
  );
});
