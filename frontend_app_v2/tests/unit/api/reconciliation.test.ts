import { describe, expect, it, vi } from 'vitest';
import {
  buildReconciliationReportPath,
  getReconciliationReport,
  parseReconciliationDays,
  readReconciliationEntry,
  readReconciliationReport,
  RECONCILIATION_DAYS_DEFAULT,
  RECONCILIATION_DAYS_MAX,
  RECONCILIATION_DAYS_MIN,
  RECONCILIATION_REPORT_PATH,
} from '@/api/reconciliation';
import { MODE } from '@/api/_adapter';
import { createApiClient, type ApiClient, type ApiResponse } from '@/integrations/api-client';

/**
 * F9/9.0 — adapter rekonsiliasi BARU: `GET /reconciliation/report/?days=N` (§6.2).
 *
 * Bentuk respons di bawah = PERSIS backend (`ReconciliationReportView.get` →
 * `ReconciliationService.report`): `{days, count, entries[]}`. docs §6.2 menulis `rows`.
 */

const LIVE_BODY = {
  days: 7,
  count: 2,
  entries: [
    {
      run_at: '2026-10-07T03:00:00Z',
      product_code: 'KAIN-COTTON-30S',
      product_odoo_id: 99,
      mes_qty: 100,
      odoo_qty: 105,
      diff: -5,
      is_alert: true,
      notes: 'Top 5 alerts',
    },
    {
      run_at: '2026-10-07T03:00:00Z',
      product_code: null,
      product_odoo_id: 100,
      mes_qty: 10,
      odoo_qty: 10,
      diff: 0,
      is_alert: false,
      notes: null,
    },
  ],
};

function stubClient(data: unknown): { client: ApiClient; paths: string[] } {
  const paths: string[] = [];

  const client = {
    get: async <T,>(path: string): Promise<ApiResponse<T>> => {
      paths.push(path);

      return { ok: true, status: 200, data: data as T };
    },
  } as unknown as ApiClient;

  return { client, paths };
}

describe('F9 — MODE & path rekonsiliasi', () => {
  it('MODE reconciliation = real (endpoint §6.2 ADA)', () => {
    expect(MODE['reconciliation']).toBe('real');
  });

  it('path + query days eksplisit', () => {
    expect(RECONCILIATION_REPORT_PATH).toBe('/reconciliation/report/');
    expect(buildReconciliationReportPath(7)).toBe('/reconciliation/report/?days=7');
    expect(RECONCILIATION_DAYS_DEFAULT).toBe(7);
    expect(RECONCILIATION_DAYS_MIN).toBe(1);
    expect(RECONCILIATION_DAYS_MAX).toBe(90);
  });

  it('getReconciliationReport memakai path itu apa adanya', async () => {
    const { client, paths } = stubClient(LIVE_BODY);

    await getReconciliationReport(client, 30);

    expect(paths).toEqual(['/reconciliation/report/?days=30']);
  });
});

describe('F9 — parseReconciliationDays (validasi 1..90 seperti backend)', () => {
  it('string angka valid diterima', () => {
    expect(parseReconciliationDays('1')).toBe(1);
    expect(parseReconciliationDays('7')).toBe(7);
    expect(parseReconciliationDays(' 90 ')).toBe(90);
  });

  it('di luar 1..90 / bukan angka → null (backend akan balas 400)', () => {
    expect(parseReconciliationDays('0')).toBeNull();
    expect(parseReconciliationDays('100')).toBeNull();
    expect(parseReconciliationDays('-3')).toBeNull();
    expect(parseReconciliationDays('7.5')).toBeNull();
    expect(parseReconciliationDays('tujuh')).toBeNull();
    expect(parseReconciliationDays('')).toBeNull();
    expect(parseReconciliationDays(null)).toBeNull();
    expect(parseReconciliationDays(undefined)).toBeNull();
    expect(parseReconciliationDays(0)).toBeNull();
    expect(parseReconciliationDays(91)).toBeNull();
  });

  it('number valid diterima apa adanya', () => {
    expect(parseReconciliationDays(7)).toBe(7);
    expect(parseReconciliationDays(90)).toBe(90);
  });
});

