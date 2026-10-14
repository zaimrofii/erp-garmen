// REAL - master Routing DAG (H1.9). Endpoint = **B22 yang di-extend di tempat**:
//   GET    `/settings/routing/`                      (list B22, shape F3A)
//   GET    `/settings/routing/<id>/`                 (detail + field H1.9)
//   POST   `/settings/routing/`                      (create, body B22: steps[])
//   PUT    `/settings/routing/<id>/`                 (ubah header)
//   DELETE `/settings/routing/<id>/`                 (soft delete, guard rule aktif)
//   POST   `/settings/routing/<id>/steps/`           (tambah step/node DAG)
//   PUT    `/settings/routing/<id>/steps/<step_id>/` (ubah step + edge)
//   DELETE `/settings/routing/<id>/steps/<step_id>/` (hapus step — structural)
//
// Tidak ada endpoint paralel `/master/routings/` (keputusan H1.9): halaman master
// memakai jalur yang sama dengan editor DAG Settings (B22) sehingga tidak ada dua
// sumber kebenaran. `src/api/real/settingsRouting.ts` (F3A) TIDAK diubah — di sini
// hanya diimpor untuk pembaca bentuk list yang sudah dipin 16 test F3A.
//
// Catatan: `ApiClient` hanya punya `get`/`post` — PUT/DELETE lewat `client.request()`.
import type { ApiClient, ApiResponse } from '@/integrations/api-client';
import type {
  MasterRoutingCreateInput,
  MasterRoutingDetail,
  MasterRoutingInput,
  MasterRoutingRow,
  MasterRoutingSaved,
  MasterRoutingStepInput,
  MasterRoutingStepRow,
} from '@/types/master-routing';
import { unwrap } from '../client';
import { readRoutingPage, readRoutingRow, SETTINGS_ROUTING_PATH } from './settingsRouting';
import {
  buildQueryPath,
  getParsed,
  isRecord,
  readBool,
  readNum,
  readStr,
  type ListPage,
} from './_shape';

/** Path relatif terhadap `VITE_API_BASE_URL` (`…/api/v1`) — sama dengan B22. */
export const MASTER_ROUTINGS_PATH = SETTINGS_ROUTING_PATH;

/** Batas paging backend B22 (`settings/views.py::DEFAULT_LIMIT` / `MAX_LIMIT`). */
export const ROUTINGS_LIMIT_DEFAULT = 50;
export const ROUTINGS_LIMIT_MAX = 200;

export type MasterRoutingPage = ListPage<MasterRoutingRow>;

export interface MasterRoutingsParams {
  limit?: number | null;
  cursor?: number | null;
}

/** URL detail routing. */
export function routingDetailPath(id: number): string {
  return `${MASTER_ROUTINGS_PATH}${id}/`;
}

/** URL koleksi step routing. */
export function routingStepsPath(id: number): string {
  return `${routingDetailPath(id)}steps/`;
}

/** URL satu step routing. */
export function routingStepPath(id: number, stepId: number): string {
  return `${routingStepsPath(id)}${stepId}/`;
}

/** PURE — path + query `GET /settings/routing/` (hanya param terisi dikirim). */
export function buildMasterRoutingsPath(params: MasterRoutingsParams = {}): string {
  return buildQueryPath(MASTER_ROUTINGS_PATH, {
    limit: params.limit,
    cursor: params.cursor,
  });
}

/** PURE — hapus key `undefined` supaya backend melihat "field tidak dikirim". */
export function stripUndefined<T extends Record<string, unknown>>(raw: T): Record<string, unknown> {
  return Object.fromEntries(Object.entries(raw).filter(([, value]) => value !== undefined));
}

function readTags(raw: unknown): string[] {
  if (!Array.isArray(raw)) return [];
  return raw.filter((item): item is string => typeof item === 'string');
}

function readNodes(raw: unknown) {
  if (!Array.isArray(raw)) return [];
  return raw.filter(isRecord).map((row) => ({
    id: readNum(row['id']),
    label: readStr(row['label']),
    step_no: readNum(row['step_no']),
  }));
}

function readEdges(raw: unknown) {
  if (!Array.isArray(raw)) return [];
  return raw.filter(isRecord).map((row) => ({
    from: readNum(row['from']),
    to: readNum(row['to']),
    overlap_pct: readNum(row['overlap_pct']),
    is_rework: readBool(row['is_rework']),
  }));
}

/** PURE — satu baris list B22 (bentuk F3A, TIDAK diubah). */
export function readMasterRoutingRow(raw: unknown): MasterRoutingRow | null {
  return readRoutingRow(raw);
}

/** PURE — respons ListPage B22. */
export function readMasterRoutingPage(raw: unknown): MasterRoutingPage | null {
  return readRoutingPage(raw);
}

/** PURE — detail routing (baris B22 + field H1.9). */
export function readMasterRoutingDetail(raw: unknown): MasterRoutingDetail | null {
  const row = readRoutingRow(raw);
  if (row === null || !isRecord(raw)) return null;

  return {
    ...row,
    capability_tags: readTags(raw['capability_tags']),
    steps_count: readNum(raw['steps_count']),
    nodes: readNodes(raw['nodes']),
    edges: readEdges(raw['edges']),
    created_at: readStr(raw['created_at']),
    updated_at: readStr(raw['updated_at']),
  };
}

