import { describe, expect, it } from 'vitest';
import { MODE } from '@/api/_adapter';
import { getQcRow, getQcRows, QC_PATH, readQcRow, readQcRows } from '@/api/qc';
import type { ApiClient, ApiResponse } from '@/integrations/api-client';

/** F2/2.3 — adapter `qcRows` BARU (real) + 4 key QC lama tetap dummy (kontrak halaman tak pecah). */

/** Baris PERSIS dari backend live: `GET /api/v1/garmen/qc/?limit=2`. */
const LIVE_ROW = {
  id: 1,
  work_center_code: 'SEWING-DEMO',
  bundle_code: 'BND-DEMO-001',
  qty: 3,
  rework_qty: 1,
  end_loss_qty: 2,
  reason: 'demo curl',
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

describe('D7/F2 — qcRows (real) path', () => {
  it('QC_PATH = /garmen/qc/', () => {
    expect(QC_PATH).toBe('/garmen/qc/');
  });

  it('getQcRows memakai limit/offset (pola getBundles)', async () => {
    const { client, paths } = stubClient({ rows: [], total_count: 0, has_more: false, next_cursor: null });

    await getQcRows(client, { limit: 5, offset: 10 });

    expect(paths).toEqual(['/garmen/qc/?limit=5&offset=10']);
  });

  it('getQcRows tanpa param → tanpa query', async () => {
    const { client, paths } = stubClient({ rows: [], total_count: 0, has_more: false, next_cursor: null });

    await getQcRows(client);

    expect(paths).toEqual(['/garmen/qc/']);
  });

  it('getQcRow memakai id di path', async () => {
    const { client, paths } = stubClient(LIVE_ROW);

    await getQcRow(client, 1);

    expect(paths).toEqual(['/garmen/qc/1/']);
  });
});

describe('F2 — qcRows (real) shape', () => {
  it('baris live backend → QcRow apa adanya (snake_case)', () => {
    expect(readQcRow(LIVE_ROW)).toEqual(LIVE_ROW);
  });

  it('baris rusak → null (id wajib angka)', () => {
    expect(readQcRow({ work_center_code: 'X' })).toBeNull();
    expect(readQcRow({ ...LIVE_ROW, id: '1' })).toBeNull();
    expect(readQcRow(null)).toBeNull();
    expect(readQcRow('qc')).toBeNull();
    expect(readQcRow([LIVE_ROW])).toBeNull();
  });

  it('baris tanpa qty/reason → default aman (0 / null)', () => {
    expect(readQcRow({ id: 9 })).toEqual({
      id: 9,
      work_center_code: null,
      bundle_code: null,
      qty: 0,
      rework_qty: 0,
      end_loss_qty: 0,
      reason: null,
    });
  });

  it('readQcRows melewati baris rusak, urutan tetap', () => {
    const rows = readQcRows([LIVE_ROW, 'rusak', { id: 2, qty: 5 }]);

    expect(rows.map((row) => row.id)).toEqual([1, 2]);
    expect(rows[1]?.qty).toBe(5);
  });
});

describe('F2C.2 + F3A.CLOSE — key QC', () => {
  it('SELURUH key /quality/* real (F3A.CLOSE)', () => {
    expect(MODE['qcRows']).toBe('real');
    expect(MODE['qcLog']).toBe('real');
    expect(MODE['qcRework']).toBe('real');
    expect(MODE['qcAql']).toBe('real');
    expect(MODE['qcSubmit']).toBe('real');
  });
});