describe('F9 — readReconciliationReport', () => {
  it('respons backend {days,count,entries} → report (nilai null dipertahankan)', async () => {
    const { client } = stubClient(LIVE_BODY);

    const report = await getReconciliationReport(client, 7);

    expect(report.days).toBe(7);
    expect(report.count).toBe(2);
    expect(report.entries).toHaveLength(2);
    expect(report.entries[0]?.is_alert).toBe(true);
    expect(report.entries[1]?.product_code).toBeNull();
    expect(report.entries[1]?.is_alert).toBe(false);
  });

  it('docs §6.2 memakai `rows` → tetap diterima', () => {
    const parsed = readReconciliationReport({ days: 7, rows: LIVE_BODY.entries });

    expect(parsed?.entries).toHaveLength(2);
    expect(parsed?.count).toBe(2);
  });

  it('`is_alert` hanya true kalau boolean true (bukan truthy asing)', () => {
    expect(readReconciliationEntry({ is_alert: 'ya' })?.is_alert).toBe(false);
    expect(readReconciliationEntry({ is_alert: 1 })?.is_alert).toBe(false);
    expect(readReconciliationEntry({ is_alert: true })?.is_alert).toBe(true);
  });

  it('baris bukan objek dibuang; envelope tak dikenal → null', () => {
    expect(readReconciliationEntry('rusak')).toBeNull();

    const parsed = readReconciliationReport({ days: 7, entries: [{ mes_qty: 1 }, 5] });

    expect(parsed?.entries).toHaveLength(1);
    expect(parsed?.entries[0]?.product_code).toBeNull();

    expect(readReconciliationReport(null)).toBeNull();
    expect(readReconciliationReport({ entries: [] })).toBeNull();
    expect(readReconciliationReport({ days: 7, entries: 'bukan-array' })).toBeNull();
  });
});


/**
 * F9/9.0 — jalur HTTP (400 days / 403 tanpa session) + credentials/URL lewat api-client.
 */

describe('F9 — error HTTP', () => {
  it('400 (days di luar 1..90) → melempar pesan backend', async () => {
    const client = {
      get: async <T,>(): Promise<ApiResponse<T>> => ({
        ok: false,
        status: 400,
        error: { kind: 'http_error', message: 'Parameter days=0 tidak valid.' },
      }),
    } as unknown as ApiClient;

    await expect(getReconciliationReport(client, 0)).rejects.toThrow(/days=0/);
  });

  it('403 (perlu session) → melempar pesan', async () => {
    const client = {
      get: async <T,>(): Promise<ApiResponse<T>> => ({
        ok: false,
        status: 403,
        error: { kind: 'http_error', message: 'HTTP 403' },
      }),
    } as unknown as ApiClient;

    await expect(getReconciliationReport(client, 7)).rejects.toThrow(/403/);
  });

  it('bentuk respons tak dikenali → melempar pesan jelas', async () => {
    const client = {
      get: async <T,>(): Promise<ApiResponse<T>> => ({ ok: true, status: 200, data: {} as T }),
    } as unknown as ApiClient;

    await expect(getReconciliationReport(client, 7)).rejects.toThrow(/tidak dikenali/);
  });

  it('URL penuh + credentials + GET lewat api-client', async () => {
    const calls: { url: string; init: RequestInit }[] = [];

    vi.stubGlobal(
      'fetch',
      vi.fn((url: RequestInfo | URL, init?: RequestInit) => {
        calls.push({ url: String(url), init: init ?? {} });

        return Promise.resolve(
          new Response(JSON.stringify(LIVE_BODY), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          }),
        );
      }),
    );

    try {
      const client = createApiClient({ baseUrl: 'http://localhost:8000/api/v1' });
      await getReconciliationReport(client);

      expect(calls[0]?.url).toBe('http://localhost:8000/api/v1/reconciliation/report/?days=7');
      expect(calls[0]?.init.credentials).toBe('include');
    } finally {
      vi.unstubAllGlobals();
    }
  });
});
