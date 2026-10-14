import { afterEach, describe, expect, it, vi } from 'vitest';
import { CUSTOMER_INVOICES_PATH } from '@/api/real/customerInvoices';
import { INVENTORY_OPERATIONS_PATH } from '@/api/real/inventoryOperations';
import { INVOICES_PATH } from '@/api/real/invoice';
import { MASTER_ACCOUNTS_PATH } from '@/api/real/masterAccounts';
import { MASTER_BOMS_PATH } from '@/api/real/masterBoms';
import { MASTER_JOURNALS_PATH } from '@/api/real/masterJournals';
import { MASTER_LOCATIONS_PATH } from '@/api/real/masterLocations';
import { MASTER_PARTNERS_PATH } from '@/api/real/masterPartners';
import { MASTER_PRODUCTION_LINES_PATH } from '@/api/real/masterProductionLines';
import { MASTER_PRODUCTS_PATH } from '@/api/real/masterProducts';
import { MASTER_TAXES_PATH } from '@/api/real/masterTaxes';
import { MASTER_UOMS_PATH } from '@/api/real/masterUoms';
import { MASTER_WORK_CENTERS_PATH } from '@/api/real/masterWorkCenters';
import { ROUTING_GRAPH_PATH } from '@/api/real/routing';
import { SYNC_RECORDS_PATH } from '@/api/real/syncMonitor';
import {
  AUTH_SCOPED_GET_PREFIXES,
  buildRequestUrl,
  createApiClient,
  isAuthScopedGetPath,
  isCrossOriginRequest,
  needsCredentials,
  normalizeApiPath,
  PUBLIC_GET_PREFIXES,
  readCookieValue,
  readCsrfToken,
  type ApiResponse,
} from '@/integrations/api-client';

/** F1 — D5 (auth header sync/audit + CSRF) & D1 (URL request anti double-prefix) + D3 (409). */

const BASE_URL = 'http://localhost:8000/api/v1';
const APP_ORIGIN = 'http://localhost:5173';

interface FetchCall {
  url: string;
  init: RequestInit;
}

function stubFetch(body: unknown, status = 200): FetchCall[] {
  const calls: FetchCall[] = [];

  vi.stubGlobal(
    'fetch',
    vi.fn((url: RequestInfo | URL, init?: RequestInit) => {
      calls.push({ url: String(url), init: init ?? {} });

      return Promise.resolve(
        new Response(JSON.stringify(body), {
          status,
          headers: { 'Content-Type': 'application/json' },
        })
      );
    })
  );

  return calls;
}

function headersOf(call: FetchCall): Record<string, string> {
  return (call.init.headers ?? {}) as Record<string, string>;
}

function stubCookie(cookie: string): void {
  vi.stubGlobal('document', { cookie });
}

