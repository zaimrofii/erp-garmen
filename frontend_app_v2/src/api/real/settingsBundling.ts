// REAL - settings bundling (F3A.CLOSE flip / backend B24). GET + POST /api/v1/settings/bundling/
// Model backend: `BundlingRule{name, size_matrix, bundle_size_default, is_active}`.
import type { ApiClient } from '@/integrations/api-client';
import { unwrap } from '../client';
import {
  buildQueryPath,
  getParsed,
  isRecord,
  readBool,
  readListPage,
  readNum,
  readStr,
  type ListPage,
} from './_shape';

export const SETTINGS_BUNDLING_PATH = '/settings/bundling/';

export interface BundlingRuleRow {
  id: number;
  name: string;
  size_matrix: Record<string, number>;
  bundle_size_default: number;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface BundlingRuleInput {
  name: string;
  size_matrix?: Record<string, number>;
  bundle_size_default?: number;
}

function readSizeMatrix(value: unknown): Record<string, number> {
  if (!isRecord(value)) return {};
  const out: Record<string, number> = {};
  for (const [key, raw] of Object.entries(value)) out[key] = readNum(raw);
  return out;
}

/** PURE — satu rule mentah → `BundlingRuleRow`. */
export function readBundlingRuleRow(raw: unknown): BundlingRuleRow | null {
  if (!isRecord(raw)) return null;
  return {
    id: readNum(raw['id']),
    name: readStr(raw['name']),
    size_matrix: readSizeMatrix(raw['size_matrix']),
    bundle_size_default: readNum(raw['bundle_size_default']),
    is_active: readBool(raw['is_active']),
    created_at: readStr(raw['created_at']),
    updated_at: readStr(raw['updated_at']),
  };
}

/** PURE — respons ListPage bundling. */
export function readBundlingRulePage(raw: unknown): ListPage<BundlingRuleRow> | null {
  return readListPage<BundlingRuleRow>(raw, readBundlingRuleRow);
}

/** PURE — path + `?limit=&cursor=`. */
export function buildSettingsBundlingPath(
  params: { limit?: number | null; cursor?: number | null } = {},
): string {
  return buildQueryPath(SETTINGS_BUNDLING_PATH, {
    limit: params.limit,
    cursor: params.cursor,
  });
}

/** List aturan bundling. Gagal HTTP → melempar. */
export async function fetchBundlingRules(
  client: ApiClient,
  params: { limit?: number | null; cursor?: number | null } = {},
): Promise<ListPage<BundlingRuleRow>> {
  return getParsed(
    client,
    buildSettingsBundlingPath(params),
    readBundlingRulePage,
    'aturan bundling',
  );
}

/** Buat aturan bundling baru (POST). Gagal HTTP → melempar. */
export async function createBundlingRule(
  client: ApiClient,
  input: BundlingRuleInput,
): Promise<BundlingRuleRow> {
  const res = await client.post<unknown>(SETTINGS_BUNDLING_PATH, {
    name: input.name,
    size_matrix: input.size_matrix ?? {},
    bundle_size_default: input.bundle_size_default ?? 0,
  });
  const row = readBundlingRuleRow(unwrap(res));

  if (row === null) {
    throw new Error('Bentuk respons simpan aturan bundling tidak dikenali.');
  }

  return row;
}
