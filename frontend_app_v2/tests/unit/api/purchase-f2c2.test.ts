import { describe, expect, it } from 'vitest';
import {
  buildPurchaseOrdersPath,
  fetchPurchaseOrders,
  PURCHASE_ORDERS_PATH,
  readPurchaseOrderRow,
} from '@/api/purchase';
import { buildPurchaseVendorsPath, fetchVendors, PURCHASE_VENDORS_PATH } from '@/api/purchase';
import {
  fetchPurchaseReporting,
  PURCHASE_REPORTING_PATH,
  readPurchaseReporting,
} from '@/api/purchase';
import { MODE } from '@/api/_adapter';
import type { ApiClient, ApiResponse } from '@/integrations/api-client';

/** F2C.2 — purchaseOrders / purchaseVendors / purchaseReporting REAL. */

const ORDER_BODY = {
  rows: [
    {
      id: 7,
      name: 'PO0007',
      partner_name: 'PT Kain',
      state: 'purchase',
      date_order: '2026-10-01 08:00:00',
      date_planned: null,
      amount_total: 1500000,
      vendor_code: 'V-01',
      lines: [{ product_code: 'TS-001', description: 'Kaos', qty: 10, price_unit: 150000, subtotal: 1500000 }],
    },
  ],
  total_count: 1,
  has_more: false,
  next_cursor: null,
};

const VENDOR_BODY = {
  rows: [{ id: 3, name: 'PT Kain', odoo_id: 12, email: null, phone: null, city: null }],
  total_count: 1,
  has_more: false,
  next_cursor: null,
};

const REPORT_BODY = {
  total_po: 4,
  total_amount: 9000000,
  by_state: { purchase: 3, done: 1 },
  top_vendors: [
    {
      partner_name: 'PT Kain',
      total_amount: 5000000,
      po_count: 2,
      vendor_name: 'PT Kain',
      vendor_code: 'V-01',
      amount_total: 5000000,
    },
  ],
  monthly_series: [{ month: '2026-10', po_count: 2, amount_total: 5000000, vendor_bill_count: 1 }],
  vendor_bills: { total: 1, total_amount: 4000000, by_state: { posted: 1 } },
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

describe('F2C.2 — purchase (3 key real)', () => {
  it('MODE purchaseOrders/purchaseVendors/purchaseReporting = real', () => {
    expect(MODE['purchaseOrders']).toBe('real');
    expect(MODE['purchaseVendors']).toBe('real');
    expect(MODE['purchaseReporting']).toBe('real');
  });

  it('orders: path + lines[] terbaca', async () => {
    expect(PURCHASE_ORDERS_PATH).toBe('/purchase/orders/');
    expect(buildPurchaseOrdersPath({ state: 'purchase' })).toBe('/purchase/orders/?state=purchase');

    const { client, paths } = stubClient(ORDER_BODY);
    const rows = await fetchPurchaseOrders(client);

    expect(paths).toEqual(['/purchase/orders/']);
    expect(rows[0]?.lines).toHaveLength(1);
    expect(rows[0]?.lines[0]?.subtotal).toBe(1500000);
    expect(readPurchaseOrderRow({ partner_name: 'x' })?.vendor_code).toBeNull();
  });

  it('vendors: email/phone/city selalu null', async () => {
    expect(PURCHASE_VENDORS_PATH).toBe('/purchase/vendors/');
    expect(buildPurchaseVendorsPath({ q: 'kain' })).toBe('/purchase/vendors/?q=kain');

    const { client } = stubClient(VENDOR_BODY);
    const rows = await fetchVendors(client);

    expect(rows[0]?.email).toBeNull();
    expect(rows[0]?.phone).toBeNull();
    expect(rows[0]?.city).toBeNull();
  });

  it('reporting: monthly_series + top_vendors terbaca', async () => {
    expect(PURCHASE_REPORTING_PATH).toBe('/purchase/reporting/');

    const parsed = readPurchaseReporting(REPORT_BODY);

    expect(parsed?.total_po).toBe(4);
    expect(parsed?.top_vendors[0]?.vendor_code).toBe('V-01');
    expect(parsed?.monthly_series).toHaveLength(1);
    expect(parsed?.vendor_bills.by_state['posted']).toBe(1);

    const { client } = stubClient(REPORT_BODY);

    await expect(fetchPurchaseReporting(client)).resolves.toBeDefined();
  });
});
