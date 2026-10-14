import { buildRequestUrl } from '@/integrations/api-client';
import type { FlushOutcome, FlushResult, OfflineQueue } from '@/integrations/offline-queue';
import { resolveConflictPolicy } from '@/lib/conflict-policy';
import type { AllowedAction } from '@/lib/schemas/action.schema';
import type { TransitionMode } from '@/lib/transition-rules';
import type { ActionResponse } from '@/types/api';

/**
 * action-runner.ts — logika murni ActionBar (§7 optimistic/pessimistic, §8 conflict policy, §9.3 lock).
 *
 * Dipisah dari komponen supaya:
 * 1. bisa diuji **tanpa DOM** (jsdom tidak jalan di bun — catatan Fase 2), dan
 * 2. komponen ActionBar hanya mengekspor komponen (React fast-refresh bersih).
 *
 * F1 (D1 + D2) — selaras kontrak backend v4.3:
 * - D1 `endpoint` metadata **relatif** ke baseUrl (yang sudah termasuk `/api/v1`) → tidak
 *   boleh di-prefix dua kali (`resolveActionPath`, guard di `buildRequestUrl`);
 * - D2 `state` respons aksi 200 ada di **top-level**; `expected_result.state` hanya fallback
 *   (`readActionState` / `resolveActionState`).
 */

export type ActionVisualState = 'normal' | 'optimistic' | 'pending' | 'blocked' | 'offline_blocked';

export type ActionBadge = 'none' | 'offline_saved' | 'needs_connection';

export interface ActionStateResolution {
  state: ActionVisualState;
  disabled: boolean;
  badge: ActionBadge;
}

export interface ActionOutcome {
  bucket: 'succeeded' | 'failed' | 'conflicted' | 'skipped';
  outcome: FlushOutcome;
}

export function isBrowserOnline(): boolean {
  const navigatorLike = globalThis as { navigator?: { onLine?: boolean } };
  return navigatorLike.navigator?.onLine !== false;
}

/** PURE — `BUNDLE_START` + resource `bundle` → `start`. */
export function slugifyActionId(actionId: string, resource: string): string {
  const prefix = `${resource.toUpperCase()}_`;
  const withoutPrefix = actionId.startsWith(prefix) ? actionId.slice(prefix.length) : actionId;

  return withoutPrefix.toLowerCase().replace(/_/g, '-');
}

/** PURE — konvensi default kalau backend tidak mengirim `endpoint` (lihat `resolveActionPath`). */
export function defaultActionPath(actionId: string, resource: string, resourceId: string): string {
  return `/${resource}/${encodeURIComponent(resourceId)}/${slugifyActionId(actionId, resource)}/`;
}

/**
 * PURE — D1: `endpoint` aksi dari metadata → URL penuh, **tanpa prefix baseUrl dua kali**.
 *
 * Backend mengirim `endpoint: "/garmen/bundles/16/BUNDLE_START/"` yang **relatif** ke
 * `VITE_API_BASE_URL` (sudah termasuk `/api/v1`), jadi hasilnya
 * `http://localhost:8000/api/v1/garmen/bundles/16/BUNDLE_START/`.
 *
 * Guard (satu sumber kebenaran → `buildRequestUrl` di `integrations/api-client.ts`):
 * 1. endpoint absolut (`http(s)://…`) → dipakai apa adanya;
 * 2. endpoint yang sudah membawa `/api/v1` → tidak di-prefix ulang;
 * 3. sisanya → `baseUrl + endpoint`.
 */
export function resolveActionPath(baseUrl: string, endpoint: string): string {
  return buildRequestUrl(baseUrl, endpoint);
}

/**
 * PURE — D2: state dari respons aksi. `state` **TOP-LEVEL** dipakai dulu (kontrak v4.3 §4.4);
 * `expected_result.state` hanya fallback untuk respons backend lama. `null` = state tidak
 * diketahui (pemanggil tidak boleh menebak, mis. jangan tandai sukses tanpa bukti).
 */
