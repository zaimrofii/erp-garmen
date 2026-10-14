import { describe, expect, it } from 'vitest';
import {
  actPayment,
  buildPaymentsPath,
  createPayment,
  deletePayment,
  fetchPayment,
  fetchPayments,
  paymentActionPath,
  PAYMENTS_PATH,
  readPaymentDetail,
  readPaymentMethod,
  readPaymentPage,
  readPaymentRow,
  readPaymentSaved,
  readPaymentSourceType,
  readPaymentState,
  readPaymentType,
  toPaymentBody,
  updatePayment,
} from '@/api/payments';
import { MODE } from '@/api/_adapter';
import type { ApiClient, ApiResponse } from '@/integrations/api-client';
import type { PaymentInput, PaymentRow } from '@/types/payment';

/**
 * H3.3 — adapter Payment MES (`/api/v1/finance/payments/`).
 *
 * Bentuk = PERSIS `garment/services/payment_services.py`:
 * `{id, code, payment_type, partner_id, partner_name, partner_code,
 * customer_invoice_id, customer_invoice_code, vendor_bill_id, vendor_bill_code,
 * source_type, source_label, amount, currency, payment_date, payment_method,
 * reference, memo, state, odoo_id, …}`; detail menambah `{odoo_sync_status,
 * odoo_sync_error, allowed_actions, source_amount_total, source_remaining_amount}`;
 * POST/PUT/aksi menambah `{sync_record_id, task_id, queued}`.
 *
 * Tidak ada field reconcile (rekonsiliasi di Odoo, bukan MES).
 */

const ROW: PaymentRow = {
  id: 22,
  code: 'PAY-2026-0001',
  payment_type: 'INBOUND',
  partner_id: 10,
  partner_name: 'PT Buyer Payment',
  partner_code: 'CUST-PAY',
  customer_invoice_id: 7,
  customer_invoice_code: 'INV-2026-0001',
  vendor_bill_id: null,
  vendor_bill_code: null,
  source_type: 'CUSTOMER_INVOICE',
  source_label: 'Customer Invoice INV-2026-0001',
  amount: '20000.00',
  currency: 'IDR',
  payment_date: '2026-10-13',
  payment_method: 'manual',
  reference: 'TRF-001',
  memo: 'termin 1',
  state: 'DRAFT',
  odoo_id: null,
  created_at: '2026-10-13T00:00:00+00:00',
  updated_at: '2026-10-13T00:00:00+00:00',
};

const DETAIL = {
  ...ROW,
  odoo_sync_status: 'PENDING',
  odoo_sync_error: null,
  allowed_actions: ['CONFIRMED', 'CANCELLED'],
  source_amount_total: '20000.00',
  source_remaining_amount: '0.00',
};

const SAVED = {
  ...DETAIL,
  sync_record_id: 51,
  task_id: 'task-pay-1',
  queued: true,
};

