import { describe, expect, it } from 'vitest';
import {
  buildQualityDefectsPath,
  fetchQCLogs,
  readDefectRow,
  QUALITY_DEFECTS_PATH,
} from '@/api/qc';
import {
  buildQualityReworkPath,
  fetchReworkRecords,
  readReworkRow,
  QUALITY_REWORK_PATH,
} from '@/api/qc';
import { MODE } from '@/api/_adapter';
import type { ApiClient, ApiResponse } from '@/integrations/api-client';

/** F2C.2 — qcLog (`/quality/defects/` B4+G3) & qcRework (`/quality/rework/` B6) REAL. */

const DEFECT_BODY = {
  rows: [
    {
      bundle_code: 'B-001',
      wc_code: 'WC-03',
      defect_type: 'Jahitan',
      qty: 3,
      reason: 'meleset',
      recorded_at: '2026-10-01T08:00:00Z',
      location: 'lengan',
      action: 'rework',
      defect_entries: [{ type: 'Jahitan', qty: 3, location: 'lengan', note: 'meleset' }],
    },
    {
      bundle_code: null,
      wc_code: null,
      defect_type: 'Noda',
      qty: 1,
      reason: '',
      recorded_at: null,
      location: null,
      action: null,
      defect_entries: [],
    },
  ],
  total_count: 2,
  has_more: false,
  next_cursor: null,
};

const REWORK_BODY = {
  rows: [
    {
      bundle_code: 'B-001',
      from_step: null,
      to_step: null,
      iteration: 1,
      started_at: '2026-10-01T09:00:00Z',
      closed_at: null,
      is_open: true,
    },
  ],
  total_count: 1,
  has_more: false,
  next_cursor: null,
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

describe('F2C.2 — qcLog (defects)', () => {
  it('MODE qcLog = real; path + query wc', async () => {
    expect(MODE['qcLog']).toBe('real');
    expect(QUALITY_DEFECTS_PATH).toBe('/quality/defects/');
    expect(buildQualityDefectsPath({ wc: 'WC-03' })).toBe('/quality/defects/?wc=WC-03');

    const { client, paths } = stubClient(DEFECT_BODY);

    await fetchQCLogs(client);

    expect(paths).toEqual(['/quality/defects/']);
  });

  it('readDefectRow membaca defect_entries + action null', () => {
    const row = readDefectRow(DEFECT_BODY.rows[0]);

    expect(row?.defect_entries).toHaveLength(1);
    expect(row?.defect_entries[0]?.location).toBe('lengan');
    expect(row?.action).toBe('rework');
    expect(readDefectRow(DEFECT_BODY.rows[1])?.action).toBeNull();
    expect(readDefectRow('rusak')).toBeNull();
  });
});

describe('F2C.2 — qcRework', () => {
  it('MODE qcRework = real; from_step/to_step null dipertahankan', async () => {
    expect(MODE['qcRework']).toBe('real');
    expect(QUALITY_REWORK_PATH).toBe('/quality/rework/');
    expect(buildQualityReworkPath({ open: true })).toBe('/quality/rework/?open=true');

    const { client, paths } = stubClient(REWORK_BODY);
    const rows = await fetchReworkRecords(client);

    expect(paths).toEqual(['/quality/rework/']);
    expect(rows[0]?.from_step).toBeNull();
    expect(rows[0]?.to_step).toBeNull();
    expect(rows[0]?.is_open).toBe(true);

    const row = readReworkRow(REWORK_BODY.rows[0]);
    expect(row?.iteration).toBe(1);
    expect(row?.closed_at).toBeNull();
  });
});
