import { describe, expect, it } from 'vitest';
import { buildQualityDefectsPath, buildQualityReworkPath } from '@/api/qc';
import { buildInventoryOperationsPath } from '@/api/inventory';

/**
 * F2C.2 LIVE — 10 adapter real vs backend Django yang sedang jalan.
 *
 * Dijalankan HANYA kalau `MES_LIVE=1` (default: skip → `bun run test` tetap hijau
 * tanpa backend). Contoh:
 *
 *   MES_LIVE=1 ~/.bun/bin/bun --bun run test tests/live
 *   MES_LIVE=1 MES_SESSION_COOKIE='sessionid=…; csrftoken=…' … run test tests/live
 *
 * Endpoint F1/F2 memakai `IsAuthenticated` → tanpa cookie bisa 403. Uji ini
 * menerima 200 (bentuk divalidasi) ATAU 403 (route ada, auth kurang).
 */

const LIVE = process.env['MES_LIVE'] === '1';
const BASE_URL = process.env['MES_API_BASE_URL'] ?? 'http://localhost:8000/api/v1';
const SESSION_COOKIE = process.env['MES_SESSION_COOKIE'] ?? '';

const OK_OR_FORBIDDEN = [200, 403];

async function probe(path: string): Promise<{ status: number; body: unknown }> {
  const headers: Record<string, string> = {};
  if (SESSION_COOKIE.length > 0) headers['cookie'] = SESSION_COOKIE;

  const res = await fetch(`${BASE_URL}${path}`, { headers });
  let body: unknown = null;

  try {
    body = await res.json();
  } catch {
    body = null;
  }

  return { status: res.status, body };
}

async function expectListEnvelope(path: string): Promise<void> {
  const { status, body } = await probe(path);

  expect(OK_OR_FORBIDDEN).toContain(status);

  if (status === 200 && typeof body === 'object' && body !== null) {
    const record = body as Record<string, unknown>;

    expect(Array.isArray(record['rows'])).toBe(true);
    expect(typeof record['total_count']).toBe('number');
    expect(record).toHaveProperty('has_more');
    expect(record).toHaveProperty('next_cursor');
  }
}

describe.skipIf(!LIVE)('F2C.2 LIVE — 10 endpoint real', () => {
  it('1 dashboard /dashboard/summary/', async () => {
    const { status, body } = await probe('/dashboard/summary/');

    expect(OK_OR_FORBIDDEN).toContain(status);

    if (status === 200 && body !== null) {
      const record = body as Record<string, unknown>;

      expect(typeof record['wip_qty']).toBe('number');
      expect(Array.isArray(record['trend'])).toBe(true);
      expect(record).toHaveProperty('line_efficiency');
    }
  });

  it('2 bufferQueue /production/buffer-queue/', async () => {
    const { status, body } = await probe('/production/buffer-queue/');

    expect(OK_OR_FORBIDDEN).toContain(status);

    if (status === 200 && body !== null) {
      expect(Array.isArray((body as Record<string, unknown>)['rows'])).toBe(true);
    }
  });

  it('3 qcLog /quality/defects/ (ListPage)', async () => {
    await expectListEnvelope(buildQualityDefectsPath({ limit: 2 }));
  });

  it('4 qcRework /quality/rework/ (ListPage)', async () => {
    await expectListEnvelope(buildQualityReworkPath({ limit: 2 }));
  });

  it('5 inventoryOperations /inventory/operations/ (ListPage)', async () => {
    await expectListEnvelope(buildInventoryOperationsPath({ limit: 2 }));
  });

  it('6 purchaseVendors /purchase/vendors/', async () => {
    await expectListEnvelope('/purchase/vendors/?limit=2');
  });

  it('7 purchaseOrders /purchase/orders/', async () => {
    await expectListEnvelope('/purchase/orders/?limit=2');
  });

  it('8 purchaseReporting /purchase/reporting/', async () => {
    const { status, body } = await probe('/purchase/reporting/');

    expect(OK_OR_FORBIDDEN).toContain(status);

    if (status === 200 && body !== null) {
      const record = body as Record<string, unknown>;

      expect(typeof record['total_po']).toBe('number');
      expect(Array.isArray(record['monthly_series'])).toBe(true);
    }
  });

  it('9 reportsLineEfficiency /reports/line-efficiency/', async () => {
    const { status, body } = await probe('/reports/line-efficiency/');

    expect(OK_OR_FORBIDDEN).toContain(status);

    if (status === 200 && body !== null) {
      expect(Array.isArray((body as Record<string, unknown>)['rows'])).toBe(true);
    }
  });

  it('10 reportsWIP /reports/wip/ (rows saat group_by=wc)', async () => {
    const { status, body } = await probe('/reports/wip/?group_by=wc');

    expect(OK_OR_FORBIDDEN).toContain(status);

    if (status === 200 && body !== null) {
      expect(typeof (body as Record<string, unknown>)['total_wip']).toBe('number');
    }
  });
});
