import { describe, expect, it } from 'vitest';
import {
  actVendorBill,
  buildVendorBillsPath,
  createVendorBill,
  deleteVendorBill,
  fetchVendorBill,
  fetchVendorBills,
  readVendorBillDetail,
  readVendorBillLineRow,
  readVendorBillPage,
  readVendorBillRow,
  readVendorBillSaved,
  readVendorBillState,
  toVendorBillBody,
  updateVendorBill,
  VENDOR_BILLS_PATH,
  vendorBillActionPath,
} from '@/api/vendorBills';
import { MODE } from '@/api/_adapter';
import type { ApiClient, ApiResponse } from '@/integrations/api-client';
import type { VendorBillInput, VendorBillRow } from '@/types/vendor-bill';

/**
 * H3.2 — adapter Vendor Bill MES (`/api/v1/finance/vendor-bills/`).
 *
 * Bentuk = PERSIS `garment/services/vendor_bill_services.py`:
 * `{id, code, purchase_order_id, purchase_order_no, vendor_id, vendor_name,
 * vendor_code, ref, invoice_date, due_date, state, notes, lines_count,
 * amount_total, odoo_id, …}`; detail menambah `{lines[], odoo_sync_status,
 * odoo_sync_error, allowed_actions}`; POST/PUT/aksi menambah
 * `{sync_record_id, task_id, queued}` (+ `duplicate_warning` saat create).
 *
 * ⚠️ `purchase_order_id` **nullable** (bill tanpa PO, mis. biaya jasa) dan `ref`
 * best-effort (boleh kosong). I6 (`MaterialReadiness.vendor_bill_*`) tidak diuji di
 * sini karena bukan bagian adapter ini.
 */

const ROW: VendorBillRow = {
  id: 22,
  code: 'VB-2026-0001',
  purchase_order_id: 5,
  purchase_order_no: 'PO-2026-9001',
  vendor_id: 14,
  vendor_name: 'PT Vendor Bill',
  vendor_code: 'SUP-VB',
  ref: 'INV-VENDOR-001',
  invoice_date: '2026-10-13',
  due_date: null,
  state: 'DRAFT',
  notes: '',
  lines_count: 1,
  amount_total: '15000.00',
  odoo_id: null,
  created_at: '2026-10-13T00:00:00+00:00',
  updated_at: '2026-10-13T00:00:00+00:00',
};

const LINE = {
  id: 31,
  po_line_id: 9,
  product_id: 34,
  product_code: 'BENANG-VB',
  product_name: 'Benang Vendor',
  qty: '10.00',
  price_unit: '1500.00',
  subtotal: '15000.00',
  tax_ids: [20],
  tax_odoo_ids: [20],
  line_total: '15000.00',
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
  sync_record_id: 39,
  task_id: 'task-vb-1',
  queued: true,
  duplicate_warning: null,
};

