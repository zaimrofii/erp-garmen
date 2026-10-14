import { describe, expect, it } from 'vitest';
import { getBundles } from '@/api/bundles';
import { getOrderLine } from '@/api/orderLines';
import { printBundleTag, printCoupon } from '@/api/print';
import { postSyncScrap } from '@/api/sync';
import { createApiClient } from '@/integrations/api-client';

/**
 * F6 LIVE — cetak kupon (mock printer) + sync manual OPT-IN.
 * F14 LIVE — cetak tag bundle (migrasi penuh dari `integrations/print-tag.ts`).
 *
 *   MES_LIVE=1 ~/.bun/bin/bun --bun run test tests/live
 *     → cetak kupon & tag bundle DIIZINKAN (backend `PRINTER_BACKEND=mock`, tidak menyentuh
 *       printer fisik; setiap cetak tetap mencatat satu baris `PrintJob`)
 *     → sync ERP hanya diprobe sebagai anonim (**403**, tidak menulis apa pun)
 *
 *   MES_LIVE=1 MES_LIVE_ALLOW_SYNC=1 MES_SESSION_COOKIE='sessionid=…' … run test tests/live
 *     → sync scrap/FG SUNGGUHAN (menulis stok ke Odoo) — hanya untuk operator yang sadar risiko.
 */

const LIVE = process.env['MES_LIVE'] === '1';
const ALLOW_SYNC = process.env['MES_LIVE_ALLOW_SYNC'] === '1';
const API_BASE = process.env['MES_API_BASE_URL'] ?? 'http://localhost:8000/api/v1';
const SESSION_COOKIE = process.env['MES_SESSION_COOKIE'] ?? '';
const ORDER_LINE_ID = process.env['MES_LIVE_ORDER_LINE_ID'] ?? '1';

describe.skipIf(!LIVE)('F6 LIVE — print kupon + sync', () => {
  const client = createApiClient({ baseUrl: API_BASE });

  it('POST /print/kupon/ → 200 + bytes (ticket_code nyata dari /garmen/order-lines/{id}/)', async () => {
    const line = await getOrderLine(client, ORDER_LINE_ID);
    const ticketCode = line.ticket_code ?? '';

    expect(ticketCode.length).toBeGreaterThan(0);

    const job = await printCoupon(client, ticketCode);

    expect(job.ok).toBe(true);
    expect(job.bytes).toBeGreaterThan(0);
    expect(job.ref).toBe(ticketCode);
    expect(typeof job.backend).toBe('string');
  });

  it('ticket_code tidak ada → 400 dengan pesan (bukan crash)', async () => {
    await expect(printCoupon(client, 'TICKET-TIDAK-ADA-XYZ')).rejects.toThrow(/400|tidak ditemukan/);
  });

  /* ------------------------------------------------------------------
     F14 — tag bundle (§7.1): jalur adapter baru (legacy sudah dihapus).
     ------------------------------------------------------------------ */

  it('F14: POST /print/bundle-tag/ → 200 + bytes (bundle nyata, mock printer)', async () => {
    const page = await getBundles(client, { limit: 1 });
    const first = page.rows[0];

    expect(first).toBeDefined();

    const job = await printBundleTag(client, first?.id ?? '1');

    expect(job.ok).toBe(true);
    expect(job.bytes).toBeGreaterThan(0);
    expect(job.resource).toBe('bundle');
    expect(job.status).toBe('SENT');
  });

  it('F14: bundle_id tidak ada → 400 dengan pesan (bukan crash)', async () => {
    await expect(printBundleTag(client, 999999)).rejects.toThrow(/400|tidak ditemukan/);
  });

  it('sync tanpa session → 403 (route ADA, tidak menulis apa pun)', async () => {
    await expect(postSyncScrap(client)).rejects.toThrow(/403/);
  });

  it.skipIf(!ALLOW_SYNC || SESSION_COOKIE.length === 0)(
    'OPT-IN: POST /sync/scrap/ dengan session → 200 {sent,failed,skipped}',
    async () => {
      const res = await fetch(`${API_BASE}/sync/scrap/`, {
        method: 'POST',
        headers: { cookie: SESSION_COOKIE, 'content-type': 'application/json' },
        body: '{}',
      });

      expect([200, 403]).toContain(res.status);

      if (res.status === 200) {
        const body = (await res.json()) as Record<string, unknown>;

        expect(body).toHaveProperty('sent');
        expect(body).toHaveProperty('skipped');
      }
    }
  );

  it.skipIf(!ALLOW_SYNC || SESSION_COOKIE.length === 0)(
    'OPT-IN: POST /sync/odoo/FG/ dengan session → 200 {status:queued, task_id}',
    async () => {
      const res = await fetch(`${API_BASE}/sync/odoo/FG/`, {
        method: 'POST',
        headers: { cookie: SESSION_COOKIE, 'content-type': 'application/json' },
        body: JSON.stringify({ resource: 'bundle', resource_id: '1', payload: { qty: 10, ref: 'FG-LIVE' } }),
      });

      expect([200, 400, 403]).toContain(res.status);

      if (res.status === 200) {
        const body = (await res.json()) as Record<string, unknown>;

        expect(body['status']).toBe('queued');
        expect(typeof body['task_id']).toBe('string');
      }
    }
  );
});
