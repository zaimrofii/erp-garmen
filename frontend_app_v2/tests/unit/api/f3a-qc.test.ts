import { describe, expect, it } from 'vitest';
import {
  buildQualityAqlPath,
  fetchAqlSummary,
  QUALITY_AQL_PATH,
  readAqlReport,
} from '@/api/real/qcAql';
import { readDefectSubmitResult, submitDefect } from '@/api/real/qcSubmit';
import { MODE } from '@/api/_adapter';
import type { ApiClient, ApiResponse } from '@/integrations/api-client';

/**
 * F3A.CLOSE — adapter REAL QC: AQL (B5) + submit defect (B7b).
 * Bentuk PERSIS `monitoring.QualityAqlView` / `QualityDefectsSubmitView`.
 */

const AQL_BODY = {
  rows: [
    {
      wc_code: 'JAHIT-01',
      wc_name: 'Jahit 01',
      sample_qty: 40,
      defect_qty: 1,
      aql_pct: 2.5,
      severity: 'warn',
    },
  ],
  generated_at: '2026-10-10T08:00:00+07:00',
  period: { from: '2026-09-10', to: '2026-10-10' },
};

const SUBMIT_BODY = { ok: true, bundle_event_id: 'evt-1', cycle_instance_id: 12 };

function stubClient(data: unknown): {
  client: ApiClient;
  gets: string[];
  posts: { path: string; body: unknown }[];
} {
  const gets: string[] = [];
  const posts: { path: string; body: unknown }[] = [];

  const client = {
    get: async <T,>(path: string): Promise<ApiResponse<T>> => {
      gets.push(path);
      return { ok: true, status: 200, data: data as T };
    },
    post: async <T,>(path: string, body?: unknown): Promise<ApiResponse<T>> => {
      posts.push({ path, body });
      return { ok: true, status: 201, data: data as T };
    },
  } as unknown as ApiClient;

  return { client, gets, posts };
}

describe('F3A.CLOSE — MODE qcAql & qcSubmit', () => {
  it('kedua key = real', () => {
    expect(MODE['qcAql']).toBe('real');
    expect(MODE['qcSubmit']).toBe('real');
  });
});

describe('F3A.CLOSE — readAqlReport / buildQualityAqlPath', () => {
  it('memetakan field backend apa adanya', () => {
    const report = readAqlReport(AQL_BODY);

    expect(report).not.toBeNull();
    expect(report?.rows[0]).toEqual({
      wc_code: 'JAHIT-01',
      wc_name: 'Jahit 01',
      sample_qty: 40,
      defect_qty: 1,
      aql_pct: 2.5,
      severity: 'warn',
    });
    expect(report?.period.to).toBe('2026-10-10');
  });

  it('severity tak dikenal → pass; rows bukan array → null', () => {
    expect(readAqlReport({ rows: [{}] })?.rows[0]?.severity).toBe('pass');
    expect(readAqlReport({ rows: {} })).toBeNull();
    expect(readAqlReport(null)).toBeNull();
  });

  it('path default + filter from/to', () => {
    expect(QUALITY_AQL_PATH).toBe('/quality/aql/');
    expect(buildQualityAqlPath()).toBe('/quality/aql/');
    expect(buildQualityAqlPath({ from: '2026-09-01', to: '' })).toBe(
      '/quality/aql/?from=2026-09-01',
    );
  });

  it('fetchAqlSummary GET + parse', async () => {
    const { client, gets } = stubClient(AQL_BODY);
    const report = await fetchAqlSummary(client);

    expect(gets).toEqual(['/quality/aql/']);
    expect(report.rows).toHaveLength(1);
  });
});

describe('F3A.CLOSE — submitDefect (POST /quality/defects/)', () => {
  it('readDefectSubmitResult menormalkan respons', () => {
    expect(readDefectSubmitResult(SUBMIT_BODY)).toEqual({
      ok: true,
      bundle_event_id: 'evt-1',
      cycle_instance_id: 12,
    });
    expect(readDefectSubmitResult({})).toEqual({
      ok: false,
      bundle_event_id: null,
      cycle_instance_id: null,
    });
  });

  it('mengirim body backend (bundle_id + defect_type + qty + reason + action)', async () => {
    const { client, posts } = stubClient(SUBMIT_BODY);
    const result = await submitDefect(client, {
      bundle_id: 5,
      defect_type: 'jahitan_loncat',
      qty: 3,
      reason: 'sleeve_left',
      action: 'rework',
    });

    expect(posts).toHaveLength(1);
    expect(posts[0]?.path).toBe('/quality/defects/');
    expect(posts[0]?.body).toEqual({
      bundle_id: 5,
      defect_type: 'jahitan_loncat',
      qty: 3,
      reason: 'sleeve_left',
      action: 'rework',
    });
    expect(result.cycle_instance_id).toBe(12);
  });

  it('reason default string kosong (opsional)', async () => {
    const { client, posts } = stubClient(SUBMIT_BODY);
    await submitDefect(client, { bundle_id: 1, defect_type: 'kain_rusak', qty: 1, action: 'scrap' });

    expect(posts[0]?.body).toMatchObject({ reason: '' });
  });
});
