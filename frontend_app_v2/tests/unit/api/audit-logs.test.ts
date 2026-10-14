import { describe, expect, it } from 'vitest';
import {
  EMPTY_AUDIT_FILTERS,
  SETTINGS_AUDIT_PATH,
  auditLogDetailPath,
  buildAuditLogsPath,
  fetchAuditLog,
  fetchAuditLogs,
  parseAuditResult,
  parseUserId,
  readAuditLogDetail,
  readAuditLogPage,
  readAuditLogRow,
  readJsonObject,
} from '@/api/auditLogs';
import { MODE, isReal } from '@/api/_adapter';
import type { ApiClient, ApiResponse } from '@/integrations/api-client';

/**
 * H5.5 — adapter Audit Log Viewer (`/api/v1/settings/audit/`, READ-ONLY).
 *
 * Bentuk baris = PERSIS `core/audit/services.py::audit_row` (12 field); detail
 * (`audit_detail`) menambah `payload`/`metadata`/`user_agent`. Daftar memakai amplop
 * ListPage `{rows, total_count, has_more, next_cursor}`.
 */

const ROW = {
  id: 12,
  timestamp: '2026-10-14T03:00:00+00:00',
  user_id: 4,
  username: 'admin-audit',
  full_name: 'Sari Admin',
  action: 'master.create',
  resource: 'master.product',
  resource_id: '7',
  result: 'OK',
  request_id: 'req-1',
  ip_address: '10.0.0.1',
  metadata_preview: '{"fields": ["code"]}',
};

const DETAIL = {
  ...ROW,
  payload: { api_key: '***', code: 'PRD-1' },
  metadata: { fields: ['code'] },
  user_agent: 'vitest',
};

const PAGE = {
  rows: [ROW],
  total_count: 41,
  has_more: true,
  next_cursor: 50,
};

interface RecordedRequest {
  path: string;
  method: string;
}

