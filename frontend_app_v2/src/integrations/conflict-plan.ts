import type { ApiConflictCurrent } from './api-client';
import type { EnqueueInput, OfflineAction } from './offline-queue';
import type { ConflictChoice } from '@/components/ConflictResolver';

/**
 * conflict-plan.ts — peta keputusan `ConflictResolver` → rencana aksi (Fase D.4).
 *
 * Murni & tanpa React supaya bisa diuji langsung: komponen `ConflictResolver` hanya
 * melaporkan pilihan operator, dan hook/`App` yang mengeksekusi rencana ini.
 *
 * Kontrak §8.2: `server_wins` = server lebih benar (buang aksi lokal, muat ulang);
 * `last_write_wins`/`retry_force` = operator melihat fisik (timpa, pakai `X-Force`);
 * `cancel` = biarkan aksi tetap di queue (status `conflict`) sampai operator siap.
 *
 * F1 (D3): body 409 backend v4.3 mengirim `current` di **TOP-LEVEL** *dan* alias
 * `conflict.current` (kontrak §4.4). `readConflictCurrent` membaca top-level dulu, alias
 * hanya fallback — dipakai `integrations/api-client.ts` saat membangun `ApiResponse.conflict`
 * (jalur yang sama dipakai offline queue & `ConflictResolver`).
 */

export type ConflictResolution =
  | { kind: 'refetch' }
  | { kind: 'retry_force'; input: EnqueueInput }
  | { kind: 'keep_queued' };

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/** PURE — satu blok `current` → `ApiConflictCurrent`; `undefined` kalau tidak lengkap. */
function toConflictCurrent(value: unknown): ApiConflictCurrent | undefined {
  if (!isRecord(value)) return undefined;

  const version = value['version'];
  const state = value['state'];
  if (typeof version !== 'string' || typeof state !== 'string') return undefined;

  const current: ApiConflictCurrent = { version, state };
  const workCenter = value['current_work_center'];
  if (typeof workCenter === 'string') current.current_work_center = workCenter;

  return current;
}

/**
 * PURE — D3: baca `current` dari body 409.
 *
 * Urutan: `body.current` (**top-level**, kontrak v4.3) → `body.conflict.current` (alias lama).
 * Objek tanpa `version`/`state` string diabaikan (frontend tidak menebak).
 */
export function readConflictCurrent(body: unknown): ApiConflictCurrent | undefined {
  if (!isRecord(body)) return undefined;

  const topLevel = toConflictCurrent(body['current']);
  if (topLevel !== undefined) return topLevel;

  const alias = body['conflict'];
  if (!isRecord(alias)) return undefined;

  return toConflictCurrent(alias['current']);
}

/**
 * PURE — input enqueue untuk mencoba ulang dengan paksa (`last_write_wins`).
 *
 * `base_version` diisi version server terbaru dari 409: kita **menerima** kenyataan server
 * lalu menimpanya (policy `last_write_wins` — backend melewati cek konflik, lihat Fase C).
 */
export function buildForcedInput(
  action: OfflineAction,
  current?: ApiConflictCurrent
): EnqueueInput {
  return {
    path: action.path,
    method: action.method,
    body: action.body,
    resource: action.resource,
    resourceId: action.resourceId,
    base_version: current?.version ?? action.base_version,
    conflict_policy: 'last_write_wins',
    ...(action.expected_result === undefined ? {} : { expected_result: action.expected_result }),
  };
}

/** PURE — pilihan operator di `ConflictResolver` → rencana yang dieksekusi `App`. */
export function planConflictResolution(
  choice: ConflictChoice,
  action: OfflineAction,
  current?: ApiConflictCurrent
): ConflictResolution {
  if (choice === 'server_wins') return { kind: 'refetch' };
  if (choice === 'cancel') return { kind: 'keep_queued' };

  return { kind: 'retry_force', input: buildForcedInput(action, current) };
}
