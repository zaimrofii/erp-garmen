// REAL - settings line allocation (F3A.CLOSE flip / backend B25).
// GET + POST /api/v1/settings/line-allocation/ (model `LineAllocationRule`).
import type { ApiClient } from '@/integrations/api-client';
import { unwrap } from '../client';
import {
  buildQueryPath,
  getParsed,
  isRecord,
  readBool,
  readListPage,
  readNullableNum,
  readNum,
  readStr,
  type ListPage,
} from './_shape';

export const SETTINGS_LINE_ALLOCATION_PATH = '/settings/line-allocation/';

export interface LineAllocationRow {
  id: number;
  name: string;
  wc_type: string;
  line_id: number;
  line_code: string | null;
  priority: number;
  is_active: boolean;
  config: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface LineAllocationInput {
  name: string;
  wc_type: string;
  line_id: number;
  priority?: number;
  config?: Record<string, unknown>;
}

/** PURE — satu rule mentah → `LineAllocationRow`. */
export function readLineAllocationRow(raw: unknown): LineAllocationRow | null {
  if (!isRecord(raw)) return null;
  return {
    id: readNum(raw['id']),
    name: readStr(raw['name']),
    wc_type: readStr(raw['wc_type']),
    line_id: readNullableNum(raw['line_id']) ?? 0,
    line_code: typeof raw['line_code'] === 'string' ? raw['line_code'] : null,
    priority: readNum(raw['priority']),
    is_active: readBool(raw['is_active']),
    config: isRecord(raw['config']) ? raw['config'] : {},
    created_at: readStr(raw['created_at']),
    updated_at: readStr(raw['updated_at']),
  };
}

/** PURE — respons ListPage line-allocation. */
export function readLineAllocationPage(
  raw: unknown,
): ListPage<LineAllocationRow> | null {
  return readListPage<LineAllocationRow>(raw, readLineAllocationRow);
}

/** PURE — path + `?wc_type=&limit=&cursor=`. */
export function buildSettingsLineAllocationPath(
  params: { wcType?: string | null; limit?: number | null; cursor?: number | null } = {},
): string {
  return buildQueryPath(SETTINGS_LINE_ALLOCATION_PATH, {
    wc_type: params.wcType,
    limit: params.limit,
    cursor: params.cursor,
  });
}

/** List aturan alokasi (filter opsional `wc_type`). Gagal HTTP → melempar. */
export async function fetchLineAllocations(
  client: ApiClient,
  params: { wcType?: string | null; limit?: number | null; cursor?: number | null } = {},
): Promise<ListPage<LineAllocationRow>> {
  return getParsed(
    client,
    buildSettingsLineAllocationPath(params),
    readLineAllocationPage,
    'aturan alokasi lini',
  );
}

/** Buat aturan alokasi baru (POST). Gagal HTTP → melempar. */
export async function createLineAllocation(
  client: ApiClient,
  input: LineAllocationInput,
): Promise<LineAllocationRow> {
  const res = await client.post<unknown>(SETTINGS_LINE_ALLOCATION_PATH, {
    name: input.name,
    wc_type: input.wc_type,
    line_id: input.line_id,
    priority: input.priority ?? 0,
    config: input.config ?? {},
  });
  const row = readLineAllocationRow(unwrap(res));

  if (row === null) {
    throw new Error('Bentuk respons simpan aturan alokasi tidak dikenali.');
  }

  return row;
}