export function readActionState(raw: unknown): string | null {
  if (typeof raw !== 'object' || raw === null || Array.isArray(raw)) return null;

  const record = raw as Record<string, unknown>;
  const topLevel = record['state'];
  if (typeof topLevel === 'string' && topLevel.length > 0) return topLevel;

  const expected = record['expected_result'];
  if (typeof expected !== 'object' || expected === null || Array.isArray(expected)) return null;

  const fallback = (expected as Record<string, unknown>)['state'];
  return typeof fallback === 'string' && fallback.length > 0 ? fallback : null;
}

/** PURE — versi bertipe dari `readActionState` untuk respons aksi yang sudah diparse. */
export function resolveActionState(response: ActionResponse | null | undefined): string | null {
  return readActionState(response ?? null);
}

/**
 * PURE — state visual + disabled + badge per tombol (inti per-resource lock & mode offline).
 *
 * Dinamai `resolveActionVisualState` sejak F1: nama `resolveActionState` dipakai untuk
 * resolver state **respons** backend (D2) supaya tidak ada dua arti berbeda.
 */
export function resolveActionVisualState(input: {
  actionId: string;
  mode: TransitionMode;
  resourceId: string;
  pendingByResource: Map<string, string>;
  online: boolean;
  queuedOfflineActionId?: string | null;
}): ActionStateResolution {
  const pendingActionId = input.pendingByResource.get(input.resourceId) ?? null;
  const queuedOffline = input.queuedOfflineActionId === input.actionId;
  const offlineBadge: ActionBadge = queuedOffline ? 'offline_saved' : 'none';

  // Ada aksi LAIN yang pending di RESOURCE INI → tombol ini blocked.
  // Resource lain tidak terpengaruh karena map di-key per `resourceId` (throughput §9.3).
  if (pendingActionId !== null && pendingActionId !== input.actionId) {
    return { state: 'blocked', disabled: true, badge: 'none' };
  }

  if (pendingActionId === input.actionId) {
    return {
      state: input.mode === 'optimistic' ? 'optimistic' : 'pending',
      disabled: true,
      badge: offlineBadge,
    };
  }

  // Offline + pessimistic → jangan kirim (butuh validasi server), tombol dimatikan.
  if (!input.online && input.mode === 'pessimistic') {
    return { state: 'offline_blocked', disabled: true, badge: 'needs_connection' };
  }

  return { state: 'normal', disabled: false, badge: offlineBadge };
}

/** PURE — cari outcome aksi tertentu di `FlushResult` (lintas bucket). */
export function findActionOutcome(result: FlushResult, actionId: string): ActionOutcome | null {
  for (const bucket of ['succeeded', 'failed', 'conflicted', 'skipped'] as const) {
    const outcome = result[bucket].find((item) => item.id === actionId);
    if (outcome !== undefined) return { bucket, outcome };
  }

  return null;
}

export interface SubmitActionInput {
  queue: OfflineQueue;
  action: AllowedAction;
  resource: string;
  resourceId: string;
  baseVersion: string;
  path: string;
  body?: Record<string, unknown>;
}

export type SubmitActionResult =
  | { kind: 'succeeded'; outcome: FlushOutcome }
  | { kind: 'conflicted'; outcome: FlushOutcome }
  | { kind: 'failed'; outcome: FlushOutcome }
  | { kind: 'queued_offline' }
  | { kind: 'deferred' };

/**
 * Kirim satu aksi lewat queue (`enqueue` + `flush`) lalu petakan hasilnya.
 * Semua aksi lewat jalur ini supaya logika 409 / `expected_result` / dependency / atomic
 * terpakai ulang — bukan diimplementasi ulang di UI.
 */
export async function submitAction(input: SubmitActionInput): Promise<SubmitActionResult> {
  const conflictPolicy = resolveConflictPolicy(input.action.id);

  const queuedId = await input.queue.enqueue({
    path: input.path,
    method: 'POST',
    body: {
      action: input.action.id,
      resource_id: input.resourceId,
      ...(input.body ?? {}),
    },
    resource: input.resource,
    resourceId: input.resourceId,
    base_version: input.baseVersion,
    conflict_policy: conflictPolicy,
  });

  const result = await input.queue.flush();

  // Offline → aksi tersimpan di queue (badge kuning "Tersimpan Offline").
  if (result.offline) return { kind: 'queued_offline' };

  const resolved = findActionOutcome(result, queuedId);

  // Tidak muncul di hasil flush (mis. dependency belum selesai) → tetap di queue.
  if (resolved === null) return { kind: 'deferred' };

  if (resolved.bucket === 'succeeded') return { kind: 'succeeded', outcome: resolved.outcome };
  if (resolved.bucket === 'conflicted') return { kind: 'conflicted', outcome: resolved.outcome };

  return { kind: 'failed', outcome: resolved.outcome };
}