const INPUT: VendorBillInput = {
  vendor_id: 14,
  purchase_order_id: 5,
  ref: ' INV-VENDOR-001 ',
  invoice_date: '2026-10-13',
  due_date: '2026-11-13',
  notes: ' termin 1 ',
  lines: [{ product_id: 34, qty: 10, price_unit: 1500, tax_ids: [20], po_line_id: 9 }],
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

describe('H3.2 — MODE & path vendor bill', () => {
  it('MODE.vendorBills = real; MODE.purchaseOrders (B10) tetap real', () => {
    expect(MODE['vendorBills']).toBe('real');
    expect(MODE['purchaseOrders']).toBe('real');
    expect(VENDOR_BILLS_PATH).toBe('/finance/vendor-bills/');
  });

  it('buildVendorBillsPath: default tanpa query, param terisi saja', () => {
    expect(buildVendorBillsPath()).toBe('/finance/vendor-bills/');
    expect(buildVendorBillsPath({ search: 'vb', state: 'DRAFT' })).toBe(
      '/finance/vendor-bills/?search=vb&state=DRAFT',
    );
    expect(buildVendorBillsPath({ vendor_id: 14, purchase_order_id: 5 })).toBe(
      '/finance/vendor-bills/?vendor_id=14&purchase_order_id=5',
    );
    expect(buildVendorBillsPath({ limit: 200, cursor: 20 })).toBe(
      '/finance/vendor-bills/?limit=200&cursor=20',
    );
    expect(buildVendorBillsPath({ state: null, cursor: null })).toBe('/finance/vendor-bills/');
  });

  it('vendorBillActionPath: confirm/done/cancel', () => {
    expect(vendorBillActionPath(22, 'confirm')).toBe('/finance/vendor-bills/22/confirm/');
    expect(vendorBillActionPath(22, 'done')).toBe('/finance/vendor-bills/22/done/');
    expect(vendorBillActionPath(22, 'cancel')).toBe('/finance/vendor-bills/22/cancel/');
  });
});

describe('H3.2 — parsing baris, detail & payload', () => {
  it('readVendorBillState: nilai sah saja; lain → DRAFT', () => {
    expect(readVendorBillState('CONFIRMED')).toBe('CONFIRMED');
    expect(readVendorBillState('SENT')).toBe('SENT');
    expect(readVendorBillState('DONE')).toBe('DONE');
    expect(readVendorBillState('NGACO')).toBe('DRAFT');
    expect(readVendorBillState(undefined)).toBe('DRAFT');
  });

  it('readVendorBillRow/Line: field lengkap + fallback aman', () => {
    expect(readVendorBillRow(ROW)).toEqual(ROW);
    expect(readVendorBillRow({ id: '22' })).toBeNull();

    // Bill TANPA PO (nullable) tetap sah.
    const tanpaPo = readVendorBillRow({ id: 23, purchase_order_id: null, ref: '' });
    expect(tanpaPo?.purchase_order_id).toBeNull();
    expect(tanpaPo?.purchase_order_no).toBeNull();
    expect(tanpaPo?.ref).toBe('');

    const line = readVendorBillLineRow(LINE);
    expect(line?.tax_ids).toEqual([20]);
    expect(line?.tax_odoo_ids).toEqual([20]);
    expect(line?.po_line_id).toBe(9);

    const sparse = readVendorBillLineRow({ id: 2, product_id: 5, tax_ids: 'bukan-array' });
    expect(sparse?.tax_ids).toEqual([]);
    expect(sparse?.qty).toBe('');
  });

  it('readVendorBillPage/Detail/Saved', () => {
    expect(readVendorBillPage({ rows: [ROW], total_count: 1, has_more: false })).toEqual({
      rows: [ROW],
      total_count: 1,
      has_more: false,
      next_cursor: null,
    });
    expect(readVendorBillPage(null)).toBeNull();

    const detail = readVendorBillDetail(DETAIL);
    expect(detail?.lines).toHaveLength(1);
    expect(detail?.allowed_actions).toEqual(['CONFIRMED', 'CANCELLED']);
    expect(detail?.odoo_sync_status).toBe('PENDING');

    const saved = readVendorBillSaved(SAVED);
    expect(saved?.sync_record_id).toBe(39);
    expect(saved?.queued).toBe(true);
    expect(saved?.duplicate_warning).toBeNull();

    const duplicate = readVendorBillSaved({ ...SAVED, duplicate_warning: 'PO sudah punya bill' });
    expect(duplicate?.duplicate_warning).toBe('PO sudah punya bill');
  });

  it('toVendorBillBody: trim teks, `due_date` kosong → null, PO dilewati bila kosong', () => {
    expect(toVendorBillBody(INPUT)).toEqual({
      vendor_id: 14,
      purchase_order_id: 5,
      ref: 'INV-VENDOR-001',
      invoice_date: '2026-10-13',
      due_date: '2026-11-13',
      notes: 'termin 1',
      lines: [
        { product_id: 34, qty: 10, price_unit: 1500, tax_ids: [20], po_line_id: 9 },
      ],
    });

    expect(
      toVendorBillBody({
        vendor_id: 14,
        purchase_order_id: null,
        invoice_date: '2026-10-13',
        due_date: '',
      }),
    ).toEqual({ vendor_id: 14, invoice_date: '2026-10-13' });
  });
});

describe('H3.2 — daftar, detail, tulis & aksi', () => {
  it('fetchVendorBills memanggil path + filter, error backend dilempar', async () => {
    const { client, requests } = stubClient({ rows: [ROW], total_count: 1, has_more: false });

    const page = await fetchVendorBills(client, { state: 'DRAFT', limit: 50 });

    expect(requests).toEqual([{ path: '/finance/vendor-bills/?state=DRAFT&limit=50', method: 'GET' }]);
    expect(page.total_count).toBe(1);

    await expect(fetchVendorBills(failingClient(403, 'HTTP 403'))).rejects.toThrow(/403/);
  });

  it('fetchVendorBill: detail + pesan backend saat 404', async () => {
    const { client, requests } = stubClient(DETAIL);

    const detail = await fetchVendorBill(client, 22);

    expect(requests).toEqual([{ path: '/finance/vendor-bills/22/', method: 'GET' }]);
    expect(detail.lines).toHaveLength(1);

    await expect(
      fetchVendorBill(failingClient(404, 'Vendor Bill tidak ditemukan.'), 22),
    ).rejects.toThrow(/tidak ditemukan/);
  });

  it('createVendorBill: POST body + saved (duplicate_warning tidak dilempar)', async () => {
    const { client, requests } = stubClient({
      ...SAVED,
      duplicate_warning: 'Purchase Order PO-2026-9001 sudah punya 1 bill aktif.',
    });

    const saved = await createVendorBill(client, INPUT);

    expect(requests).toEqual([
      { path: '/finance/vendor-bills/', method: 'POST', body: toVendorBillBody(INPUT) },
    ]);
    expect(saved.code).toBe('VB-2026-0001');
    expect(saved.queued).toBe(true);
    expect(saved.duplicate_warning).toContain('bill aktif');

    await expect(
      createVendorBill(
        failingClient(400, "Field 'vendor_id' wajib diisi."),
        { ...INPUT, vendor_id: 0 },
      ),
    ).rejects.toThrow(/vendor_id/);
  });

  it('updateVendorBill: PUT ke `/…/<id>/`', async () => {
    const { client, requests } = stubClient(SAVED);

    await updateVendorBill(client, 22, INPUT);

    expect(requests).toEqual([
      { path: '/finance/vendor-bills/22/', method: 'PUT', body: toVendorBillBody(INPUT) },
    ]);
  });

  it('deleteVendorBill: DELETE (DRAFT-only di backend)', async () => {
    const { client, requests } = stubClient({ id: 22, deleted: true });

    await deleteVendorBill(client, 22);

    expect(requests).toEqual([
      { path: '/finance/vendor-bills/22/', method: 'DELETE', body: undefined },
    ]);

    await expect(
      deleteVendorBill(failingClient(400, 'hapus hanya boleh saat DRAFT'), 22),
    ).rejects.toThrow(/DRAFT/);
  });

  it('actVendorBill: POST aksi + parse saved; bentuk rusak → melempar', async () => {
    const { client, requests } = stubClient({ ...SAVED, state: 'CONFIRMED' });

    const saved = await actVendorBill(client, 22, 'confirm');

    expect(requests).toEqual([
      { path: '/finance/vendor-bills/22/confirm/', method: 'POST', body: {} },
    ]);
    expect(saved.state).toBe('CONFIRMED');

    const broken = stubClient({ ok: true });

    await expect(actVendorBill(broken.client, 22, 'cancel')).rejects.toThrow(/tidak dikenali/);
  });
});