/** PURE — respons tulis (PUT/DELETE header, POST/PUT/DELETE step) = detail. */
export function readMasterRoutingSaved(raw: unknown): MasterRoutingSaved | null {
  return readMasterRoutingDetail(raw);
}

/** PURE — body `PUT /settings/routing/<id>/` (hanya field yang diisi). */
export function toMasterRoutingBody(input: MasterRoutingInput): Record<string, unknown> {
  return stripUndefined({
    name: input.name,
    code: input.code,
    description: input.description,
    capability_tags: input.capability_tags,
    active: input.active,
  });
}

/** PURE — body `POST /settings/routing/` (bentuk B22: `steps[]` dengan `step_no`). */
export function toMasterRoutingCreateBody(
  input: MasterRoutingCreateInput,
): Record<string, unknown> {
  return stripUndefined({
    name: input.name,
    description: input.description,
    steps: input.steps,
  });
}

/** PURE — body step endpoint H1.9 (hanya field yang diisi; list kosong = kosongkan). */
export function toMasterRoutingStepBody(
  input: MasterRoutingStepInput,
): Record<string, unknown> {
  return stripUndefined({
    label: input.label,
    order: input.order,
    code: input.code,
    work_center_id: input.work_center_id,
    depends_on_step_ids: input.depends_on_step_ids,
    next_step_ids: input.next_step_ids,
    rework_target_step_id: input.rework_target_step_id,
  });
}

/** PURE — step backend (dipakai test & pemetaan form). */
export function readMasterRoutingStepRow(raw: unknown): MasterRoutingStepRow | null {
  const row = readRoutingRow({ steps: [raw] });
  if (row === null) return null;
  return row.steps[0] ?? null;
}

/* -------------------------------------------------------------------- HTTP */

function readSaved(response: ApiResponse<unknown>): MasterRoutingSaved {
  const detail = readMasterRoutingSaved(unwrap(response));
  if (detail === null) {
    throw new Error('Bentuk respons simpan routing tidak dikenali.');
  }
  return detail;
}

/** List routing (bentuk B22). Gagal HTTP → melempar. */
export async function fetchMasterRoutings(
  client: ApiClient,
  params: MasterRoutingsParams = {},
): Promise<MasterRoutingPage> {
  return getParsed(
    client,
    buildMasterRoutingsPath(params),
    readMasterRoutingPage,
    'master routing',
  );
}

/** Detail routing (dengan `nodes[]`/`edges[]` DAG). Gagal HTTP → melempar. */
export async function fetchMasterRouting(
  client: ApiClient,
  id: number,
): Promise<MasterRoutingDetail> {
  return getParsed(
    client,
    routingDetailPath(id),
    readMasterRoutingDetail,
    `master routing #${id}`,
  );
}

/** Buat routing baru (POST B22 — `steps[]` ikut terkirim). */
export async function createMasterRouting(
  client: ApiClient,
  input: MasterRoutingCreateInput,
): Promise<MasterRoutingSaved> {
  return readSaved(
    await client.post<unknown>(MASTER_ROUTINGS_PATH, toMasterRoutingCreateBody(input)),
  );
}

/** Ubah header routing (PUT) — hanya field yang diisi. */
export async function updateMasterRouting(
  client: ApiClient,
  id: number,
  input: MasterRoutingInput,
): Promise<MasterRoutingSaved> {
  return readSaved(
    await client.request<unknown>(routingDetailPath(id), {
      method: 'PUT',
      body: toMasterRoutingBody(input),
    }),
  );
}

/** Soft delete routing (DELETE) — detail dengan `is_active=false`. */
export async function deleteMasterRouting(
  client: ApiClient,
  id: number,
): Promise<MasterRoutingSaved> {
  return readSaved(
    await client.request<unknown>(routingDetailPath(id), { method: 'DELETE' }),
  );
}

/** Tambah step (node DAG) ke routing → detail terbaru. */
export async function createRoutingStep(
  client: ApiClient,
  id: number,
  input: MasterRoutingStepInput,
): Promise<MasterRoutingSaved> {
  return readSaved(
    await client.post<unknown>(routingStepsPath(id), toMasterRoutingStepBody(input)),
  );
}

/** Ubah step (label/order/WC/edge) → detail terbaru. */
export async function updateRoutingStep(
  client: ApiClient,
  id: number,
  stepId: number,
  input: MasterRoutingStepInput,
): Promise<MasterRoutingSaved> {
  return readSaved(
    await client.request<unknown>(routingStepPath(id, stepId), {
      method: 'PUT',
      body: toMasterRoutingStepBody(input),
    }),
  );
}

/** Hapus step (structural) → detail terbaru. */
export async function deleteRoutingStep(
  client: ApiClient,
  id: number,
  stepId: number,
): Promise<MasterRoutingSaved> {
  return readSaved(
    await client.request<unknown>(routingStepPath(id, stepId), { method: 'DELETE' }),
  );
}


