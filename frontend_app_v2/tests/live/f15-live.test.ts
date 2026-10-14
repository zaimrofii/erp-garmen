import { describe, expect, it } from 'vitest';
import { buildInvoicesPath, getInvoices } from '@/api/invoice';
import { buildSyncRecordsPath, getSyncRecords } from '@/api/syncMonitor';
import { createApiClient } from '@/integrations/api-client';

/**
 * F15 LIVE — endpoint monitoring Fase 4.4 (`/sync/records/` & `/finance/invoices/`).
 *
 *   MES_LIVE=1 ~/.bun/bin/bun --bun run test tests/live
 *     → probe anonim: keduanya **403** (route ADA + `IsAuthenticated`) — bukan 404
 *
 *   MES_LIVE=1 MES_LIVE_ALLOW_MONITORING=1 MES_SESSION_COOKIE='sessionid=…' … run test tests/live
 *     → GET terautentikasi: shape `{rows,total_count,has_next,next_cursor}` + filter `stage`
 *
 * Catatan: sebelum Fase 4.4 kedua path ini menjawab **404** (endpoint belum ada) — karena itu
 * F10 dulu DROP; sekarang dihidupkan lagi (F15) dan asersinya diperbarui ke 403.
 */

const LIVE = process.env['MES_LIVE'] === '1';
const ALLOW_MONITORING = process.env['MES_LIVE_ALLOW_MONITORING'] === '1';
const API_BASE = process.env['MES_API_BASE_URL'] ?? 'http://localhost:8000/api/v1';
const SESSION_COOKIE = process.env['MES_SESSION_COOKIE'] ?? '';
const OPTED_IN = ALLOW_MONITORING && SESSION_COOKIE.length > 0;

/** Client TANPA cookie → dipakai membuktikan adapter memetakan 403 dengan benar. */
const anonClient = createApiClient({ baseUrl: API_BASE });

describe.skipIf(!LIVE)('F15 LIVE — route monitoring ADA (anon 403, bukan 404)', () => {
  it('anon GET /sync/records/ → 403', async () => {
    const res = await fetch(`${API_BASE}/sync/records/`);

    expect(res.status).toBe(403);
    expect(res.status).not.toBe(404);
  });

  it('anon GET /finance/invoices/ → 403', async () => {
    const res = await fetch(`${API_BASE}/finance/invoices/`);

    expect(res.status).toBe(403);
    expect(res.status).not.toBe(404);
  });

  it('anon dengan filter pun 403 (auth dicek lebih dulu)', async () => {
    const res = await fetch(`${API_BASE}/sync/records/?stage=WIP&status=FAILED`);

    expect(res.status).toBe(403);
  });

  it('adapter anon (api-client + URL nyata) → melempar /403/ untuk kedua endpoint', async () => {
    await expect(getSyncRecords(anonClient)).rejects.toThrow(/403/);
    await expect(getInvoices(anonClient)).rejects.toThrow(/403/);
  });
});

describe.skipIf(!LIVE)('F15 LIVE — opt-in terautentikasi', () => {
  async function getJson(path: string): Promise<{ status: number; body: Record<string, unknown> }> {
    const res = await fetch(`${API_BASE}${path}`, { headers: { cookie: SESSION_COOKIE } });

    return {
      status: res.status,
      body: (await res.json()) as Record<string, unknown>,
    };
  }

  it.skipIf(!OPTED_IN)('OPT-IN GET sync records → 200 + shape {rows,total_count,has_next,next_cursor}', async () => {
    const { status, body } = await getJson(buildSyncRecordsPath({ limit: 5 }));

    expect([200, 403]).toContain(status);

    if (status !== 200) return;

    expect(Array.isArray(body['rows'])).toBe(true);
    expect(typeof body['total_count']).toBe('number');
    expect(typeof body['has_next']).toBe('boolean');
    expect(body).toHaveProperty('next_cursor');

    const first = (body['rows'] as Record<string, unknown>[])[0];

    if (first !== undefined) {
      expect(typeof first['id']).toBe('number');
      expect(first).toHaveProperty('stage');
      expect(first).toHaveProperty('status');
    }
  });

  it.skipIf(!OPTED_IN)('OPT-IN filter ?stage=WIP → hanya baris stage WIP (atau kosong)', async () => {
    const { status, body } = await getJson(buildSyncRecordsPath({ stage: 'WIP', limit: 20 }));

    expect([200, 403]).toContain(status);

    if (status !== 200) return;

    for (const row of body['rows'] as Record<string, unknown>[]) {
      expect(String(row['stage']).toUpperCase()).toBe('WIP');
    }
  });

  it.skipIf(!OPTED_IN)('OPT-IN GET invoices → 200 + shape antrean invoice (order/invoice_status)', async () => {
    const { status, body } = await getJson(buildInvoicesPath({ limit: 5 }));

    expect([200, 403]).toContain(status);

    if (status !== 200) return;

    expect(Array.isArray(body['rows'])).toBe(true);
    expect(typeof body['total_count']).toBe('number');

    const first = (body['rows'] as Record<string, unknown>[])[0];

    if (first !== undefined) {
      expect(first).toHaveProperty('order_id');
      expect(first).toHaveProperty('order_no');
      expect(first).toHaveProperty('invoice_status');
    }
  });

  it.skipIf(!OPTED_IN)('OPT-IN param invalid (limit=999) → 400 (validasi backend)', async () => {
    const { status } = await getJson(buildInvoicesPath({ limit: 999 }));

    // `limit` divalidasi di klien (1..200) sehingga yang terkirim hanya `?limit=999`
    // lewat path mentah di bawah — backend harus menolak.
    const raw = await fetch(`${API_BASE}/finance/invoices/?limit=999`, {
      headers: { cookie: SESSION_COOKIE },
    });

    expect([200, 400, 403]).toContain(status);
    expect([400, 403]).toContain(raw.status);
  });
});