/* --------------------------------------------------------------------------
   F11 — id aksi bundle + guard state (kontrak §4.4 / seed `garment.bundle`).
   -------------------------------------------------------------------------- */

/**
 * Id aksi bundle yang dipakai frontend. Segment action dikirim **APA ADANYA**
 * (`BUNDLE_SCRAP`, bukan slug `scrap`) — lihat `submitBundleAction` (kontrak §4.4).
 */
export const BUNDLE_ACTION_IDS = {
  START: 'BUNDLE_START',
  ADVANCE: 'BUNDLE_ADVANCE',
  QC: 'BUNDLE_QC',
  FINISH: 'BUNDLE_FINISH',
  SCRAP: 'BUNDLE_SCRAP',
  REWORK: 'BUNDLE_REWORK',
} as const;

export type BundleActionId = (typeof BUNDLE_ACTION_IDS)[keyof typeof BUNDLE_ACTION_IDS];

/**
 * State ASAL yang sah per aksi — SUMBER: seed state machine `garment.bundle`
 * (`apps_industry/garment/migrations/0002_seed_state_machines.py`) + docs §4.4:
 * BUNDLE_START DRAFT→CUTTING, BUNDLE_ADVANCE CUTTING→SEWING, BUNDLE_QC SEWING→QC,
 * BUNDLE_FINISH QC→DONE, BUNDLE_SCRAP {DRAFT,CUTTING,SEWING,QC}→DONE.
 *
 * `BUNDLE_REWORK` **tidak** ada di seed (bukan transisi state machine) → sengaja tidak
 * dipetakan supaya guard-nya tidak menebak; tombol rework tetap mengikuti `allowed_actions`.
 */
export const BUNDLE_ACTION_SOURCE_STATES: Record<string, readonly string[]> = {
  BUNDLE_START: ['DRAFT'],
  BUNDLE_ADVANCE: ['CUTTING'],
  BUNDLE_QC: ['SEWING'],
  BUNDLE_FINISH: ['QC'],
  BUNDLE_SCRAP: ['DRAFT', 'CUTTING', 'SEWING', 'QC'],
};

/** PURE — state asal yang sah untuk `actionId`; `undefined` = tidak dipetakan. */
export function bundleActionSourceStates(actionId: string): readonly string[] | undefined {
  return BUNDLE_ACTION_SOURCE_STATES[actionId.trim().toUpperCase()];
}

/**
 * PURE — aksi ini sah dari `state` SEKARANG menurut seed state machine.
 * Aksi tak dipetakan (mis. `BUNDLE_REWORK`) atau state kosong → `false`
 * (fail-closed: lebih baik tombol mati daripada mengirim transisi ilegal).
 */
export function canRunBundleAction(actionId: string, state: string | null | undefined): boolean {
  const states = bundleActionSourceStates(actionId);
  if (states === undefined) return false;
  if (typeof state !== 'string') return false;

  return states.includes(state.trim().toUpperCase());
}

/** PURE — aksi tersedia di metadata `allowed_actions` (sumber kebenaran utama). */
export function hasAllowedAction(allowed: readonly { id: string }[], actionId: string): boolean {
  return allowed.some((action) => action.id === actionId);
}

/**
 * PURE — boleh dijalankan? DUA syarat wajib: id ada di `allowed_actions` (metadata
 * backend) DAN state sekarang sah menurut state machine. Dipakai tombol QC/SCRAP.
 */
export function canSubmitBundleAction(
  allowed: readonly { id: string }[],
  actionId: string,
  state: string | null | undefined,
): boolean {
  return hasAllowedAction(allowed, actionId) && canRunBundleAction(actionId, state);
}