function stubOrigin(origin: string): void {
  vi.stubGlobal('location', { origin });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('D1 — buildRequestUrl (endpoint backend sekali prefix saja)', () => {
  it('endpoint relatif → baseUrl + endpoint', () => {
    expect(buildRequestUrl(BASE_URL, '/garmen/bundles/16/BUNDLE_START/')).toBe(
      'http://localhost:8000/api/v1/garmen/bundles/16/BUNDLE_START/'
    );
  });

  it('endpoint absolut → apa adanya', () => {
    expect(buildRequestUrl(BASE_URL, 'https://mes.example.com/x/')).toBe(
      'https://mes.example.com/x/'
    );
  });

  it('endpoint yang sudah /api/v1 → di-dedupe (tidak /api/v1/api/v1)', () => {
    expect(buildRequestUrl(BASE_URL, '/api/v1/garmen/bundles/16/BUNDLE_START/')).toBe(
      'http://localhost:8000/api/v1/garmen/bundles/16/BUNDLE_START/'
    );
  });
});

describe('D5 — kredensial & CSRF', () => {
  it('POST (tulis) mengirim credentials: include + X-CSRFToken dari cookie csrftoken', async () => {
    stubCookie('sessionid=abc; csrftoken=csrf-123');
    const calls = stubFetch({ ok: true });
    const client = createApiClient({ baseUrl: BASE_URL });

    await client.post('/garmen/bundles/16/BUNDLE_START/', { action: 'BUNDLE_START' });

    expect(calls[0]?.init.credentials).toBe('include');
    expect(headersOf(calls[0]!)['X-CSRFToken']).toBe('csrf-123');
    expect(calls[0]?.url).toBe('http://localhost:8000/api/v1/garmen/bundles/16/BUNDLE_START/');
  });

  it('GET /sync/odoo/WIP/ mengirim credentials: include TANPA CSRF', async () => {
    stubCookie('sessionid=abc; csrftoken=csrf-123');
    const calls = stubFetch({ status: 'queued' });
    const client = createApiClient({ baseUrl: BASE_URL });

    await client.get('/sync/odoo/WIP/');

    expect(calls[0]?.init.credentials).toBe('include');
    expect(headersOf(calls[0]!)).not.toHaveProperty('X-CSRFToken');
  });

  it('GET /audit/products-missing-odoo-id/ juga butuh cookie (IsAuthenticated)', async () => {
    const calls = stubFetch({ count: 0 });
    const client = createApiClient({ baseUrl: BASE_URL });

    await client.get('/audit/products-missing-odoo-id/');

    expect(calls[0]?.init.credentials).toBe('include');
  });

  it('GET garmen list (AllowAny) TIDAK diubah: tanpa credentials & tanpa CSRF', async () => {
    stubCookie('csrftoken=csrf-123');
    const calls = stubFetch({ rows: [] });
    const client = createApiClient({ baseUrl: BASE_URL });

    await client.get('/garmen/bundles/?limit=5');

    expect(calls[0]?.init).not.toHaveProperty('credentials');
    expect(headersOf(calls[0]!)).not.toHaveProperty('X-CSRFToken');
  });

  it('lintas origin tetap credentials: include (F1.6 — backend F1.5 sudah Allow-Credentials)', async () => {
    stubOrigin(APP_ORIGIN);
    stubCookie('csrftoken=csrf-123');
    const calls = stubFetch({ ok: true });
    const client = createApiClient({ baseUrl: BASE_URL });

    await client.post('/garmen/bundles/16/BUNDLE_START/', { action: 'BUNDLE_START' });
    await client.get('/sync/odoo/FG/');
    await client.get('/garmen/bundles/?limit=5');

    expect(calls[0]?.init.credentials).toBe('include');
    expect(calls[1]?.init.credentials).toBe('include');
    expect(headersOf(calls[0]!)['X-CSRFToken']).toBe('csrf-123');
    // GET garmen list (AllowAny) tetap TIDAK memakai credentials.
    expect(calls[2]?.init).not.toHaveProperty('credentials');
  });

  it('cookie tanpa csrftoken → header tidak dikirim (jangan kirim nilai kosong)', async () => {
    stubCookie('sessionid=abc');
    const calls = stubFetch({ ok: true });
    const client = createApiClient({ baseUrl: BASE_URL });

    await client.post('/print/bundle-tag/', { bundle_id: 16 });

    expect(headersOf(calls[0]!)).not.toHaveProperty('X-CSRFToken');
  });

  it('helper murni: cookie, cakupan auth, deteksi lintas origin', () => {
    expect(readCookieValue('a=1; csrftoken=abc; b=2', 'csrftoken')).toBe('abc');
    expect(readCookieValue('a=1', 'csrftoken')).toBeNull();
    expect(readCsrfToken('csrftoken=abc')).toBe('abc');
    expect(readCsrfToken('csrftoken=')).toBeNull();
    expect(needsCredentials('POST', '/apa-saja/')).toBe(true);
    expect(needsCredentials('GET', '/sync/odoo/WIP/')).toBe(true);
    expect(needsCredentials('GET', '/reconciliation/report/?days=7')).toBe(true);
    expect(needsCredentials('GET', '/garmen/orders/1/readiness/')).toBe(true);
    expect(needsCredentials('GET', '/garmen/bundles/')).toBe(false);
    expect(isAuthScopedGetPath('/audit/products-missing-odoo-id/')).toBe(true);
    expect(isAuthScopedGetPath('/reconciliation/report/?days=7')).toBe(true);
    // F9/9.0b — readiness (§5.4) juga IsAuthenticated: dulu false (celah lintas origin).
    expect(isAuthScopedGetPath('/garmen/orders/1/readiness/')).toBe(true);
    expect(isAuthScopedGetPath('/garmen/order-lines/')).toBe(false);
    expect(isCrossOriginRequest(`${BASE_URL}/x`, APP_ORIGIN)).toBe(true);
    expect(isCrossOriginRequest('/api/v1/x', APP_ORIGIN)).toBe(false);
    expect(isCrossOriginRequest(`${BASE_URL}/x`, null)).toBe(false);
  });
});

describe('D3 — 409 turun lewat api-client (top-level dulu, alias fallback)', () => {
  it('body kontrak v4.3 (current top-level) → res.conflict.current terisi', async () => {
    const calls = stubFetch(
      {
        current: { version: 'old-sha', state: 'CUTTING', current_work_center: 'SEWING-1' },
        conflict: { current: { version: 'alias-sha', state: 'SABLON' } },
      },
      409
    );
    const client = createApiClient({ baseUrl: BASE_URL });

    const response: ApiResponse<unknown> = await client.post(
      '/garmen/bundles/16/BUNDLE_START/',
      {}
    );

    expect(calls).toHaveLength(1);
    expect(response.ok).toBe(false);
    expect(response.status).toBe(409);
    expect(response.conflict?.current).toEqual({
      version: 'old-sha',
      state: 'CUTTING',
      current_work_center: 'SEWING-1',
    });
  });

  it('body alias lama (hanya conflict.current) → tetap terbaca', async () => {
    stubFetch({ conflict: { current: { version: 'alias-sha', state: 'SABLON' } } }, 409);
    const client = createApiClient({ baseUrl: BASE_URL });

    const response: ApiResponse<unknown> = await client.post(
      '/garmen/bundles/16/BUNDLE_START/',
      {}
    );

    expect(response.conflict?.current).toEqual({ version: 'alias-sha', state: 'SABLON' });
  });
});

describe('FIX 403 (H3.4) — GET endpoint sesi (master/routing) wajib membawa cookie', () => {
  it('PURE — `/master/*` & `/routing/graph/` butuh credentials, publik tetap tidak', () => {
    expect(needsCredentials('GET', '/master/uoms/')).toBe(true);
    expect(needsCredentials('GET', '/master/products/?limit=50')).toBe(true);
    expect(needsCredentials('GET', '/master/partners/?search=pt')).toBe(true);
    expect(needsCredentials('GET', '/routing/graph/?product_id=7')).toBe(true);
    expect(isAuthScopedGetPath('/master/accounts/?active=true')).toBe(true);
    // Path yang sudah membawa prefix `/api/v1` juga dikenali (anti-celah D1).
    expect(needsCredentials('GET', '/api/v1/master/taxes/')).toBe(true);
    // Default AMAN: endpoint baru yang belum terdaftar di mana pun tetap butuh sesi.
    expect(needsCredentials('GET', '/apa-saja-baru/')).toBe(true);
    // `AllowAny` (bukti probe live) tetap tanpa cookie.
    expect(needsCredentials('GET', '/garmen/bundles/?limit=5')).toBe(false);
    expect(needsCredentials('GET', '/garmen/order-lines/')).toBe(false);
    expect(needsCredentials('GET', '/metadata/bundle')).toBe(false);
    expect(needsCredentials('GET', '/devices/me')).toBe(false);
    expect(needsCredentials('GET', '/chatter/')).toBe(false);
  });

  it('PURE — normalizeApiPath menyamakan path ber-prefix `/api/v1`', () => {
    expect(normalizeApiPath('  /api/v1/master/uoms/?limit=5 ')).toBe('/master/uoms/?limit=5');
    expect(normalizeApiPath('/master/uoms/')).toBe('/master/uoms/');
    expect(normalizeApiPath('master/uoms/')).toBe('/master/uoms/');
    expect(normalizeApiPath('')).toBe('/');
  });

  it('inventaris endpoint-sesi TIDAK boleh tercatat publik (anti kontradiksi)', () => {
    for (const prefix of AUTH_SCOPED_GET_PREFIXES) {
      expect(PUBLIC_GET_PREFIXES.some((item) => prefix.startsWith(item))).toBe(false);
      expect(isAuthScopedGetPath(prefix)).toBe(true);
    }
  });

  it('drift — path adapter master/finance/sync yang dipakai UI semua mengirim cookie', () => {
    const paths = [
      CUSTOMER_INVOICES_PATH,
      INVENTORY_OPERATIONS_PATH,
      INVOICES_PATH,
      MASTER_ACCOUNTS_PATH,
      MASTER_BOMS_PATH,
      MASTER_JOURNALS_PATH,
      MASTER_LOCATIONS_PATH,
      MASTER_PARTNERS_PATH,
      MASTER_PRODUCTION_LINES_PATH,
      MASTER_PRODUCTS_PATH,
      MASTER_TAXES_PATH,
      MASTER_UOMS_PATH,
      MASTER_WORK_CENTERS_PATH,
      ROUTING_GRAPH_PATH,
      SYNC_RECORDS_PATH,
    ];

    expect(paths).toHaveLength(15);
    for (const path of paths) expect(needsCredentials('GET', path)).toBe(true);
  });

  it('client nyata — `GET /master/uoms/` mengirim `credentials: include` (bug 403)', async () => {
    stubOrigin(APP_ORIGIN);
    const calls = stubFetch({ rows: [] });
    const client = createApiClient({ baseUrl: BASE_URL });

    await client.get('/master/uoms/?limit=50');
    await client.get(ROUTING_GRAPH_PATH);
    await client.get('/garmen/bundles/?limit=5');

    expect(calls[0]?.url).toBe(`${BASE_URL}/master/uoms/?limit=50`);
    expect(calls[0]?.init.credentials).toBe('include');
    expect(calls[1]?.init.credentials).toBe('include');
    // Publik tetap tidak membawa cookie (perilaku lama dipertahankan).
    expect(calls[2]?.init).not.toHaveProperty('credentials');
  });
});

