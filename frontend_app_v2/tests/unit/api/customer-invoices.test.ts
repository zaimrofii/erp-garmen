import { describe, expect, it } from 'vitest';
import {
  actCustomerInvoice,
  buildCustomerInvoicesPath,
  createCustomerInvoice,
  customerInvoiceActionPath,
  CUSTOMER_INVOICES_PATH,
  deleteCustomerInvoice,
  fetchCustomerInvoice,
  fetchCustomerInvoices,
  readCustomerInvoiceDetail,
  readCustomerInvoiceLineRow,
  readCustomerInvoicePage,
  readCustomerInvoiceRow,
  readCustomerInvoiceSaved,
  readCustomerInvoiceState,
  toCustomerInvoiceBody,
  updateCustomerInvoice,
} from '@/api/customerInvoices';
import { MODE } from '@/api/_adapter';
import type { ApiClient, ApiResponse } from '@/integrations/api-client';
import type { CustomerInvoiceInput, CustomerInvoiceRow } from '@/types/customer-invoice';

/**
 * H3.1 — adapter Customer Invoice MES (`/api/v1/finance/customer-invoices/`).
 *
 * Bentuk = PERSIS `garment/services/customer_invoice_services.py`:
 * `{id, code, order_id, order_no, customer_id, customer_name, customer_code,
 * invoice_date, due_date, state, notes, lines_count, amount_total, odoo_id, …}`;
 * detail menambah `{lines[], odoo_sync_status, odoo_sync_error, allowed_actions}`;
 * POST/PUT/aksi menambah `{sync_record_id, task_id, queued}`.
 */

const ROW: CustomerInvoiceRow = {
  id: 7,
  code: 'INV-2026-0001',
  order_id: 3,
  order_no: 'SO-2026-0001',
  customer_id: 10,
  customer_name: 'PT Buyer',
  customer_code: 'CUST-INV',
  invoice_date: '2026-10-12',
  due_date: null,
  state: 'DRAFT',
  notes: '',
  lines_count: 1,
  amount_total: '20000.00',
  odoo_id: null,
  created_at: '2026-10-12T00:00:00+00:00',
  updated_at: '2026-10-12T00:00:00+00:00',
};

const LINE = {
  id: 11,
  order_line_id: 5,
  product_id: 34,
  product_code: 'KAOS-INV',
  product_name: 'Kaos Invoice',
  qty: '5.00',
  price_unit: '4000.00',
  subtotal: '20000.00',
  tax_ids: [19],
  tax_odoo_ids: [19],
  line_total: '20000.00',
  created_at: null,
  updated_at: null,
};

const DETAIL = {
  ...ROW,
  lines: [LINE],
  odoo_sync_status: 'PENDING',
  odoo_sync_error: null,
  allowed_actions: ['CONFIRMED', 'CANCELLED'],
};

const SAVED = {
  ...DETAIL,
  sync_record_id: 3,
  task_id: 'task-inv-1',
  queued: true,
  duplicate_warning: null,
};

const INPUT: CustomerInvoiceInput = {
  order_id: 3,
  invoice_date: '2026-10-12',
  due_date: '2026-11-12',
  notes: ' DP 50% ',
  lines: [{ product_id: 34, qty: 5, price_unit: 4000, tax_ids: [19], order_line_id: 5 }],
};

interface RecordedRequest {
  path: string;
  method: string;
  body?: unknown;
}

function stubClient(data: unknown): { client: ApiClient; requests: RecordedRequest[] } {
  const requests: RecordedRequest[] = [];
  const reply = <T,>(): ApiResponse<T> => ({ ok: true, status: 200, data: data as T });

  const client = {
    get: async <T,>(path: string): Promise<ApiResponse<T>> => {
      requests.push({ path, method: 'GET' });

      return reply<T>();
    },
    post: async <T,>(path: string, body: unknown): Promise<ApiResponse<T>> => {
      requests.push({ path, method: 'POST', body });

      return reply<T>();
    },
    request: async <T,>(
      path: string,
      options?: { method?: 'GET' | 'POST' | 'PUT' | 'DELETE'; body?: unknown },
    ): Promise<ApiResponse<T>> => {
      requests.push({ path, method: options?.method ?? 'GET', body: options?.body });

      return reply<T>();
    },
  } as unknown as ApiClient;

  return { client, requests };
}

