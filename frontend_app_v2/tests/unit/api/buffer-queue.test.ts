import { describe, expect, it } from 'vitest';
import { BUFFER_QUEUE_PATH, fetchBufferQueue, readBufferQueueSummary } from '@/api/bufferQueue';
import { MODE } from '@/api/_adapter';
import type { ApiClient, ApiResponse } from '@/integrations/api-client';

/** F2C.2 — bufferQueue REAL (`GET /api/v1/production/buffer-queue/`, B2 + G2). */

const LIVE_BODY = {
  rows: [
    {
      wc_code: 'WC-01',
      wc_name: 'Cutting 1',
      queue_depth: 2,
      avg_wait_min: 45,
      bundles: [
        {
          code: 'B-001',
          qty: 12,
          waited_min: 30,
          state: 'CUTTING',
          from_wc: null,
          to_wc: 'WC-02',
          status: 'CUTTING',
        },
        {
          code: 'B-002',
          qty: 8,
          waited_min: 60,
          state: 'SEWING',
          from_wc: 'WC-01',
          to_wc: null,
          status: 'SEWING',
        },
      ],
    },
  ],
  generated_at: '2026-10-02T10:00:00Z',
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

describe('F2C.2 — bufferQueue', () => {
  it('MODE bufferQueue = real; path tetap', () => {
    expect(MODE['bufferQueue']).toBe('real');
    expect(BUFFER_QUEUE_PATH).toBe('/production/buffer-queue/');
  });

  it('readBufferQueueSummary memberi baris per WC + from_wc/to_wc null apa adanya', () => {
    const parsed = readBufferQueueSummary(LIVE_BODY);

    expect(parsed?.rows).toHaveLength(1);
    expect(parsed?.rows[0]?.queue_depth).toBe(2);
    expect(parsed?.rows[0]?.avg_wait_min).toBe(45);
    expect(parsed?.rows[0]?.bundles[0]?.from_wc).toBeNull();
    expect(parsed?.rows[0]?.bundles[1]?.to_wc).toBeNull();
    expect(parsed?.generated_at).toBe('2026-10-02T10:00:00Z');
  });

  it('rows bukan array → null; fetch jalan + path', async () => {
    expect(readBufferQueueSummary({ rows: 'x' })).toBeNull();

    const { client, paths } = stubClient(LIVE_BODY);

    await fetchBufferQueue(client);

    expect(paths).toEqual(['/production/buffer-queue/']);
  });
});
