import { describe, expect, it } from 'vitest';
import {
  buildMasterSequencesPath,
  createSequence,
  deleteSequence,
  fetchSequences,
  previewSequenceNumber,
  readMasterSequencePage,
  readMasterSequenceRow,
  readSequencePreview,
  SEQUENCES_LIMIT_DEFAULT,
  SEQUENCES_LIMIT_MAX,
  sequenceCreatePath,
  sequenceDetailPath,
  sequencePreviewPath,
  SETTINGS_SEQUENCES_PATH,
  toMasterSequenceBody,
  toMasterSequenceCreateBody,
  updateSequence,
} from '@/api/masterSequences';
import { MODE, isReal } from '@/api/_adapter';
import type { ApiClient, ApiResponse } from '@/integrations/api-client';
import type { MasterSequenceRow } from '@/types/master-sequence';

/**
 * Sprint C — adapter Number Sequence (`/api/v1/settings/sequences/`).
 *
 * Bentuk = PERSIS `django_app/master/sequence_services.py::sequence_row`:
 * `{id, code, name, prefix, year, last_seq, padding, is_active, next_number,
 * created_at, updated_at}`; pratinjau = field yang sama **tanpa** `id`/timestamp.
 * **Tanpa `odoo_id`** — MES-only (`ir.sequence` Odoo = counter internal dokumen Odoo).
 */

const ROW: MasterSequenceRow = {
  id: 4,
  code: 'SO',
  name: 'Sales Order',
  prefix: 'SO',
  year: 2026,
  last_seq: 12,
  padding: 4,
  is_active: true,
  next_number: 'SO-2026-0013',
  created_at: '2026-10-11T04:00:00+00:00',
  updated_at: '2026-10-11T05:00:00+00:00',
};

