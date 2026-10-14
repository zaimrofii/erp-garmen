// Helper PURE bersama untuk adapter real F3A.CLOSE (parsing defensif + ListPage + query).
//
// Dipakai `real/qcAql.ts`, `real/reports*.ts`, `real/settings*.ts` supaya bentuk
// parsing/`ListPage` konsisten dan tidak diduplikasi 10x.
import type { ApiClient } from '@/integrations/api-client';
import { unwrap } from '../client';

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

export function readNum(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0;
}

export function readNullableNum(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

export function readStr(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

export function readNullableStr(value: unknown): string | null {
  return typeof value === 'string' ? value : null;
}

export function readBool(value: unknown): boolean {
  return value === true;
}

/** Amplop ListPage backend (`has_more`, bukan `has_next`). */
export interface ListPage<T> {
  rows: T[];
  total_count: number;
  has_more: boolean;
  next_cursor: number | null;
}

/** PURE — respons mentah → `ListPage<T>`; `null` kalau `rows` bukan array. */
export function readListPage<T>(
  raw: unknown,
  readRow: (row: unknown) => T | null,
): ListPage<T> | null {
  if (!isRecord(raw)) return null;
  const rows = raw['rows'];
  if (!Array.isArray(rows)) return null;

  const parsed: T[] = [];
  for (const row of rows) {
    const item = readRow(row);
    if (item !== null) parsed.push(item);
  }

  return {
    rows: parsed,
    total_count: readNum(raw['total_count']),
    has_more: raw['has_more'] === true,
    next_cursor: typeof raw['next_cursor'] === 'number' ? raw['next_cursor'] : null,
  };
}

/** PURE — `path` + query string dari params (nilai kosong dilewati). */
export function buildQueryPath(
  path: string,
  params: Record<string, string | number | boolean | null | undefined> = {},
): string {
  const qs = new URLSearchParams();

  for (const [key, value] of Object.entries(params)) {
    if (value === null || value === undefined || value === '') continue;
    qs.set(key, String(value));
  }

  const suffix = qs.toString();
  return suffix.length === 0 ? path : `${path}?${suffix}`;
}

/** GET + `unwrap` + parse (helper untuk adapter baru; melempar kalau bentuk rusak). */
export async function getParsed<T>(
  client: ApiClient,
  path: string,
  parse: (raw: unknown) => T | null,
  label: string,
): Promise<T> {
  const res = await client.get<unknown>(path);
  const parsed = parse(unwrap(res));

  if (parsed === null) {
    throw new Error(`Bentuk respons ${label} tidak dikenali.`);
  }

  return parsed;
}