const INPUT: PaymentInput = {
  payment_type: 'INBOUND',
  customer_invoice_id: 7,
  amount: 20000,
  currency: 'idr',
  payment_date: '2026-10-13',
  payment_method: 'bank',
  reference: ' TRF-001 ',
  memo: ' termin 1 ',
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

describe('H3.3 — MODE & path payment', () => {
  it('MODE.payments = real; H3.1/H3.2 tetap real', () => {
    expect(MODE['payments']).toBe('real');
    expect(MODE['customerInvoices']).toBe('real');
    expect(MODE['vendorBills']).toBe('real');
    expect(PAYMENTS_PATH).toBe('/finance/payments/');
  });

  it('buildPaymentsPath: default tanpa query, param terisi saja', () => {
    expect(buildPaymentsPath()).toBe('/finance/payments/');
    expect(buildPaymentsPath({ search: 'pay', state: 'DRAFT', payment_type: 'INBOUND' })).toBe(
      '/finance/payments/?search=pay&state=DRAFT&payment_type=INBOUND',
    );
    expect(buildPaymentsPath({ partner_id: 10, customer_invoice_id: 7 })).toBe(
      '/finance/payments/?partner_id=10&customer_invoice_id=7',
    );
    expect(buildPaymentsPath({ vendor_bill_id: 5, limit: 200, cursor: 20 })).toBe(
      '/finance/payments/?vendor_bill_id=5&limit=200&cursor=20',
    );
    expect(buildPaymentsPath({ state: null, payment_type: null })).toBe('/finance/payments/');
  });

  it('paymentActionPath: confirm/done/cancel', () => {
    expect(paymentActionPath(22, 'confirm')).toBe('/finance/payments/22/confirm/');
    expect(paymentActionPath(22, 'done')).toBe('/finance/payments/22/done/');
    expect(paymentActionPath(22, 'cancel')).toBe('/finance/payments/22/cancel/');
  });
});

describe('H3.3 — parsing baris, detail & payload', () => {
  it('readPaymentState/Type/Method/SourceType: nilai sah saja; lain → default', () => {
    expect(readPaymentState('SENT')).toBe('SENT');
    expect(readPaymentState('NGACO')).toBe('DRAFT');

    expect(readPaymentType('OUTBOUND')).toBe('OUTBOUND');
    expect(readPaymentType('inbound')).toBe('INBOUND');

    expect(readPaymentMethod('bank')).toBe('bank');
    expect(readPaymentMethod('giro')).toBe('manual');

    expect(readPaymentSourceType('VENDOR_BILL')).toBe('VENDOR_BILL');
    expect(readPaymentSourceType('BOGUS')).toBe('UNKNOWN');
  });

  it('readPaymentRow: field lengkap + fallback aman (sumber vendor bill)', () => {
    expect(readPaymentRow(ROW)).toEqual(ROW);
    expect(readPaymentRow({ id: '22' })).toBeNull();

    const outbound = readPaymentRow({
      id: 23,
      payment_type: 'OUTBOUND',
      vendor_bill_id: 9,
      source_type: 'VENDOR_BILL',
      amount: '15000.00',
    });
    expect(outbound?.payment_type).toBe('OUTBOUND');
    expect(outbound?.vendor_bill_id).toBe(9);
    expect(outbound?.customer_invoice_id).toBeNull();
    expect(outbound?.currency).toBe('');
  });

  it('readPaymentPage/Detail/Saved', () => {
    expect(readPaymentPage({ rows: [ROW], total_count: 1, has_more: false })).toEqual({
      rows: [ROW],
      total_count: 1,
      has_more: false,
      next_cursor: null,
    });
    expect(readPaymentPage(null)).toBeNull();

    const detail = readPaymentDetail(DETAIL);
    expect(detail?.allowed_actions).toEqual(['CONFIRMED', 'CANCELLED']);
    expect(detail?.source_amount_total).toBe('20000.00');
    expect(detail?.source_remaining_amount).toBe('0.00');
    expect(detail?.odoo_sync_status).toBe('PENDING');

    const saved = readPaymentSaved(SAVED);
    expect(saved?.sync_record_id).toBe(51);
    expect(saved?.queued).toBe(true);
  });

  it('toPaymentBody: sumber sesuai tipe, trim teks, currency uppercase', () => {
    expect(toPaymentBody(INPUT)).toEqual({
      payment_type: 'INBOUND',
      customer_invoice_id: 7,
      amount: 20000,
      currency: 'IDR',
      payment_date: '2026-10-13',
      payment_method: 'bank',
      reference: 'TRF-001',
      memo: 'termin 1',
    });

    const outbound = toPaymentBody({
      payment_type: 'OUTBOUND',
      customer_invoice_id: 7,
      vendor_bill_id: 9,
      amount: 15000,
      payment_date: '2026-10-13',
    });
    expect(outbound['vendor_bill_id']).toBe(9);
    expect(outbound['customer_invoice_id']).toBeUndefined();
  });
});

describe('H3.3 — daftar, detail, tulis & aksi', () => {
  it('fetchPayments memanggil path + filter, error backend dilempar', async () => {
    const { client, requests } = stubClient({ rows: [ROW], total_count: 1, has_more: false });

    const page = await fetchPayments(client, { payment_type: 'INBOUND', limit: 50 });

    expect(requests).toEqual([
      { path: '/finance/payments/?payment_type=INBOUND&limit=50', method: 'GET' },
    ]);
    expect(page.total_count).toBe(1);

    await expect(fetchPayments(failingClient(403, 'HTTP 403'))).rejects.toThrow(/403/);
  });

  it('fetchPayment: detail + pesan backend saat 404', async () => {
    const { client, requests } = stubClient(DETAIL);

    const detail = await fetchPayment(client, 22);

    expect(requests).toEqual([{ path: '/finance/payments/22/', method: 'GET' }]);
    expect(detail.source_label).toBe('Customer Invoice INV-2026-0001');

    await expect(fetchPayment(failingClient(404, 'Payment tidak ditemukan.'), 22)).rejects.toThrow(
      /tidak ditemukan/,
    );
  });

  it('createPayment: POST body + guard overpay 400 dilempar', async () => {
    const { client, requests } = stubClient(SAVED);

    const saved = await createPayment(client, INPUT);

    expect(requests).toEqual([
      { path: '/finance/payments/', method: 'POST', body: toPaymentBody(INPUT) },
    ]);
    expect(saved.code).toBe('PAY-2026-0001');
    expect(saved.queued).toBe(true);

    await expect(
      createPayment(failingClient(400, 'Jumlah bayar 20000.01 melebihi sisa'), INPUT),
    ).rejects.toThrow(/melebihi sisa/);
  });

  it('updatePayment: PUT ke `/…/<id>/`', async () => {
    const { client, requests } = stubClient(SAVED);

    await updatePayment(client, 22, INPUT);

    expect(requests).toEqual([
      { path: '/finance/payments/22/', method: 'PUT', body: toPaymentBody(INPUT) },
    ]);
  });

  it('deletePayment: DELETE (DRAFT-only di backend)', async () => {
    const { client, requests } = stubClient({ id: 22, deleted: true });

    await deletePayment(client, 22);

    expect(requests).toEqual([
      { path: '/finance/payments/22/', method: 'DELETE', body: undefined },
    ]);

    await expect(
      deletePayment(failingClient(400, 'hapus hanya boleh saat DRAFT'), 22),
    ).rejects.toThrow(/DRAFT/);
  });

  it('actPayment: POST aksi + parse saved; bentuk rusak → melempar', async () => {
    const { client, requests } = stubClient({ ...SAVED, state: 'CONFIRMED' });

    const saved = await actPayment(client, 22, 'confirm');

    expect(requests).toEqual([{ path: '/finance/payments/22/confirm/', method: 'POST', body: {} }]);
    expect(saved.state).toBe('CONFIRMED');

    const broken = stubClient({ ok: true });

    await expect(actPayment(broken.client, 22, 'cancel')).rejects.toThrow(/tidak dikenali/);
  });
});


