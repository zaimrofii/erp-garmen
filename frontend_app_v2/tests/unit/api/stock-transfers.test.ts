import { describe, expect, it } from 'vitest';
import {
  buildTransfersPath,
  commitTransfer,
  createTransfer,
  fetchTransfer,
  fetchTransfers,
  INVENTORY_TRANSFERS_PATH,
  INVENTORY_TRANSFER_PATH,
  readTransferCommitResult,
  readTransferCreated,
  readTransferDetail,
  readTransferRow,
  transferCommitPath,
  transferDetailPath,
} from '@/api/stockTransfers';
import { MODE, isReal } from '@/api/_adapter';
import type { ApiClient, ApiResponse } from '@/integrations/api-client';

/**
 * H2.6 — adapter Stock Transfer (`/api/v1/inventory/transfer*`).
 *
 * Bentuk = PERSIS `apps_industry/garment/services/stock_transfer_services.py`
 * (`transfer_row`/`transfer_detail_row`): decimal sebagai **string**, snapshot
 * `qty_before` boleh `null`, detail menambah blok `sync`, commit menambah
 * `ledger_id`/`task_id`/`queued`, dan jejak Odoo = `odoo_picking_id`/`odoo_picking_name`.
 */

interface RecordedRequest {
  path: string;
  method: string;
  body?: unknown;
}

