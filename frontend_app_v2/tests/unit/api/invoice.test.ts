import { describe, expect, it, vi } from 'vitest';
import {
  buildInvoicesPath,
  getInvoices,
  INVOICES_PATH,
  INVOICE_STATUSES,
  parseIntParam,
  parseInvoiceStatus,
  readInvoicePage,
  readInvoiceRow,
} from '@/api/invoice';
import { MODE } from '@/api/_adapter';
import { createApiClient, type ApiClient, type ApiResponse } from '@/integrations/api-client';

/**
 * F15 — adapter antrean invoice BARU (`GET /finance/invoices/`, Fase 4.4).
 *
 * Bentuk di bawah = PERSIS backend `monitoring.InvoiceListView`: envelope
 * `{rows, total_count, has_next, next_cursor}` dan baris `{order_id, order_no,
 * invoice_status, erp_id, attempts, last_error, sent_at, created_at}`.
 * `IsAuthenticated` → anonim 403.
 */

const LIVE_BODY = {
  rows: [
    {
      order_id: 1,
      order_no: 'SO-001',
      invoice_status: 'SENT',
      erp_id: 'INV/2026/0001',
      attempts: 1,
      last_error: null,
      sent_at: '2026-10-08T03:00:00Z',
      created_at: '2026-10-08T02:59:00Z',
    },
    {
      order_id: null,
      order_no: null,
      invoice_status: 'PENDING',
      erp_id: null,
      attempts: 0,
      last_error: null,
      sent_at: null,
      created_at: '2026-10-08T02:00:00Z',
    },
  ],
  total_count: 2,
  has_next: false,
  next_cursor: null,
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

describe('F15 — MODE & path invoice', () => {
  it('MODE invoiceQueue = real (endpoint Fase 4.4 ADA)', () => {
    expect(MODE['invoiceQueue']).toBe('real');
  });

  it('path default tanpa query param', async () => {
    expect(INVOICES_PATH).toBe('/finance/invoices/');
    expect(buildInvoicesPath()).toBe('/finance/invoices/');

    const { client, paths } = stubClient(LIVE_BODY);

    await getInvoices(client);

    expect(paths).toEqual(['/finance/invoices/']);
  });

  it('filter state (status sync) + limit divalidasi sebelum dikirim', () => {
    expect(buildInvoicesPath({ state: 'sent' })).toBe('/finance/invoices/?state=SENT');
    expect(buildInvoicesPath({ state: 'NGAWUR' })).toBe('/finance/invoices/');
    expect(buildInvoicesPath({ limit: 25 })).toBe('/finance/invoices/?limit=25');
    expect(buildInvoicesPath({ cursor: 50 })).toBe('/finance/invoices/?cursor=50');
    expect(buildInvoicesPath({ cursor: 0 })).toBe('/finance/invoices/');
    expect(buildInvoicesPath({ state: 'FAILED', limit: 10, cursor: 20 })).toBe(
      '/finance/invoices/?state=FAILED&limit=10&cursor=20',
    );
  });

  it('parseIntParam & parseInvoiceStatus (batas 1..200 / offset)', () => {
    expect(parseIntParam('50', 1, 200)).toBe(50);
    expect(parseIntParam('0', 1, 200)).toBeNull();
    expect(parseIntParam('201', 1, 200)).toBeNull();
    expect(parseIntParam('x', 1, 200)).toBeNull();
    expect(parseIntParam('', 1, 200)).toBeNull();
    expect(parseIntParam(null, 1, 200)).toBeNull();
    expect(parseInvoiceStatus('pending')).toBe('PENDING');
    expect(parseInvoiceStatus(' DRAFT ')).toBeNull();
    expect(INVOICE_STATUSES).toEqual(['PENDING', 'SENT', 'FAILED', 'DUPLICATE']);
  });
});

describe('F15 — readInvoicePage', () => {
  it('respons Fase 4.4 → InvoicePage (null dipertahankan)', async () => {
    const { client } = stubClient(LIVE_BODY);

    const page = await getInvoices(client);

    expect(page.total_count).toBe(2);
    expect(page.has_next).toBe(false);
    expect(page.next_cursor).toBeNull();
    expect(page.rows).toHaveLength(2);
    expect(page.rows[0]?.order_no).toBe('SO-001');
    expect(page.rows[0]?.invoice_status).toBe('SENT');
    expect(page.rows[1]?.order_id).toBeNull();
    expect(page.rows[1]?.erp_id).toBeNull();
  });

  it('envelope menerima `has_more` juga; baris non-objek dibuang', () => {
    const parsed = readInvoicePage({
      rows: [{ order_id: 3, invoice_status: 'FAILED' }, 'rusak'],
      total_count: 5,
      has_more: true,
      next_cursor: 1,
    });

    expect(parsed?.rows).toHaveLength(1);
    expect(parsed?.has_next).toBe(true);
    expect(parsed?.rows[0]?.attempts).toBe(0);
    expect(readInvoiceRow(null)).toBeNull();
  });

  it('envelope tak dikenal → null', () => {
    expect(readInvoicePage(null)).toBeNull();
    expect(readInvoicePage({ total_count: 0 })).toBeNull();
    expect(readInvoicePage({ rows: 'bukan-array' })).toBeNull();
  });
});

describe('F15 — error HTTP & jalur api-client', () => {
  it('403 (perlu session) → melempar pesan', async () => {
    const client = {
      get: async <T,>(): Promise<ApiResponse<T>> => ({
        ok: false,
        status: 403,
        error: { kind: 'http_error', message: 'HTTP 403' },
      }),
    } as unknown as ApiClient;

    await expect(getInvoices(client)).rejects.toThrow(/403/);
  });

  it('400 (param invalid) → melempar pesan backend', async () => {
    const client = {
      get: async <T,>(): Promise<ApiResponse<T>> => ({
        ok: false,
        status: 400,
        error: { kind: 'http_error', message: "Parameter 'limit' harus antara 1 dan 200." },
      }),
    } as unknown as ApiClient;

    await expect(getInvoices(client, { limit: 201 })).rejects.toThrow(/limit/);
  });

  it('bentuk respons tak dikenali → melempar pesan jelas', async () => {
    const { client } = stubClient({ ok: true });

    await expect(getInvoices(client)).rejects.toThrow(/tidak dikenali/);
  });

  it('URL penuh + credentials (GET auth-scoped) lewat api-client', async () => {
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
      await getInvoices(client, { state: 'SENT', limit: 10 });

      expect(calls[0]?.url).toBe(
        'http://localhost:8000/api/v1/finance/invoices/?state=SENT&limit=10',
      );
    } finally {
      vi.unstubAllGlobals();
    }
  });
});
