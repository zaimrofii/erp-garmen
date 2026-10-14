import { describe, expect, it } from 'vitest';
import {
  adjustmentCommitPath,
  adjustmentDetailPath,
  buildAdjustmentsPath,
  buildStockQtyPath,
  commitAdjustment,
  createAdjustment,
  fetchAdjustment,
  fetchAdjustments,
  fetchStockQty,
  INVENTORY_ADJUSTMENTS_PATH,
  INVENTORY_ADJUST_PATH,
  INVENTORY_STOCK_QTY_PATH,
  readAdjustmentCommitResult,
  readAdjustmentCreated,
  readAdjustmentDetail,
  readAdjustmentRow,
  readStockQty,
} from '@/api/inventoryAdjustments';
import { MODE, isReal } from '@/api/_adapter';
import type { ApiClient, ApiResponse } from '@/integrations/api-client';

/**
 * H2.5 — adapter Inventory Adjustment (`/api/v1/inventory/…`).
 *
 * Bentuk = PERSIS `apps_industry/garment/services/inventory_adjustment_services.py`
 * (`adjustment_row`/`adjustment_detail_row`): decimal sebagai **string**, snapshot stok
 * Odoo boleh `null`, detail menambah blok `sync`, commit menambah `ledger_id`/`task_id`/
 * `queued`, dan `stock-qty` = pembacaan on-demand (read-only).
 */

interface RecordedRequest {
  path: string;
  method: string;
  body?: unknown;
}

const ROW = {
  id: 3,
  code: 'ADJ-2026-0001',
  product_id: 89,
  product_code: 'KAIN-COTTON',
  product_name: 'Kain Cotton',
  location_id: 8,
  location_code: 'WH/STOK',
  location_name: 'Stok',
  location_usage: 'internal',
  qty_delta: '5.00',
  qty_before: '60.00',
  qty_after: null,
  reason: 'Hasil opname',
  state: 'DRAFT',
  odoo_move_id: null,
  odoo_reference: '',
  last_error: '',
  created_by: 'sim-h25',
  created_at: '2026-10-12T03:00:00+00:00',
  updated_at: null,
};

const DETAIL = { ...ROW, sync: { record_id: null, status: null, erp_id: null, attempts: 0 } };

