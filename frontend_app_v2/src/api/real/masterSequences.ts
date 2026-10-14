// REAL - Number Sequence (Sprint C). Endpoint `/api/v1/settings/sequences/…`:
//   GET  `/settings/sequences/`                     (list; ?search=&active=&year=)
//   GET  `/settings/sequences/<code>/preview/`      (nomor berikutnya, tanpa increment)
//   PUT  `/settings/sequences/<code>/`              (prefix/padding/aktif/nama; ADMIN/OWNER)
//
// Bentuk baris = PERSIS `django_app/master/sequence_services.py::sequence_row`:
// `{id, code, name, prefix, year, last_seq, padding, is_active, next_number,
// created_at, updated_at}`. **Tanpa `odoo_id`** — MES-only (probe: `ir.sequence` Odoo
// adalah counter internal dokumen Odoo sendiri, 37 record hidup).
//
// Catatan: `ApiClient` hanya punya `get`/`post` — PUT lewat `client.request()`.
import type { ApiClient } from '@/integrations/api-client';
import type {
  MasterSequenceCreateInput,
  MasterSequenceInput,
  MasterSequenceRow,
  SequencePreview,
} from '@/types/master-sequence';
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

/** Path relatif terhadap `VITE_API_BASE_URL` (`…/api/v1`). */
export const SETTINGS_SEQUENCES_PATH = '/settings/sequences/';

/** Batas paging backend (`settings/views.py::DEFAULT_LIMIT` / `MAX_LIMIT`). */
export const SEQUENCES_LIMIT_DEFAULT = 50;
export const SEQUENCES_LIMIT_MAX = 200;

export type MasterSequencePage = ListPage<MasterSequenceRow>;

export interface MasterSequencesParams {
  search?: string | null;
  active?: boolean | null;
  /** Tahun berjalan (default backend) atau `'all'` untuk semua tahun. */
  year?: number | 'all' | null;
  limit?: number | null;
  cursor?: number | null;
}

/** URL pratinjau satu sequence. */
export function sequencePreviewPath(code: string): string {
  return `${SETTINGS_SEQUENCES_PATH}${encodeURIComponent(code)}/preview/`;
}

/** URL detail/ubah satu sequence. */
export function sequenceDetailPath(code: string): string {
  return `${SETTINGS_SEQUENCES_PATH}${encodeURIComponent(code)}/`;
}

/** PURE — path `POST /settings/sequences/` (+ `?year=` kalau diminta). */
export function sequenceCreatePath(year?: number | null): string {
  return buildQueryPath(SETTINGS_SEQUENCES_PATH, { year: year ?? null });
}

/** PURE — path + query `GET /settings/sequences/` (hanya param terisi dikirim). */
export function buildMasterSequencesPath(params: MasterSequencesParams = {}): string {
  const year =
    params.year === null || params.year === undefined
      ? null
      : params.year === 'all'
        ? 'all'
        : String(params.year);

  return buildQueryPath(SETTINGS_SEQUENCES_PATH, {
    search: params.search,
    active: params.active === null || params.active === undefined ? null : params.active,
    year,
    limit: params.limit,
    cursor: params.cursor,
  });
}

/** PURE — satu baris sequence. */
export function readMasterSequenceRow(raw: unknown): MasterSequenceRow | null {
  if (!isRecord(raw)) return null;

  return {
    id: readNum(raw['id']),
    code: readStr(raw['code']),
    name: readStr(raw['name']),
    prefix: readStr(raw['prefix']),
    year: readNum(raw['year']),
    last_seq: readNum(raw['last_seq']),
    padding: readNum(raw['padding']),
    is_active: readBool(raw['is_active']),
    next_number: readStr(raw['next_number']),
    created_at: readStr(raw['created_at']),
    updated_at: readStr(raw['updated_at']),
  };
}

/** PURE — respons ListPage sequence. */
export function readMasterSequencePage(raw: unknown): MasterSequencePage | null {
  return readListPage<MasterSequenceRow>(raw, readMasterSequenceRow);
}