function stubClient(data: unknown): { client: ApiClient; requests: RecordedRequest[] } {
  const requests: RecordedRequest[] = [];
  const reply = <T,>(): ApiResponse<T> => ({ ok: true, status: 200, data: data as T });

  const client = {
    get: async <T,>(path: string): Promise<ApiResponse<T>> => {
      requests.push({ path, method: 'GET' });

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
    get: async <T,>(): Promise<ApiResponse<T>> => response<T>(),
  } as unknown as ApiClient;
}

describe('H5.5 — MODE, path & parsing', () => {
  it('MODE.auditLogs = real + path daftar/detail', () => {
    expect(MODE['auditLogs']).toBe('real');
    expect(isReal('auditLogs')).toBe(true);
    expect(SETTINGS_AUDIT_PATH).toBe('/settings/audit/');
    expect(auditLogDetailPath(12)).toBe('/settings/audit/12/');
  });

  it('buildAuditLogsPath hanya mengirim filter terisi (trim + normalisasi)', () => {
    expect(buildAuditLogsPath()).toBe('/settings/audit/');
    expect(buildAuditLogsPath(EMPTY_AUDIT_FILTERS)).toBe('/settings/audit/');

    const path = buildAuditLogsPath({
      search: '  master  ',
      action: 'master.',
      resource: 'master.product',
      resource_id: '7',
      result: 'failed',
      date_from: '2026-10-01',
      date_to: '2026-10-14',
      user_id: ' 4 ',
    });

    const qs = new URLSearchParams(path.split('?')[1]);

    expect(path.startsWith('/settings/audit/?')).toBe(true);
    expect(qs.get('search')).toBe('master');
    expect(qs.get('action')).toBe('master.');
    expect(qs.get('resource')).toBe('master.product');
    expect(qs.get('resource_id')).toBe('7');
    expect(qs.get('result')).toBe('FAILED'); // dinormalisasi UPPER
    expect(qs.get('date_from')).toBe('2026-10-01');
    expect(qs.get('date_to')).toBe('2026-10-14');
    expect(qs.get('user_id')).toBe('4');

    // nilai tidak valid DIBUANG (bukan dikirim lalu 400)
    const invalid = buildAuditLogsPath({
      result: 'NGACO',
      user_id: 'abc',
      search: '   ',
    });

    expect(invalid).toBe('/settings/audit/');
  });

  it('buildAuditLogsPath: limit/cursor hanya bila masuk rentang backend', () => {
    const ok = buildAuditLogsPath({}, { limit: 200, cursor: 100000 });
    const qs = new URLSearchParams(ok.split('?')[1]);

    expect(qs.get('limit')).toBe('200');
    expect(qs.get('cursor')).toBe('100000');

    // di luar rentang / nol → tidak dikirim (server pakai default)
    expect(buildAuditLogsPath({}, { limit: 500 })).toBe('/settings/audit/');
    expect(buildAuditLogsPath({}, { limit: 0 })).toBe('/settings/audit/');
    expect(buildAuditLogsPath({}, { cursor: 0 })).toBe('/settings/audit/');
    expect(buildAuditLogsPath({}, { cursor: 200000 })).toBe('/settings/audit/');
  });

  it('parseUserId / parseAuditResult (pure edge case)', () => {
    expect(parseUserId('4')).toBe(4);
    expect(parseUserId(' 12 ')).toBe(12);
    expect(parseUserId(7)).toBe(7);
    expect(parseUserId('')).toBeNull();
    expect(parseUserId('abc')).toBeNull();
    expect(parseUserId('0')).toBeNull();
    expect(parseUserId('-3')).toBeNull();
    expect(parseUserId(null)).toBeNull();

    expect(parseAuditResult('ok')).toBe('OK');
    expect(parseAuditResult(' DENIED ')).toBe('DENIED');
    expect(parseAuditResult('ngaco')).toBe('');
    expect(parseAuditResult(undefined)).toBe('');
  });

  it('readAuditLogRow / readAuditLogPage (bentuk backend apa adanya)', () => {
    const row = readAuditLogRow(ROW);

    expect(row?.id).toBe(12);
    expect(row?.username).toBe('admin-audit');
    expect(row?.full_name).toBe('Sari Admin');
    expect(row?.metadata_preview).toBe('{"fields": ["code"]}');
    expect(row?.user_id).toBe(4);

    // user NULL (anonim/sistem) tetap valid
    const sistem = readAuditLogRow({ ...ROW, user_id: null, username: null, full_name: '' });

    expect(sistem?.user_id).toBeNull();
    expect(sistem?.username).toBeNull();

    const page = readAuditLogPage(PAGE);

    expect(page?.rows).toHaveLength(1);
    expect(page?.total_count).toBe(41);
    expect(page?.has_more).toBe(true);
    expect(page?.next_cursor).toBe(50);

    // kontrak lama `has_next` juga diterima
    const legacy = readAuditLogPage({
      rows: [ROW],
      total_count: 1,
      has_next: true,
      next_cursor: null,
    });

    expect(legacy?.has_more).toBe(true);
    expect(legacy?.next_cursor).toBeNull();

    // bentuk rusak → null / dilewati
    expect(readAuditLogPage({ rows: 'bukan array' })).toBeNull();
    expect(readAuditLogPage('bukan objek')).toBeNull();
    expect(readAuditLogRow({ tanpa: 'id' })).toBeNull();
    expect(readAuditLogPage({ rows: [{ id: 'x' }] })?.rows).toEqual([]);
  });

  it('readAuditLogDetail / readJsonObject', () => {
    const detail = readAuditLogDetail(DETAIL);

    expect(detail?.payload).toEqual({ api_key: '***', code: 'PRD-1' });
    expect(detail?.metadata).toEqual({ fields: ['code'] });
    expect(detail?.user_agent).toBe('vitest');
    expect(detail?.action).toBe('master.create');

    expect(readAuditLogDetail({ tanpa: 'id' })).toBeNull();
    expect(readJsonObject(null)).toEqual({});
    expect(readJsonObject('teks')).toEqual({});
    expect(readJsonObject({ a: 1 })).toEqual({ a: 1 });
  });
});

describe('H5.5 — HTTP adapter', () => {
  it('fetchAuditLogs GET daftar + filter + paging', async () => {
    const stub = stubClient(PAGE);

    const page = await fetchAuditLogs(
      stub.client,
      { action: 'master.', result: 'OK' },
      { limit: 50, cursor: 50 },
    );

    const qs = new URLSearchParams(stub.requests[0].path.split('?')[1]);

    expect(stub.requests).toHaveLength(1);
    expect(stub.requests[0].method).toBe('GET');
    expect(qs.get('action')).toBe('master.');
    expect(qs.get('result')).toBe('OK');
    expect(qs.get('limit')).toBe('50');
    expect(qs.get('cursor')).toBe('50');
    expect(page.total_count).toBe(41);
  });

  it('fetchAuditLog GET detail (amplop {audit}) + path', async () => {
    const stub = stubClient({ audit: DETAIL });

    const detail = await fetchAuditLog(stub.client, 12);

    expect(stub.requests).toEqual([{ path: '/settings/audit/12/', method: 'GET' }]);
    expect(detail.payload['api_key']).toBe('***');
    expect(detail.user_agent).toBe('vitest');
  });

  it('gagal HTTP & bentuk rusak → melempar', async () => {
    await expect(
      fetchAuditLogs(failingClient(403, 'Hanya user dengan role ADMIN/OWNER')),
    ).rejects.toThrow('ADMIN/OWNER');
    await expect(
      fetchAuditLog(failingClient(404, 'Audit log tidak ditemukan.')),
    ).rejects.toThrow('tidak ditemukan');
    await expect(fetchAuditLogs(stubClient({ rows: 'rusak' }).client)).rejects.toThrow(
      'tidak dikenali',
    );
    await expect(fetchAuditLog(stubClient({ audit: { tanpa: 'id' } }).client, 1)).rejects.toThrow(
      'tidak dikenali',
    );
  });
});