function stubClient(data: unknown): { client: ApiClient; requests: RecordedRequest[] } {
  const requests: RecordedRequest[] = [];
  const reply = <T,>(): ApiResponse<T> => ({ ok: true, status: 200, data: data as T });

  const client = {
    get: async <T,>(path: string): Promise<ApiResponse<T>> => {
      requests.push({ path, method: 'GET' });

      return reply<T>();
    },
    post: async <T,>(path: string, body: unknown, options?: unknown): Promise<ApiResponse<T>> => {
      requests.push({ path, method: 'POST', body, options });

      return reply<T>();
    },
    request: async <T,>(
      path: string,
      options?: Record<string, unknown>,
    ): Promise<ApiResponse<T>> => {
      requests.push({ path, method: String(options?.['method'] ?? 'GET'), options });

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
    get: async <T,>() => response<T>(),
    post: async <T,>() => response<T>(),
    request: async <T,>() => response<T>(),
  } as unknown as ApiClient;
}

describe('H2.5 — path & reader PURE Inventory Adjustment', () => {
  it('mode adapter = real + path backend sesuai config/urls.py', () => {
    expect(MODE['inventoryAdjustments']).toBe('real');
    expect(isReal('inventoryAdjustments')).toBe(true);
    expect(INVENTORY_ADJUST_PATH).toBe('/inventory/adjust/');
    expect(INVENTORY_ADJUSTMENTS_PATH).toBe('/inventory/adjustments/');
    expect(INVENTORY_STOCK_QTY_PATH).toBe('/inventory/stock-qty/');
    expect(adjustmentDetailPath(3)).toBe('/inventory/adjustments/3/');
    expect(adjustmentCommitPath(3)).toBe('/inventory/adjustments/3/commit/');
  });

  it('buildAdjustmentsPath hanya mengirim param terisi', () => {
    expect(buildAdjustmentsPath()).toBe('/inventory/adjustments/');
    expect(buildAdjustmentsPath({ search: 'ADJ', state: 'DRAFT', limit: 20, offset: 0 })).toBe(
      '/inventory/adjustments/?search=ADJ&state=DRAFT&limit=20&offset=0',
    );
    expect(buildAdjustmentsPath({ product_id: 89, location_id: 8 })).toBe(
      '/inventory/adjustments/?product_id=89&location_id=8',
    );
    expect(buildAdjustmentsPath({ search: null, state: null })).toBe('/inventory/adjustments/');
  });

  it('buildStockQtyPath menyusun query product & location', () => {
    expect(buildStockQtyPath(89, 8)).toBe('/inventory/stock-qty/?product_id=89&location_id=8');
  });

  it('readAdjustmentRow mempertahankan decimal string & snapshot null', () => {
    const row = readAdjustmentRow(ROW);

    expect(row).not.toBeNull();
    expect(row?.qty_delta).toBe('5.00');
    expect(row?.qty_before).toBe('60.00');
    expect(row?.qty_after).toBeNull();
    expect(row?.odoo_move_id).toBeNull();
    expect(row?.location_usage).toBe('internal');
  });

  it('readAdjustmentRow menolak baris tanpa id / bukan objek', () => {
    expect(readAdjustmentRow({ code: 'ADJ' })).toBeNull();
    expect(readAdjustmentRow(null)).toBeNull();
    expect(readAdjustmentRow([])).toBeNull();
  });

  it('readAdjustmentDetail menambahkan blok sync (default null)', () => {
    expect(readAdjustmentDetail(ROW)?.sync).toEqual({
      record_id: null,
      status: null,
      erp_id: null,
      attempts: 0,
    });

    const withSync = readAdjustmentDetail({
      ...ROW,
      sync: { record_id: 11, status: 'SENT', erp_id: '231', attempts: 1 },
    });
    expect(withSync?.sync).toEqual({ record_id: 11, status: 'SENT', erp_id: '231', attempts: 1 });
  });

  it('readAdjustmentCreated membaca blok commit saat ?commit=true', () => {
    const plain = readAdjustmentCreated(DETAIL);
    expect(plain?.commit).toBeUndefined();

    const committed = readAdjustmentCreated({
      ...DETAIL,
      state: 'COMMITTED',
      commit: { ok: true, ledger_id: 5, task_id: 'task-1', queued: true },
    });
    expect(committed?.state).toBe('COMMITTED');
    expect(committed?.commit).toEqual({
      ok: true,
      detail: undefined,
      ledger_id: 5,
      task_id: 'task-1',
      queued: true,
    });
  });

  it('readAdjustmentCreated membaca commit gagal (tetap DRAFT + detail)', () => {
    const failed = readAdjustmentCreated({
      ...DETAIL,
      commit: { ok: false, detail: 'Product belum punya odoo_id.' },
    });

    expect(failed?.commit?.ok).toBe(false);
    expect(failed?.commit?.detail).toBe('Product belum punya odoo_id.');
    expect(failed?.state).toBe('DRAFT');
  });

  it('readAdjustmentCommitResult membaca ledger/task/queued', () => {
    const result = readAdjustmentCommitResult({
      ...DETAIL,
      state: 'COMMITTED',
      ledger_id: 7,
      task_id: 'task-9',
      queued: true,
    });

    expect(result?.ledger_id).toBe(7);
    expect(result?.task_id).toBe('task-9');
    expect(result?.queued).toBe(true);
  });

  it('readStockQty membaca qty string & null (tidak terbaca)', () => {
    expect(
      readStockQty({
        product_id: 89,
        product_code: 'KAIN',
        product_odoo_id: 89,
        location_id: 8,
        location_code: 'WH/STOK',
        location_odoo_id: 8,
        qty: '60.00',
        source: 'odoo',
        stock_owner: 'odoo',
      })?.qty,
    ).toBe('60.00');

    expect(
      readStockQty({
        product_id: 89,
        location_id: 8,
        qty: null,
        product_code: '',
        location_code: '',
        product_odoo_id: null,
        location_odoo_id: null,
        source: 'odoo',
        stock_owner: 'odoo',
      })?.qty,
    ).toBeNull();

    expect(readStockQty({ qty: '1' })).toBeNull();
  });
});

describe('H2.5 — fungsi fetch Inventory Adjustment', () => {
  it('fetchAdjustments mengirim GET dengan filter & membaca amplop §3', async () => {
    const { client, requests } = stubClient({
      rows: [ROW],
      total_count: 1,
      has_more: false,
      next_cursor: null,
    });

    const page = await fetchAdjustments(client, { state: 'DRAFT', limit: 20 });

    expect(requests[0]?.path).toBe('/inventory/adjustments/?state=DRAFT&limit=20');
    expect(requests[0]?.method).toBe('GET');
    expect(page.total_count).toBe(1);
    expect(page.rows[0]?.code).toBe('ADJ-2026-0001');
  });

  it('fetchAdjustment mengirim GET detail', async () => {
    const { client, requests } = stubClient(DETAIL);

    const detail = await fetchAdjustment(client, 3);

    expect(requests[0]?.path).toBe('/inventory/adjustments/3/');
    expect(detail.id).toBe(3);
    expect(detail.sync.status).toBeNull();
  });

  it('createAdjustment (DRAFT) POST tanpa query commit', async () => {
    const { client, requests } = stubClient(DETAIL);

    const created = await createAdjustment(client, {
      product_id: 89,
      location_id: 8,
      qty_delta: '5.00',
      reason: 'Hasil opname',
    });

    expect(requests[0]?.path).toBe('/inventory/adjust/');
    expect(requests[0]?.body).toEqual({
      product_id: 89,
      location_id: 8,
      qty_delta: '5.00',
      reason: 'Hasil opname',
    });
    expect(created.commit).toBeUndefined();
  });

  it('createAdjustment commit=true memakai query ?commit=true', async () => {
    const { client, requests } = stubClient({
      ...DETAIL,
      state: 'COMMITTED',
      commit: { ok: true, ledger_id: 5, task_id: 'task-1', queued: true },
    });

    const created = await createAdjustment(
      client,
      { product_id: 89, location_id: 8, qty_delta: '5.00', reason: 'opname' },
      { commit: true, idempotencyKey: 'idem-1' },
    );

    expect(requests[0]?.path).toBe('/inventory/adjust/?commit=true');
    expect(requests[0]?.options).toEqual({ idempotencyKey: 'idem-1' });
    expect(created.commit?.queued).toBe(true);
  });

  it('commitAdjustment POST ke endpoint commit', async () => {
    const { client, requests } = stubClient({
      ...DETAIL,
      state: 'COMMITTED',
      ledger_id: 7,
      task_id: 'task-9',
      queued: true,
    });

    const result = await commitAdjustment(client, 3);

    expect(requests[0]?.path).toBe('/inventory/adjustments/3/commit/');
    expect(requests[0]?.method).toBe('POST');
    expect(result.state).toBe('COMMITTED');
    expect(result.ledger_id).toBe(7);
  });

  it('fetchStockQty memakai query product/location & boleh null', async () => {
    const { client, requests } = stubClient({
      product_id: 89,
      product_code: 'KAIN',
      product_odoo_id: null,
      location_id: 8,
      location_code: 'WH/STOK',
      location_odoo_id: 8,
      qty: null,
      source: 'odoo',
      stock_owner: 'odoo',
    });

    const stock = await fetchStockQty(client, 89, 8);

    expect(requests[0]?.path).toBe('/inventory/stock-qty/?product_id=89&location_id=8');
    expect(stock.qty).toBeNull();
    expect(stock.stock_owner).toBe('odoo');
  });

  it('error HTTP diteruskan sebagai pesan backend (bukan ditelan)', async () => {
    const client = failingClient(400, "Field 'qty_delta' tidak boleh 0.");

    await expect(
      createAdjustment(client, {
        product_id: 89,
        location_id: 8,
        qty_delta: '0.00',
        reason: 'salah',
      }),
    ).rejects.toThrow(/tidak boleh 0/);
    await expect(commitAdjustment(client, 3)).rejects.toThrow(/tidak boleh 0/);
  });

  it('bentuk respons rusak → melempar pesan yang jelas', async () => {
    const { client } = stubClient({ bukan: 'baris' });

    await expect(fetchAdjustment(client, 3)).rejects.toThrow(
      /Bentuk respons detail inventory adjustment tidak dikenali/,
    );
  });
});

