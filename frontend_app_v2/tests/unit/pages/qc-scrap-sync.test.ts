import { readFileSync } from 'node:fs';
import path from 'node:path';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { createApiClient } from '@/integrations/api-client';
import { canSyncScrap, runScrapSync } from '@/lib/sync-actions';

/**
 * F6/6.3 — tombol "Sync Scrap" di halaman QC.
 *
 * `POST /sync/scrap/` mengirim SEMUA ScrapAccumulator pending ke Odoo (efek nyata) dan
 * endpoint-nya `IsAuthenticated` → diuji lewat `runScrapSync` (fetch di-stub) + guard
 * state, bukan dengan menembak backend sungguhan.
 */

const ROOT = path.resolve(import.meta.dirname, '../../..');

function stubFetch(status = 200, body: unknown = { sent: 3, failed: 0, skipped: 1 }) {
  const calls: { url: string; init: RequestInit }[] = [];

  vi.stubGlobal(
    'fetch',
    vi.fn((url: RequestInfo | URL, init?: RequestInit) => {
      calls.push({ url: String(url), init: init ?? {} });

      return Promise.resolve(
        new Response(JSON.stringify(status === 200 ? body : { detail: 'Autentikasi diperlukan.' }), {
          status,
          headers: { 'Content-Type': 'application/json' },
        }),
      );
    }),
  );

  return { calls };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('F6/6.3 — runScrapSync', () => {
  it('POST /api/v1/sync/scrap/ + ringkasan {sent,failed,skipped}', async () => {
    const { calls } = stubFetch();
    const client = createApiClient({ baseUrl: 'http://localhost:8000/api/v1' });

    const outcome = await runScrapSync(client);

    expect(calls[0]?.url).toBe('http://localhost:8000/api/v1/sync/scrap/');
    expect(calls[0]?.init.method).toBe('POST');
    expect(calls[0]?.init.credentials).toBe('include');
    expect(outcome.ok).toBe(true);
    expect(outcome.message).toContain('3 sukses');
    expect(outcome.message).toContain('1 dilewati');
  });

  it('403 (tanpa session) → union gagal, TIDAK throw', async () => {
    stubFetch(403);
    const client = createApiClient({ baseUrl: 'http://localhost:8000/api/v1' });

    const outcome = await runScrapSync(client);

    expect(outcome.ok).toBe(false);
    // F6.2: `api-client` kini membaca `detail` DRF (sebelumnya pesan generik "HTTP 403"),
    // jadi teks backend yang sampai ke user.
    expect(outcome.message).toContain('Autentikasi diperlukan.');
  });

  it('guard state: hanya QC', () => {
    expect(canSyncScrap('QC')).toBe(true);
    expect(canSyncScrap('CUTTING')).toBe(false);
    expect(canSyncScrap('')).toBe(false);
  });
});

describe('F6/6.3+6.5 — wiring halaman QC', () => {
  it('QCPage memuat tombol Sync Scrap + handler feedback/toast', () => {
    const source = readFileSync(path.join(ROOT, 'src/pages/production/QCPage.tsx'), 'utf8');

    expect(source).toContain("import { canSyncScrap, runScrapSync } from '@/lib/sync-actions'");
    expect(source).toContain('runScrapSync(client)');
    expect(source).toContain('canSyncScrap(bundle.state)');
    expect(source).toContain('Sync Scrap');
    expect(source).toContain("trigger(outcome.ok ? 'success' : 'error')");
    expect(source).toContain('<Toast');
  });

  it('halaman bundle (production) memakai runBundleStageSync + printCoupon + Toast', () => {
    const source = readFileSync(
      path.join(ROOT, 'src/pages/production/BundleDetailPage.tsx'),
      'utf8',
    );

    expect(source).toContain('<SyncActionsCard');
    expect(source).toContain('runBundleStageSync(client, stage');
    expect(source).toContain('printCoupon(client, ticketCode)');
    expect(source).toContain('<Toast');
    // bundle-tag lama TIDAK diubah/diduplikasi
    expect(source).toContain('<PrintTagButton');
  });
});
