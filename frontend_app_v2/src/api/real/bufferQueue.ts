// REAL - antrean buffer per work center (F2C.2). Endpoint: GET /api/v1/production/buffer-queue/
//
// Backend `monitoring.BufferQueueView` (B2 + G2). Non-ListPage: `{rows, generated_at}`.
import type { ApiClient } from '@/integrations/api-client';
import { unwrap } from '../client';

/** Path relatif terhadap `VITE_API_BASE_URL`. */
export const BUFFER_QUEUE_PATH = '/production/buffer-queue/';

export interface BufferQueueBundle {
  code: string;
  qty: number;
  waited_min: number;
  state: string;
  /** WC step sebelumnya (bisa `null` di step pertama). */
  from_wc: string | null;
  /** WC step berikutnya (bisa `null` di WC terminal). */
  to_wc: string | null;
  /** State bundle saat ini (DRAFT|CUTTING|SEWING|QC|DONE). */
  status: string;
}

export interface BufferQueueWcRow {
  wc_code: string;
  wc_name: string;
  queue_depth: number;
  avg_wait_min: number;
  bundles: BufferQueueBundle[];
}

export interface BufferQueueSummary {
  rows: BufferQueueWcRow[];
  generated_at: string;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function readNum(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0;
}

function readStr(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

function readNullableStr(value: unknown): string | null {
  return typeof value === 'string' ? value : null;
}

function readBundles(value: unknown): BufferQueueBundle[] {
  if (!Array.isArray(value)) return [];
  return value
    .filter(isRecord)
    .map((row) => ({
      code: readStr(row['code']),
      qty: readNum(row['qty']),
      waited_min: readNum(row['waited_min']),
      state: readStr(row['state']),
      from_wc: readNullableStr(row['from_wc']),
      to_wc: readNullableStr(row['to_wc']),
      status: readStr(row['status']),
    }));
}

/** PURE — respons mentah → `BufferQueueSummary`; `null` kalau `rows` bukan array. */
export function readBufferQueueSummary(raw: unknown): BufferQueueSummary | null {
  if (!isRecord(raw)) return null;

  const rows = raw['rows'];
  if (!Array.isArray(rows)) return null;

  const parsed: BufferQueueWcRow[] = [];
  for (const row of rows) {
    if (!isRecord(row)) continue;
    parsed.push({
      wc_code: readStr(row['wc_code']),
      wc_name: readStr(row['wc_name']),
      queue_depth: readNum(row['queue_depth']),
      avg_wait_min: readNum(row['avg_wait_min']),
      bundles: readBundles(row['bundles']),
    });
  }

  return { rows: parsed, generated_at: readStr(raw['generated_at']) };
}

/** Baca antrean buffer. Gagal HTTP → melempar (`unwrap`). */
export async function fetchBufferQueue(client: ApiClient): Promise<BufferQueueSummary> {
  const res = await client.get<unknown>(BUFFER_QUEUE_PATH);
  const parsed = readBufferQueueSummary(unwrap(res));

  if (parsed === null) {
    throw new Error('Bentuk respons antrean buffer tidak dikenali.');
  }

  return parsed;
}