function failingClient(status: number, message: string): ApiClient {
  const response = <T,>(): ApiResponse<T> => ({
    ok: false,
    status,
    error: { kind: 'http_error', message },
  });

  return {
    request: async <T,>(): Promise<ApiResponse<T>> => response<T>(),
    get: async <T,>(): Promise<ApiResponse<T>> => response<T>(),
    post: async <T,>(): Promise<ApiResponse<T>> => response<T>(),
  } as unknown as ApiClient;
}

describe('H3.1 — MODE & path customer invoice', () => {
  it('MODE.customerInvoices = real & MODE.invoiceQueue (F15) tetap real', () => {
    expect(MODE['customerInvoices']).toBe('real');
    expect(MODE['invoiceQueue']).toBe('real');
    expect(CUSTOMER_INVOICES_PATH).toBe('/finance/customer-invoices/');
  });

  it('buildCustomerInvoicesPath: default tanpa query, param terisi saja', () => {
    expect(buildCustomerInvoicesPath()).toBe('/finance/customer-invoices/');
    expect(buildCustomerInvoicesPath({ search: 'inv', state: 'DRAFT' })).toBe(
      '/finance/customer-invoices/?search=inv&state=DRAFT',
    );
    expect(buildCustomerInvoicesPath({ customer_id: 10, order_id: 3 })).toBe(
      '/finance/customer-invoices/?customer_id=10&order_id=3',
    );
    expect(buildCustomerInvoicesPath({ limit: 200, cursor: 20 })).toBe(
      '/finance/customer-invoices/?limit=200&cursor=20',
    );
  });

  it('customerInvoiceActionPath: confirm/done/cancel', () => {
    expect(customerInvoiceActionPath(7, 'confirm')).toBe('/finance/customer-invoices/7/confirm/');
    expect(customerInvoiceActionPath(7, 'cancel')).toBe('/finance/customer-invoices/7/cancel/');
  });
});

describe('H3.1 — parsing baris, detail & payload', () => {
  it('readCustomerInvoiceState: nilai sah saja; lain → DRAFT', () => {
    expect(readCustomerInvoiceState('CONFIRMED')).toBe('CONFIRMED');
    expect(readCustomerInvoiceState('SENT')).toBe('SENT');
    expect(readCustomerInvoiceState('NGACO')).toBe('DRAFT');
    expect(readCustomerInvoiceState(undefined)).toBe('DRAFT');
  });

  it('readCustomerInvoiceRow/Line: field lengkap + fallback aman', () => {
    expect(readCustomerInvoiceRow(ROW)).toEqual(ROW);
    expect(readCustomerInvoiceRow({ id: '7' })).toBeNull();

    const line = readCustomerInvoiceLineRow(LINE);
    expect(line?.tax_ids).toEqual([19]);
    expect(line?.order_line_id).toBe(5);

    const sparse = readCustomerInvoiceLineRow({ id: 2, tax_ids: 'bukan-array' });
    expect(sparse?.tax_ids).toEqual([]);
    expect(sparse?.qty).toBe('');
  });

  it('readCustomerInvoicePage/Detail/Saved', () => {
    expect(readCustomerInvoicePage({ rows: [ROW], total_count: 1, has_more: false })).toEqual({
      rows: [ROW],
      total_count: 1,
      has_more: false,
      next_cursor: null,
    });
    expect(readCustomerInvoicePage(null)).toBeNull();

    const detail = readCustomerInvoiceDetail(DETAIL);
    expect(detail?.lines).toHaveLength(1);
    expect(detail?.allowed_actions).toEqual(['CONFIRMED', 'CANCELLED']);
    expect(detail?.odoo_sync_status).toBe('PENDING');

    const saved = readCustomerInvoiceSaved(SAVED);
    expect(saved?.sync_record_id).toBe(3);
    expect(saved?.queued).toBe(true);
    expect(saved?.duplicate_warning).toBeNull();
  });

  it('toCustomerInvoiceBody: trim teks, `due_date` kosong → null', () => {
    expect(toCustomerInvoiceBody(INPUT)).toEqual({
      order_id: 3,
      invoice_date: '2026-10-12',
      due_date: '2026-11-12',
      notes: 'DP 50%',
      lines: [{ product_id: 34, qty: 5, price_unit: 4000, tax_ids: [19], order_line_id: 5 }],
    });

    expect(
      toCustomerInvoiceBody({ order_id: 3, invoice_date: '2026-10-12', due_date: '' }),
    ).toEqual({
      order_id: 3,
      invoice_date: '2026-10-12',
    });
  });
});