const PREVIEW = {
  code: 'SO',
  name: 'Sales Order',
  prefix: 'SO',
  year: 2026,
  last_seq: 12,
  padding: 4,
  is_active: true,
  next_number: 'SO-2026-0013',
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

describe('Sprint C — MODE, path & parsing', () => {
  it('MODE.masterSequences = real + path list/preview/detail', () => {
    expect(MODE['masterSequences']).toBe('real');
    expect(isReal('masterSequences')).toBe(true);
    expect(SETTINGS_SEQUENCES_PATH).toBe('/settings/sequences/');
    expect(SEQUENCES_LIMIT_DEFAULT).toBe(50);
    expect(SEQUENCES_LIMIT_MAX).toBe(200);

    expect(sequencePreviewPath('SO')).toBe('/settings/sequences/SO/preview/');
    expect(sequenceDetailPath('SO')).toBe('/settings/sequences/SO/');
  });

  it('buildMasterSequencesPath hanya mengirim param terisi (year all/angka)', () => {
    expect(buildMasterSequencesPath()).toBe('/settings/sequences/');
    expect(buildMasterSequencesPath({ search: 'sales', active: false, limit: 200 })).toBe(
      '/settings/sequences/?search=sales&active=false&limit=200',
    );
    expect(buildMasterSequencesPath({ year: 'all' })).toBe('/settings/sequences/?year=all');
    expect(buildMasterSequencesPath({ year: 2027, cursor: 20 })).toBe(
      '/settings/sequences/?year=2027&cursor=20',
    );
  });

  it('readMasterSequenceRow/Page + readSequencePreview (bentuk backend apa adanya)', () => {
    const row = readMasterSequenceRow(ROW);

    expect(Object.keys(row ?? {}).sort()).toEqual(
      [
        'code',
        'created_at',
        'id',
        'is_active',
        'last_seq',
        'name',
        'next_number',
        'padding',
        'prefix',
        'updated_at',
        'year',
      ].sort(),
    );
    expect(row?.next_number).toBe('SO-2026-0013');

    const page = readMasterSequencePage({
      rows: [ROW],
      total_count: 7,
      has_more: false,
      next_cursor: null,
    });

    expect(page?.total_count).toBe(7);
    expect(page?.rows[0]?.code).toBe('SO');

    const preview = readSequencePreview(PREVIEW);

    expect(preview?.last_seq).toBe(12);
    expect(preview?.next_number).toBe('SO-2026-0013');
    expect(readSequencePreview('bukan objek')).toBeNull();
    expect(readMasterSequenceRow(null)).toBeNull();
  });

  it('toMasterSequenceBody hanya membawa field yang dikirim', () => {
    expect(toMasterSequenceBody({ prefix: 'SO-2' })).toEqual({ prefix: 'SO-2' });
    expect(
      toMasterSequenceBody({ name: 'Sales', prefix: 'SO', padding: 6, active: false }),
    ).toEqual({ name: 'Sales', prefix: 'SO', padding: 6, active: false });
  });
});

describe('Sprint C — HTTP adapter', () => {
  it('fetchSequences GET list + previewSequenceNumber GET preview', async () => {
    const list = stubClient({ rows: [ROW], total_count: 1, has_more: false, next_cursor: null });

    const page = await fetchSequences(list.client, { active: true, limit: 200 });

    expect(list.requests).toEqual([
      { path: '/settings/sequences/?active=true&limit=200', method: 'GET' },
    ]);
    expect(page.rows[0]?.next_number).toBe('SO-2026-0013');

    const one = stubClient(PREVIEW);

    const preview = await previewSequenceNumber(one.client, 'SO');

    expect(one.requests).toEqual([{ path: '/settings/sequences/SO/preview/', method: 'GET' }]);
    expect(preview.code).toBe('SO');
  });

  it('updateSequence PUT prefix/padding (ADMIN/OWNER)', async () => {
    const stub = stubClient({ ...ROW, prefix: 'SO-2', padding: 6 });

    const saved = await updateSequence(stub.client, 'SO', { prefix: 'SO-2', padding: 6 });

    expect(stub.requests).toEqual([
      { path: '/settings/sequences/SO/', method: 'PUT', body: { prefix: 'SO-2', padding: 6 } },
    ]);
    expect(saved.prefix).toBe('SO-2');
  });

  it('gagal HTTP → melempar (pesan backend tampil di UI)', async () => {
    await expect(
      previewSequenceNumber(failingClient(404, "Sequence 'ZZ' tidak dikenal."), 'ZZ'),
    ).rejects.toThrow("Sequence 'ZZ' tidak dikenal.");
    await expect(
      updateSequence(failingClient(403, 'Hanya user dengan role ADMIN/OWNER'), 'SO', {
        prefix: 'X',
      }),
    ).rejects.toThrow('ADMIN/OWNER');
  });
});

/** Klien 204 tanpa body (soft delete) — `data` undefined tapi `ok` true. */
function noContentClient(): { client: ApiClient; requests: RecordedRequest[] } {
  const requests: RecordedRequest[] = [];

  const client = {
    request: async <T,>(
      path: string,
      options?: { method?: 'GET' | 'POST' | 'PUT' | 'DELETE'; body?: unknown },
    ): Promise<ApiResponse<T>> => {
      requests.push({ path, method: options?.method ?? 'GET', body: options?.body });

      return { ok: true, status: 204 };
    },
  } as unknown as ApiClient;

  return { client, requests };
}

describe('H5.3 — CRUD create & delete', () => {
  it('sequenceCreatePath + toMasterSequenceCreateBody (PURE)', () => {
    expect(sequenceCreatePath()).toBe('/settings/sequences/');
    expect(sequenceCreatePath(null)).toBe('/settings/sequences/');
    expect(sequenceCreatePath(2027)).toBe('/settings/sequences/?year=2027');

    // adapter hanya men-trim; auto-UPPER dilakukan lib (`createSequenceInputFromForm`)
    expect(
      toMasterSequenceCreateBody({ code: ' adj ', name: ' Adjustment ', padding: 5 }),
    ).toEqual({ code: 'adj', name: 'Adjustment', padding: 5 });
    expect(toMasterSequenceCreateBody({ code: ' X1 ', name: 'X', prefix: '   ' })).toEqual({
      code: 'X1',
      name: 'X',
    });
  });

  it('createSequence POST (opsional ?year= dari filter halaman)', async () => {
    const post = stubClient({ ...ROW, id: 9, code: 'ADJ', name: 'Adjustment' });

    const created = await createSequence(post.client, {
      code: 'ADJ',
      name: 'Adjustment',
      padding: 4,
    });

    expect(post.requests).toEqual([
      {
        path: '/settings/sequences/',
        method: 'POST',
        body: { code: 'ADJ', name: 'Adjustment', padding: 4 },
      },
    ]);
    expect(created.code).toBe('ADJ');

    const tahun = stubClient({ ...ROW, year: 2027 });

    await createSequence(tahun.client, { code: 'X1', name: 'X' }, 2027);

    expect(tahun.requests[0]?.path).toBe('/settings/sequences/?year=2027');
  });

  it('createSequence bentuk respons rusak → melempar', async () => {
    await expect(
      createSequence(stubClient('bukan objek').client, { code: 'X1', name: 'X' }),
    ).rejects.toThrow('tidak dikenali');
  });

  it('deleteSequence DELETE 204 (tanpa body) + pesan gagal backend', async () => {
    const ok = noContentClient();

    await deleteSequence(ok.client, 'CUSTOM1');

    expect(ok.requests).toEqual([
      { path: '/settings/sequences/CUSTOM1/', method: 'DELETE', body: undefined },
    ]);

    await expect(
      deleteSequence(failingClient(400, "Sequence 'SO' masih dipakai (protected seed)"), 'SO'),
    ).rejects.toThrow('protected seed');
    await expect(deleteSequence(failingClient(403, 'Hanya user dengan role ADMIN/OWNER'), 'X1')).rejects.toThrow(
      'ADMIN/OWNER',
    );
  });
});

