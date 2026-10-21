/**
 * api/real/kanban.ts - helper bersama endpoint kanban (FASE K2) untuk bundles & work-orders.
 *
 * Dipakai `real/bundlesKanban.ts` + `real/workOrdersKanban.ts`: keduanya hanya berbeda
 * PATH; bentuk response sengaja KONSISTEN di backend (kontrak K2), jadi parser pun satu
 * tempat - mustahil bentuk bundle dan WO berbeda di frontend.
 *
 * Fetch tetap lewat `integrations/api-client.ts` (satu-satunya pintu HTTP).
 */

import type { ApiClient } from '@/integrations/api-client';
import type {
  KanbanAction,
  KanbanCardData,
  KanbanColumn,
  KanbanFilters,
  KanbanQuery,
  KanbanResponse,
  KanbanTransition,
} from '@/types/kanban';
import { unwrap } from '../client';

/** Batas kartu per kolom (selaras backend: default 50, maks 200). */
export const KANBAN_LIMIT_DEFAULT = 50;
export const KANBAN_LIMIT_MAX = 200;

function text(raw: unknown, fallback = ''): string {
  return typeof raw === 'string' ? raw : fallback;
}

function num(raw: unknown, fallback = 0): number {
  return typeof raw === 'number' && Number.isFinite(raw) ? raw : fallback;
}

function bool(raw: unknown): boolean {
  return raw === true;
}

function property(raw: unknown, key: string): unknown {
  if (typeof raw !== 'object' || raw === null) return undefined;

  return new Map(Object.entries(raw)).get(key);
}

/** PURE - query param kanban yang terisi saja (angka dikirim sebagai string). */
export function buildKanbanPath(basePath: string, params: KanbanQuery = {}): string {
  const qs = new URLSearchParams();

  if (params.search != null && params.search.trim().length > 0) qs.set('search', params.search.trim());
  if (params.state != null && params.state.trim().length > 0) qs.set('state', params.state.trim());
  if (params.work_center_id != null) qs.set('work_center_id', String(params.work_center_id));
  if (params.line_id != null) qs.set('line_id', String(params.line_id));
  if (params.work_order_id != null) qs.set('work_order_id', String(params.work_order_id));
  if (params.limit != null) qs.set('limit', String(params.limit));

  const suffix = qs.toString();
  return suffix.length === 0 ? basePath : `${basePath}?${suffix}`;
}

/** PURE - satu aksi kartu (`allowed_actions[]`). */
export function readKanbanAction(raw: unknown): KanbanAction | null {
  const id = property(raw, 'id');
  if (typeof id !== 'string' || id.length === 0) return null;

  const mode = property(raw, 'mode');
  const endpoint = property(raw, 'endpoint');

  return {
    id,
    label: text(property(raw, 'label'), id),
    ...(typeof mode === 'string' ? { mode } : {}),
    ...(typeof endpoint === 'string' ? { endpoint } : {}),
  };
}

/** PURE - satu kartu kanban `{id, code, work_order_code, size, qty, state, allowed_actions}`. */
export function readKanbanCard(raw: unknown): KanbanCardData | null {
  const id = property(raw, 'id');
  if (typeof id !== 'number') return null;

  const actions = property(raw, 'allowed_actions');
  const size = property(raw, 'size');
  const workOrderCode = property(raw, 'work_order_code');

  return {
    id,
    code: text(property(raw, 'code'), String(id)),
    work_order_code: typeof workOrderCode === 'string' ? workOrderCode : null,
    size: typeof size === 'string' ? size : null,
    qty: num(property(raw, 'qty')),
    state: text(property(raw, 'state')),
    allowed_actions: Array.isArray(actions)
      ? actions.map(readKanbanAction).filter((action): action is KanbanAction => action !== null)
      : [],
  };
}

/** PURE - satu kolom kanban (state + count + kartu). */
export function readKanbanColumn(raw: unknown): KanbanColumn | null {
  const state = property(raw, 'state');
  if (typeof state !== 'string' || state.length === 0) return null;

  const cards = property(raw, 'cards');

  return {
    state,
    label: text(property(raw, 'label'), state),
    order: num(property(raw, 'order')),
    count: num(property(raw, 'count')),
    cards: Array.isArray(cards)
      ? cards.map(readKanbanCard).filter((card): card is KanbanCardData => card !== null)
      : [],
    truncated: bool(property(raw, 'truncated')),
  };
}

/** PURE - satu transisi mesin (sumber validasi drag & drop di frontend). */
export function readKanbanTransition(raw: unknown): KanbanTransition | null {
  const from = property(raw, 'from');
  const to = property(raw, 'to');
  const actionId = property(raw, 'action_id');
  if (typeof from !== 'string' || typeof to !== 'string' || typeof actionId !== 'string') {
    return null;
  }

  return { from, to, action_id: actionId, label: text(property(raw, 'label'), actionId) };
}

/** PURE - blok `filters` (`applied` + `ignored`); selalu berbentuk dict supaya aman. */
export function readKanbanFilters(raw: unknown): KanbanFilters {
  const applied = property(raw, 'applied');
  const ignored = property(raw, 'ignored');
  const entries = typeof applied === 'object' && applied !== null ? Object.entries(applied) : [];
  const appliedEntries = entries.filter(
    (entry): entry is [string, string | number] =>
      typeof entry[1] === 'string' || typeof entry[1] === 'number',
  );

  return {
    applied: Object.fromEntries(appliedEntries),
    ignored: Array.isArray(ignored) ? ignored.filter((item) => typeof item === 'string') : [],
  };
}

/** PURE - response kanban penuh; `null` kalau bentuknya tidak dikenali. */
export function readKanbanResponse(raw: unknown): KanbanResponse | null {
  const columns = property(raw, 'columns');
  if (!Array.isArray(columns)) return null;

  const transitions = property(raw, 'transitions');
  const unknownStates = property(raw, 'unknown_states');
  const unknownEntries =
    typeof unknownStates === 'object' && unknownStates !== null
      ? Object.entries(unknownStates).filter(
          (entry): entry is [string, number] => typeof entry[1] === 'number',
        )
      : [];

  return {
    resource: text(property(raw, 'resource')),
    industry: text(property(raw, 'industry')),
    machine: text(property(raw, 'machine')),
    columns: columns
      .map(readKanbanColumn)
      .filter((column): column is KanbanColumn => column !== null),
    transitions: Array.isArray(transitions)
      ? transitions
          .map(readKanbanTransition)
          .filter((transition): transition is KanbanTransition => transition !== null)
      : [],
    total_count: num(property(raw, 'total_count')),
    limit: num(property(raw, 'limit'), KANBAN_LIMIT_DEFAULT),
    truncated: bool(property(raw, 'truncated')),
    unknown_states: Object.fromEntries(unknownEntries),
    filters: readKanbanFilters(property(raw, 'filters')),
  };
}

/** GET papan kanban satu resource; lempar Error kalau request/bentuk data gagal. */
export async function fetchKanban(
  client: ApiClient,
  basePath: string,
  params: KanbanQuery = {},
): Promise<KanbanResponse> {
  const raw = unwrap(await client.get<unknown>(buildKanbanPath(basePath, params)));
  const parsed = readKanbanResponse(raw);
  if (parsed === null) throw new Error('Bentuk respons kanban tidak dikenali.');

  return parsed;
}