const ROW = {
  id: 4,
  code: 'TRF-2026-0001',
  product_id: 89,
  product_code: 'KAIN-COTTON',
  product_name: 'Kain Cotton',
  from_location_id: 8,
  from_location_code: 'WH/STOK',
  from_location_name: 'Stok',
  to_location_id: 50,
  to_location_code: 'WH/PROD',
  to_location_name: 'Produksi',
  qty: '5.00',
  qty_before: '60.00',
  reason: 'Pindah lini',
  state: 'DRAFT',
  odoo_picking_id: null,
  odoo_picking_name: '',
  last_error: '',
  created_by: 'sim-h26',
  created_at: '2026-10-12T04:00:00+00:00',
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

describe('H2.6 — path & reader PURE Stock Transfer', () => {
  it('mode adapter = real + path backend sesuai config/urls.py', () => {
    expect(MODE['stockTransfers']).toBe('real');
    expect(isReal('stockTransfers')).toBe(true);
    expect(INVENTORY_TRANSFER_PATH).toBe('/inventory/transfer/');
    expect(INVENTORY_TRANSFERS_PATH).toBe('/inventory/transfers/');
    expect(transferDetailPath(4)).toBe('/inventory/transfers/4/');
    expect(transferCommitPath(4)).toBe('/inventory/transfers/4/commit/');
  });

  it('buildTransfersPath hanya mengirim param terisi', () => {
    expect(buildTransfersPath()).toBe('/inventory/transfers/');
    expect(buildTransfersPath({ search: 'TRF', state: 'DRAFT', limit: 20 })).toBe(
      '/inventory/transfers/?search=TRF&state=DRAFT&limit=20',
    );
    expect(buildTransfersPath({ product_id: 89, from_location_id: 8, to_location_id: 50 })).toBe(
      '/inventory/transfers/?product_id=89&from_location_id=8&to_location_id=50',
    );
    expect(buildTransfersPath({ state: null, search: null })).toBe('/inventory/transfers/');
  });

  it('readTransferRow mempertahankan decimal string, snapshot null & jejak picking', () => {
    const row = readTransferRow(ROW);

    expect(row).not.toBeNull();
    expect(row?.qty).toBe('5.00');
    expect(row?.qty_before).toBe('60.00');
    expect(row?.odoo_picking_id).toBeNull();
    expect(row?.from_location_code).toBe('WH/STOK');
    expect(row?.to_location_code).toBe('WH/PROD');

    const denganPicking = readTransferRow({
      ...ROW,
      state: 'SYNCED',
      odoo_picking_id: 77,
      odoo_picking_name: 'WH/INT/00003',
    });
    expect(denganPicking?.odoo_picking_id).toBe(77);
    expect(denganPicking?.odoo_picking_name).toBe('WH/INT/00003');
  });

  it('readTransferRow menolak baris tanpa id / bukan objek', () => {
    expect(readTransferRow({ code: 'TRF' })).toBeNull();
    expect(readTransferRow(null)).toBeNull();
    expect(readTransferRow([])).toBeNull();
  });

  it('readTransferDetail menambahkan blok sync (default null)', () => {
    expect(readTransferDetail(ROW)?.sync).toEqual({
      record_id: null,
      status: null,
      erp_id: null,
      attempts: 0,
    });

    const withSync = readTransferDetail({
      ...ROW,
      sync: { record_id: 12, status: 'SENT', erp_id: '77', attempts: 1 },
    });
    expect(withSync?.sync).toEqual({ record_id: 12, status: 'SENT', erp_id: '77', attempts: 1 });
  });

  it('readTransferCreated membaca blok commit saat ?commit=true', () => {
    expect(readTransferCreated(DETAIL)?.commit).toBeUndefined();

    const committed = readTransferCreated({
      ...DETAIL,
      state: 'COMMITTED',
      commit: { ok: true, ledger_id: 9, task_id: 'task-trf-1', queued: true },
    });
    expect(committed?.state).toBe('COMMITTED');
    expect(committed?.commit?.queued).toBe(true);
    expect(committed?.commit?.ledger_id).toBe(9);
  });

  it('readTransferCreated membaca commit gagal (tetap DRAFT + detail)', () => {
    const failed = readTransferCreated({
      ...DETAIL,
      commit: { ok: false, detail: 'Lokasi asal belum punya odoo_id.' },
    });

    expect(failed?.commit?.ok).toBe(false);
    expect(failed?.commit?.detail).toBe('Lokasi asal belum punya odoo_id.');
    expect(failed?.state).toBe('DRAFT');
  });

  it('readTransferCommitResult membaca ledger/task/queued', () => {
    const result = readTransferCommitResult({
      ...DETAIL,
      state: 'COMMITTED',
      ledger_id: 11,
      task_id: 'task-9',
      queued: true,
    });

    expect(result?.ledger_id).toBe(11);
    expect(result?.task_id).toBe('task-9');
    expect(result?.queued).toBe(true);
  });
});

describe('H2.6 — fungsi fetch Stock Transfer', () => {
  it('fetchTransfers mengirim GET dengan filter & membaca amplop §3', async () => {
    const { client, requests } = stubClient({
      rows: [ROW],
      total_count: 1,
      has_more: false,
      next_cursor: null,
    });

    const page = await fetchTransfers(client, { state: 'DRAFT', limit: 20 });

    expect(requests[0]?.path).toBe('/inventory/transfers/?state=DRAFT&limit=20');
    expect(requests[0]?.method).toBe('GET');
    expect(page.total_count).toBe(1);
    expect(page.rows[0]?.code).toBe('TRF-2026-0001');
  });

  it('fetchTransfer mengirim GET detail', async () => {
    const { client, requests } = stubClient(DETAIL);

    const detail = await fetchTransfer(client, 4);

    expect(requests[0]?.path).toBe('/inventory/transfers/4/');
    expect(detail.id).toBe(4);
    expect(detail.sync.status).toBeNull();
  });

  it('createTransfer (DRAFT) POST tanpa query commit', async () => {
    const { client, requests } = stubClient(DETAIL);

    const created = await createTransfer(client, {
      product_id: 89,
      from_location_id: 8,
      to_location_id: 50,
      qty: '5.00',
      reason: 'Pindah lini',
    });

    expect(requests[0]?.path).toBe('/inventory/transfer/');
    expect(requests[0]?.body).toEqual({
      product_id: 89,
      from_location_id: 8,
      to_location_id: 50,
      qty: '5.00',
      reason: 'Pindah lini',
    });
    expect(created.commit).toBeUndefined();
  });

  it('createTransfer commit=true memakai query ?commit=true', async () => {
    const { client, requests } = stubClient({
      ...DETAIL,
      state: 'COMMITTED',
      commit: { ok: true, ledger_id: 9, task_id: 'task-trf-1', queued: true },
    });

    const created = await createTransfer(
      client,
      { product_id: 89, from_location_id: 8, to_location_id: 50, qty: '5.00', reason: '' },
      { commit: true, idempotencyKey: 'idem-trf-1' },
    );

    expect(requests[0]?.path).toBe('/inventory/transfer/?commit=true');
    expect(requests[0]?.options).toEqual({ idempotencyKey: 'idem-trf-1' });
    expect(created.commit?.task_id).toBe('task-trf-1');
  });

  it('commitTransfer POST ke endpoint commit', async () => {
    const { client, requests } = stubClient({
      ...DETAIL,
      state: 'COMMITTED',
      ledger_id: 11,
      task_id: 'task-trf-2',
      queued: true,
    });

    const result = await commitTransfer(client, 4);

    expect(requests[0]?.path).toBe('/inventory/transfers/4/commit/');
    expect(requests[0]?.method).toBe('POST');
    expect(result.state).toBe('COMMITTED');
    expect(result.task_id).toBe('task-trf-2');
  });

  it('error HTTP diteruskan sebagai pesan backend (bukan ditelan)', async () => {
    const client = failingClient(400, 'Lokasi asal dan tujuan TIDAK boleh sama.');

    await expect(
      createTransfer(client, {
        product_id: 89,
        from_location_id: 8,
        to_location_id: 8,
        qty: '5.00',
        reason: '',
      }),
    ).rejects.toThrow(/TIDAK boleh sama/);
    await expect(commitTransfer(client, 4)).rejects.toThrow(/TIDAK boleh sama/);
  });

  it('bentuk respons rusak → melempar pesan yang jelas', async () => {
    const { client } = stubClient({ bukan: 'baris' });

    await expect(fetchTransfer(client, 4)).rejects.toThrow(
      /Bentuk respons detail stock transfer tidak dikenali/,
    );
  });
});
