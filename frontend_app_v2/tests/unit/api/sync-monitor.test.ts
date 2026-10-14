import { describe, expect, it } from 'vitest';
import {
  buildSyncRecordsPath,
  getSyncRecords,
  parseSyncStage,
  parseSyncStatus,
  readSyncRecordPage,
  readSyncRecordRow,
  SYNC_RECORDS_PATH,
  SYNC_STAGES,
  SYNC_STATUSES,
} from '@/api/syncMonitor';
import { MODE } from '@/api/_adapter';
import type { ApiClient, ApiResponse } from '@/integrations/api-client';

/**
 * F15 — adapter monitoring SyncRecord (`GET /sync/records/`, Fase 4.4).
 *
 * Bentuk di bawah = PERSIS backend `monitoring.SyncRecordListView`: envelope
 * `{rows, total_count, has_next, next_cursor}`, baris `{id, resource, resource_id, stage,
 * status, attempts, last_error, erp_id, sent_at, created_at}`; filter `stage`/`status`.
 */

const LIVE_BODY = {
  rows: [
    {
      id: 19,
      resource: 'order',
      resource_id: '1',
      stage: 'INVOICE',
      status: 'SENT',
      attempts: 1,
      last_error: null,
      erp_id: 'INV/2026/0001',
      sent_at: '2026-10-08T03:00:00Z',
      created_at: '2026-10-08T02:59:00Z',
    },
    {
      id: 18,
      resource: 'bundle',
      resource_id: '7',
      stage: 'WIP',
      status: 'FAILED',
      attempts: 3,
      last_error: 'Odoo timeout',
      erp_id: null,
      sent_at: null,
      created_at: '2026-10-08T01:00:00Z',
    },
  ],
  total_count: 2,
  has_next: true,
  next_cursor: 2,
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

describe('F15 — MODE & path sync records', () => {
  it('MODE syncMonitor = real (endpoint Fase 4.4 ADA)', () => {
    expect(MODE['syncMonitor']).toBe('real');
  });

  it('path default + filter stage/status (case-insensitive)', async () => {
    expect(SYNC_RECORDS_PATH).toBe('/sync/records/');
    expect(buildSyncRecordsPath()).toBe('/sync/records/');
    expect(buildSyncRecordsPath({ stage: 'wip' })).toBe('/sync/records/?stage=WIP');
    expect(buildSyncRecordsPath({ status: 'failed' })).toBe('/sync/records/?status=FAILED');
    expect(buildSyncRecordsPath({ stage: 'NGAWUR' })).toBe('/sync/records/');
    expect(buildSyncRecordsPath({ stage: 'FG', status: 'SENT', limit: 20, cursor: 40 })).toBe(
      '/sync/records/?stage=FG&status=SENT&limit=20&cursor=40',
    );

    const { client, paths } = stubClient(LIVE_BODY);

    await getSyncRecords(client, { stage: 'INVOICE' });

    expect(paths).toEqual(['/sync/records/?stage=INVOICE']);
  });

  it('enum & parser stage/status', () => {
    expect(SYNC_STAGES).toEqual(['WIP', 'FG', 'SCRAP', 'INVOICE']);
    expect(SYNC_STATUSES).toEqual(['PENDING', 'SENT', 'FAILED', 'DUPLICATE']);
    expect(parseSyncStage(' FG ')).toBe('FG');
    expect(parseSyncStage('')).toBeNull();
    expect(parseSyncStatus('duplicate')).toBe('DUPLICATE');
    expect(parseSyncStatus(undefined)).toBeNull();
  });
});

describe('F15 — readSyncRecordPage', () => {
  it('respons Fase 4.4 → SyncRecordPage', async () => {
    const { client } = stubClient(LIVE_BODY);

    const page = await getSyncRecords(client);

    expect(page.total_count).toBe(2);
    expect(page.has_next).toBe(true);
    expect(page.next_cursor).toBe(2);
    expect(page.rows[0]?.stage).toBe('INVOICE');
    expect(page.rows[1]?.last_error).toBe('Odoo timeout');
    expect(page.rows[1]?.attempts).toBe(3);
  });

  it('baris tanpa id angka dibuang; envelope `has_more` diterima', () => {
    const parsed = readSyncRecordPage({
      rows: [{ id: 5, status: 'PENDING' }, { resource: 'bundle' }, 'rusak'],
      total_count: 9,
      has_more: true,
      next_cursor: 1,
    });

    expect(parsed?.rows).toHaveLength(1);
    expect(parsed?.rows[0]?.stage).toBe('');
    expect(parsed?.has_next).toBe(true);
    expect(readSyncRecordRow({ id: '5' })).toBeNull();
  });

  it('envelope tak dikenal → null', () => {
    expect(readSyncRecordPage(null)).toBeNull();
    expect(readSyncRecordPage({ rows: 'bukan-array' })).toBeNull();
  });
});

describe('F15 — error HTTP sync records', () => {
  it('403 (perlu session) → melempar pesan', async () => {
    const client = {
      get: async <T,>(): Promise<ApiResponse<T>> => ({
        ok: false,
        status: 403,
        error: { kind: 'http_error', message: 'HTTP 403' },
      }),
    } as unknown as ApiClient;

    await expect(getSyncRecords(client)).rejects.toThrow(/403/);
  });

  it('bentuk respons tak dikenali → melempar pesan jelas', async () => {
    const { client } = stubClient({ ok: true });

    await expect(getSyncRecords(client)).rejects.toThrow(/tidak dikenali/);
  });
});
