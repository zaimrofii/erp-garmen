import { existsSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import {
  buildPrintBundleTagBody,
  printBundleTag,
  printCoupon,
  PRINT_BUNDLE_TAG_PATH,
  PRINT_COUPON_PATH,
  readPrintJob,
} from '@/api/print';
import type { ApiClient, ApiResponse } from '@/integrations/api-client';

/**
 * F6 — adapter cetak kupon (`src/api/real/print.ts` + barrel `src/api/print.ts`).
 *
 * Kontrak §7.2 NYATA (dikonfirmasi live): body `{ticket_code}` — BUKAN `{bundle_id}` —
 * dan endpoint `AllowAny` (POST body kosong → 400, bukan 403/404).
 */

const LIVE_RESPONSE = {
  ok: true,
  resource: 'coupon',
  resource_id: '1',
  bytes: 448,
  backend: 'mock',
  print_job_id: 12,
  ref: 'TKT-001',
  status: 'SENT',
};

function stubClient(data: unknown, ok = true, status = 200): { client: ApiClient; calls: { path: string; body: unknown }[] } {
  const calls: { path: string; body: unknown }[] = [];

  const client = {
    post: async <T,>(path: string, body: unknown): Promise<ApiResponse<T>> => {
      calls.push({ path, body });

      return ok ? { ok: true, status, data: data as T } : { ok: false, status, error: { kind: 'http_error', message: String(data) } };
    },
  } as unknown as ApiClient;

  return { client, calls };
}

describe('F6 — printCoupon', () => {
  it('path /print/kupon/ + body {ticket_code} (kontrak §7.2)', async () => {
    const { client, calls } = stubClient(LIVE_RESPONSE);

    const job = await printCoupon(client, '  TKT-001  ');

    expect(calls).toEqual([{ path: PRINT_COUPON_PATH, body: { ticket_code: 'TKT-001' } }]);
    expect(job).toEqual(LIVE_RESPONSE);
    expect(job.bytes).toBe(448);
  });

  it('400 (kupon/printer gagal) → melempar pesan backend', async () => {
    const { client } = stubClient('Kupon TKT-999 tidak ditemukan.', false, 400);

    await expect(printCoupon(client, 'TKT-999')).rejects.toThrow(/TKT-999/);
  });

  it('bentuk respons tak dikenali → melempar pesan jelas', async () => {
    const { client } = stubClient({ ok: true });

    await expect(printCoupon(client, 'TKT-001')).rejects.toThrow(/tidak dikenali/);
  });
});

describe('F6 — readPrintJob', () => {
  it('respons live → PrintJobResponse', () => {
    expect(readPrintJob(LIVE_RESPONSE)).toEqual(LIVE_RESPONSE);
  });

  it('bukan objek / tanpa ok:true / bytes bukan angka → null', () => {
    expect(readPrintJob(null)).toBeNull();
    expect(readPrintJob('ok')).toBeNull();
    expect(readPrintJob({ ok: false, bytes: 10 })).toBeNull();
    expect(readPrintJob({ ok: true, bytes: 'banyak' })).toBeNull();
  });

  it('field opsional hilang → default aman', () => {
    expect(readPrintJob({ ok: true, bytes: 10 })).toEqual({
      ok: true,
      resource: '',
      resource_id: '',
      bytes: 10,
      backend: 'printer',
      print_job_id: null,
      ref: '',
      status: '',
    });
  });
});

/* --------------------------------------------------------------------------
   F14 — cetak tag bundle (migrasi penuh dari `integrations/print-tag.ts`).
   -------------------------------------------------------------------------- */

const BUNDLE_TAG_RESPONSE = {
  ok: true,
  resource: 'bundle',
  resource_id: '1',
  bytes: 292,
  backend: 'mock',
  print_job_id: 19,
  ref: 'BND-DEMO-001',
  status: 'SENT',
};

describe('F14 — printBundleTag (adsorber baru, §7.1)', () => {
  it('path /print/bundle-tag/ + body {bundle_id} numerik (live: 200 + bytes)', async () => {
    const { client, calls } = stubClient(BUNDLE_TAG_RESPONSE);

    const job = await printBundleTag(client, '1');

    expect(calls).toEqual([
      { path: PRINT_BUNDLE_TAG_PATH, body: { bundle_id: 1 } },
    ]);
    expect(PRINT_BUNDLE_TAG_PATH).toBe('/print/bundle-tag/');
    expect(job).toEqual(BUNDLE_TAG_RESPONSE);
    expect(job.resource).toBe('bundle');
    expect(job.bytes).toBeGreaterThan(0);
  });

  it('id non-numerik dikirim apa adanya (perilaku lama dipertahankan)', () => {
    expect(buildPrintBundleTagBody('BND-1')).toEqual({ bundle_id: 'BND-1' });
    expect(buildPrintBundleTagBody(16)).toEqual({ bundle_id: 16 });
    expect(buildPrintBundleTagBody('')).toEqual({ bundle_id: '' });
    expect(buildPrintBundleTagBody('  7  ')).toEqual({ bundle_id: 7 });
  });

  it('400 (bundle tidak ditemukan) → melempar pesan backend', async () => {
    const { client } = stubClient('Bundle dengan id 999999 tidak ditemukan.', false, 400);

    await expect(printBundleTag(client, 999999)).rejects.toThrow(/999999/);
  });

  it('bentuk respons tak dikenali → melempar pesan jelas', async () => {
    const { client } = stubClient({ ok: true });

    await expect(printBundleTag(client, 1)).rejects.toThrow(/tidak dikenali/);
  });

  it('barrel @/api/print mengekspor printBundleTag + konstanta path', () => {
    expect(typeof printBundleTag).toBe('function');
    expect(buildPrintBundleTagBody('2')).toEqual({ bundle_id: 2 });
  });

  it('dead code lama SUDAH hilang (tidak ada `integrations/print-tag`)', () => {
    const legacy = path.resolve(import.meta.dirname, '../../../src/integrations/print-tag.ts');

    expect(existsSync(legacy)).toBe(false);

    const button = readFileSync(
      path.resolve(import.meta.dirname, '../../../src/components/molecules/PrintTagButton.tsx'),
      'utf8',
    );

    expect(button).toContain("from '@/api/print'");
    expect(button).not.toContain("from '@/integrations/print-tag'");
  });
});