describe('H3.1 — daftar, detail, tulis & aksi', () => {
  it('fetchCustomerInvoices memanggil path + filter, error backend dilempar', async () => {
    const { client, requests } = stubClient({ rows: [ROW], total_count: 1, has_more: false });

    const page = await fetchCustomerInvoices(client, { state: 'DRAFT', limit: 50 });

    expect(requests).toEqual([
      { path: '/finance/customer-invoices/?state=DRAFT&limit=50', method: 'GET' },
    ]);
    expect(page.total_count).toBe(1);

    await expect(fetchCustomerInvoices(failingClient(403, 'HTTP 403'))).rejects.toThrow(/403/);
  });

  it('fetchCustomerInvoice: detail + pesan backend saat 404', async () => {
    const { client, requests } = stubClient(DETAIL);

    const detail = await fetchCustomerInvoice(client, 7);

    expect(requests).toEqual([{ path: '/finance/customer-invoices/7/', method: 'GET' }]);
    expect(detail.lines).toHaveLength(1);

    await expect(
      fetchCustomerInvoice(failingClient(404, 'Customer Invoice tidak ditemukan.'), 7),
    ).rejects.toThrow(/tidak ditemukan/);
  });

  it('createCustomerInvoice: POST body + saved; 400 (harga 0) dilempar', async () => {
    const { client, requests } = stubClient(SAVED);

    const saved = await createCustomerInvoice(client, INPUT);

    expect(requests).toEqual([
      { path: '/finance/customer-invoices/', method: 'POST', body: toCustomerInvoiceBody(INPUT) },
    ]);
    expect(saved.code).toBe('INV-2026-0001');
    expect(saved.queued).toBe(true);

    await expect(
      createCustomerInvoice(
        failingClient(
          400,
          'Harga baris 1 harus > 0 sebelum CONFIRMED (invoice harga 0 ditolak; §5).',
        ),
        INPUT,
      ),
    ).rejects.toThrow(/harus > 0/);
  });

  it('updateCustomerInvoice: PUT ke `/…/<id>/`', async () => {
    const { client, requests } = stubClient(SAVED);

    await updateCustomerInvoice(client, 7, INPUT);

    expect(requests).toEqual([
      { path: '/finance/customer-invoices/7/', method: 'PUT', body: toCustomerInvoiceBody(INPUT) },
    ]);
  });

  it('deleteCustomerInvoice: DELETE (DRAFT-only di backend)', async () => {
    const { client, requests } = stubClient({ id: 7, deleted: true });

    await deleteCustomerInvoice(client, 7);

    expect(requests).toEqual([
      { path: '/finance/customer-invoices/7/', method: 'DELETE', body: undefined },
    ]);

    await expect(
      deleteCustomerInvoice(failingClient(400, 'hapus hanya boleh saat DRAFT'), 7),
    ).rejects.toThrow(/DRAFT/);
  });

  it('actCustomerInvoice: POST aksi + parse saved; bentuk rusak → melempar', async () => {
    const { client, requests } = stubClient({ ...SAVED, state: 'CONFIRMED' });

    const saved = await actCustomerInvoice(client, 7, 'confirm');

    expect(requests).toEqual([
      { path: '/finance/customer-invoices/7/confirm/', method: 'POST', body: {} },
    ]);
    expect(saved.state).toBe('CONFIRMED');

    const broken = stubClient({ ok: true });

    await expect(actCustomerInvoice(broken.client, 7, 'done')).rejects.toThrow(/tidak dikenali/);
  });
});

