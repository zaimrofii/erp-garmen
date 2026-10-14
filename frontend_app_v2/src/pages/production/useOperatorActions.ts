import { useCallback, useState } from 'react';
import { useFeedback, useOffline } from '@/app/app-runtime';
import { submitAction } from '@/lib/action-runner';
import { resolveConflictPolicy } from '@/lib/conflict-policy';
import { generateUUID } from '@/lib/uuid';
import type { ApiConflictCurrent } from '@/integrations/api-client';
import type { FlushOutcome, OfflineAction } from '@/integrations/offline-queue';
import type { AllowedAction } from '@/lib/schemas/action.schema';

/**
 * useOperatorActions.ts - orkestrator aksi operator (MULAI / SELESAI / SCRAP / REWORK).
 *
 * PENTING - signature `submitAction` yang SEBENARNYA (lib/action-runner.ts):
 *
 *   submitAction({ queue, action: AllowedAction, resource, resourceId, baseVersion, path, body? })
 *     -> Promise<{ kind: 'succeeded' | 'conflicted' | 'failed' | 'queued_offline' | 'deferred' }>
 *
 * Jadi TIDAK seperti `submitAction({ resource, resourceId, action: 'BUNDLE_START' })`:
 *  - `queue` diambil dari `useOffline()` (satu queue untuk seluruh aplikasi);
 *  - `action` = objek `AllowedAction` dari `bundle.allowed_actions` (berisi `endpoint`);
 *  - `baseVersion` = `bundle.version` (optimistic lock) dan `path` = `action.endpoint`;
 *  - fungsi ini **tidak pernah throw** - hasilnya union, jadi pemetaan feedback ada di sini.
 *
 * RANTAI FEEDBACK (gate "setiap aksi wajib playBeep + haptic + flash"):
 *  1. ACK SENTUH - `ActionButton` (molecule Fase 15) memanggil playBeep + haptic + flash saat tap;
 *  2. HASIL AKSI - hook ini memanggil `trigger(kind)`, lalu `ActionFeedback` (mount global di
 *     `AppRuntimeProvider`) menjalankan playBeep + haptic + overlay kedip SEKALI saja.
 * Memanggil playBeep/haptic/flash langsung di sini akan membuat bunyi berbunyi 2-3x per aksi.
 */

/**
 * Aksi operator yang boleh lewat queue ini. F11 (11.3a) menambahkan `BUNDLE_QC`
 * (SEWING → QC, kontrak §4.4) supaya tombol "LULUS QC" di QCPage memakai jalur
 * offline-safe yang sama dengan REWORK/SCRAP (bukan jalur online-only).
 */
export type OperatorAction = 'BUNDLE_START' | 'BUNDLE_FINISH' | 'BUNDLE_SCRAP' | 'BUNDLE_REWORK' | 'BUNDLE_QC';

/** Resource backend untuk aksi bundle (dipakai queue + invalidate). */
const RESOURCE = 'bundles';

export interface OperatorActionTarget {
  /** `String(bundle.id)` - backend memakai id number, queue memakai string. */
  resourceId: string;
  /** `bundle.version` untuk optimistic lock. */
  baseVersion: string;
  /** `bundle.allowed_actions` dari backend - tombol nonaktif kalau aksi tidak ada di sini. */
  allowedActions: AllowedAction[];
}

export interface OperatorActionConflict {
  /** OfflineAction minimal (pola sama seperti Fase 6/7) untuk `ConflictResolver`. */
  action: OfflineAction;
  current: ApiConflictCurrent;
}

export interface OperatorActionsResult {
  run: (action: OperatorAction, payload?: Record<string, unknown>) => Promise<boolean>;
  pending: OperatorAction | null;
  error: string | null;
  notice: string | null;
  flash: 'success' | 'error' | null;
  conflict: OperatorActionConflict | null;
  clearConflict: () => void;
  isOnline: boolean;
  pendingCount: number;
}

/** Susun payload minimal untuk `ConflictResolver` dari hasil flush 409. */
function buildConflict(
  allowed: AllowedAction,
  target: Pick<OperatorActionTarget, 'resourceId' | 'baseVersion'>,
  body: Record<string, unknown>,
  outcome: FlushOutcome,
): OperatorActionConflict | null {
  if (outcome.current === undefined) return null;

  const action: OfflineAction = {
    id: outcome.id,
    path: allowed.endpoint ?? outcome.path,
    method: 'POST',
    body,
    resource: RESOURCE,
    resourceId: target.resourceId,
    ts: Date.now(),
    base_version: target.baseVersion,
    conflict_policy: resolveConflictPolicy(allowed.id),
    status: 'conflict',
    idempotency_key: generateUUID(),
  };

  return { action, current: outcome.current };
}

export function useOperatorActions(target: OperatorActionTarget): OperatorActionsResult {
  const { queue, isOnline, pendingCount } = useOffline();
  const { trigger } = useFeedback();

  const [pending, setPending] = useState<OperatorAction | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [flash, setFlash] = useState<'success' | 'error' | null>(null);
  const [conflict, setConflict] = useState<OperatorActionConflict | null>(null);

  const clearConflict = useCallback((): void => {
    setConflict(null);
  }, []);

  const { resourceId, baseVersion, allowedActions } = target;

  const run = useCallback(
    async (actionId: OperatorAction, payload?: Record<string, unknown>): Promise<boolean> => {
      const allowed = allowedActions.find((candidate) => candidate.id === actionId);

      if (allowed === undefined || allowed.endpoint === undefined) {
        setError(`Aksi ${actionId} tidak tersedia untuk bundle ini.`);
        setNotice(null);
        setFlash('error');
        trigger('error');

        return false;
      }

      setPending(actionId);
      setError(null);
      setNotice(null);

      const body: Record<string, unknown> = { ...(payload ?? {}) };

      try {
        const result = await submitAction({
          queue,
          action: allowed,
          resource: RESOURCE,
          resourceId,
          baseVersion,
          path: allowed.endpoint,
          body,
        });

        if (result.kind === 'succeeded' || result.kind === 'queued_offline') {
          if (result.kind === 'queued_offline') {
            setNotice('Offline - aksi tersimpan di antrean dan akan dikirim otomatis.');
          }
          setFlash('success');
          trigger('success');

          return true;
        }

        if (result.kind === 'deferred') {
          setNotice('Masih menunggu aksi lain di antrean selesai.');
          trigger('warning');

          return false;
        }

        if (result.kind === 'conflicted') {
          setConflict(buildConflict(allowed, { resourceId, baseVersion }, body, result.outcome));
          setError('Data berubah di server - periksa konflik.');
          setFlash('error');
          trigger('error');

          return false;
        }

        setError(result.outcome.reason ?? `Aksi gagal (status ${result.outcome.status}).`);
        setFlash('error');
        trigger('error');

        return false;
      } catch (caught) {
        // Sabuk pengaman: `submitAction` tidak melempar, tapi IndexedDB bisa.
        setError(caught instanceof Error ? caught.message : 'Aksi gagal dikirim.');
        setFlash('error');
        trigger('error');

        return false;
      } finally {
        setPending(null);
      }
    },
    [allowedActions, baseVersion, queue, resourceId, trigger],
  );

  return { run, pending, error, notice, flash, conflict, clearConflict, isOnline, pendingCount };
}