/** PURE — respons pratinjau (`GET …/<code>/preview/`). */
export function readSequencePreview(raw: unknown): SequencePreview | null {
  if (!isRecord(raw)) return null;

  return {
    code: readStr(raw['code']),
    name: readStr(raw['name']),
    prefix: readStr(raw['prefix']),
    year: readNum(raw['year']),
    last_seq: readNum(raw['last_seq']),
    padding: readNum(raw['padding']),
    is_active: readBool(raw['is_active']),
    next_number: readStr(raw['next_number']),
  };
}

/** PURE — body `PUT /settings/sequences/<code>/` (hanya field yang diisi). */
export function toMasterSequenceBody(input: MasterSequenceInput): Record<string, unknown> {
  return Object.fromEntries(
    Object.entries({
      name: input.name,
      prefix: input.prefix,
      padding: input.padding,
      active: input.active,
    }).filter(([, value]) => value !== undefined),
  );
}

/** PURE — body `POST /settings/sequences/` (opsional kosong dihilangkan). */
export function toMasterSequenceCreateBody(
  input: MasterSequenceCreateInput,
): Record<string, unknown> {
  const prefix = input.prefix?.trim() ?? '';

  return Object.fromEntries(
    Object.entries({
      code: input.code.trim(),
      name: input.name.trim(),
      prefix: prefix === '' ? undefined : prefix,
      padding: input.padding,
    }).filter(([, value]) => value !== undefined),
  );
}

/** List sequence. Gagal HTTP → melempar. */
export async function fetchSequences(
  client: ApiClient,
  params: MasterSequencesParams = {},
): Promise<MasterSequencePage> {
  return getParsed(
    client,
    buildMasterSequencesPath(params),
    readMasterSequencePage,
    'number sequence',
  );
}

/** Pratinjau nomor berikutnya (tanpa increment). Gagal HTTP → melempar. */
export async function previewNumber(
  client: ApiClient,
  code: string,
): Promise<SequencePreview> {
  return getParsed(
    client,
    sequencePreviewPath(code),
    readSequencePreview,
    `pratinjau sequence ${code}`,
  );
}

/** Ubah prefix/padding/aktif/nama (PUT, ADMIN/OWNER) → baris terbaru. */
export async function updateSequence(
  client: ApiClient,
  code: string,
  input: MasterSequenceInput,
): Promise<MasterSequenceRow> {
  const row = readMasterSequenceRow(
    unwrap(
      await client.request<unknown>(sequenceDetailPath(code), {
        method: 'PUT',
        body: toMasterSequenceBody(input),
      }),
    ),
  );
  if (row === null) {
    throw new Error('Bentuk respons simpan sequence tidak dikenali.');
  }

  return row;
}

/** Buat sequence baru (POST, ADMIN/OWNER) → baris baru. Gagal HTTP → melempar. */
export async function createSequence(
  client: ApiClient,
  input: MasterSequenceCreateInput,
  year?: number | null,
): Promise<MasterSequenceRow> {
  const row = readMasterSequenceRow(
    unwrap(
      await client.post<unknown>(
        sequenceCreatePath(year),
        toMasterSequenceCreateBody(input),
      ),
    ),
  );
  if (row === null) {
    throw new Error('Bentuk respons buat sequence tidak dikenali.');
  }

  return row;
}

/**
 * Nonaktifkan (soft delete) sequence (DELETE, ADMIN/OWNER) → **204 tanpa body**.
 *
 * Tidak memakai `unwrap()`: `unwrap` mensyaratkan `data !== undefined`, sedangkan
 * 204 tidak punya body (`data === undefined`). Cukup cek `ok` dan teruskan pesan
 * backend (`{"detail": …}`) saat gagal (mis. 400 guard protected seed/`last_seq>0`).
 */
export async function deleteSequence(client: ApiClient, code: string): Promise<void> {
  const res = await client.request<unknown>(sequenceDetailPath(code), { method: 'DELETE' });

  if (!res.ok) {
    throw new Error(
      res.error?.message ?? `Gagal menonaktifkan sequence ${code} (status ${res.status}).`,
    );
  }
}
