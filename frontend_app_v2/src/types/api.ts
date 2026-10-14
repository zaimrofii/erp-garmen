export type {
  ApiResponse,
  ApiErrorPayload,
  ApiConflictCurrent,
  RequestOptions,
} from '@/integrations/api-client';

export type { ListPage, ListRow, ListMeta } from '@/lib/schemas/list.schema';

export type { ChatterPage, ChatterEvent, ChatterActor } from '@/lib/schemas/chatter.schema';

/**
 * Mode aksi dari metadata — **lowercase** (`'optimistic' | 'pessimistic'`, D6).
 * `TRANSITION_MODE` (`lib/transition-rules.ts`) tetap prioritas 1 atas nilai ini.
 */
export type {
  ActionMode,
  AllowedAction,
  ActionConfirm,
  ActionFormField,
} from '@/lib/schemas/action.schema';
export { ACTION_MODES, normalizeActionMode } from '@/lib/schemas/action.schema';

/** Isi `expected_result` pada respons aksi (sabuk pengaman #10 — dibandingkan queue). */
export interface ActionExpectedResult {
  state?: string;
  fields?: Record<string, unknown>;
}

/**
 * Respons 200 aksi (kontrak backend v4.3 §4.4):
 *
 * ```json
 * { "ok": true, "resource": "bundles", "id": 16, "action": "BUNDLE_START",
 *   "version": "new-sha256", "state": "CUTTING",
 *   "expected_result": { "state": "CUTTING", "fields": { "state": "CUTTING" } } }
 * ```
 *
 * **D2:** `state` ada di **TOP-LEVEL**. `expected_result.state` hanya fallback (respons
 * backend lama) — resolusi satu pintu lewat `resolveActionState()`/`readActionState()`
 * di `lib/action-runner.ts`, jangan baca `expected_result.state` langsung di komponen.
 * Field kritis diangkat backend ke top-level (mis. `qty_done`) → index signature.
 */
export interface ActionResponse {
  ok: boolean;
  resource?: string;
  id?: number | string;
  action?: string;
  version?: string;
  state: string;
  expected_result?: ActionExpectedResult;
  [field: string]: unknown;
}
