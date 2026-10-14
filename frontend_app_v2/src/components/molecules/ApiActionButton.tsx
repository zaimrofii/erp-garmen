import { useState } from 'react';
import { Button } from '@/components/atoms/Button';
import { useApiClient } from '@/hooks/useApiClient';
import { CONFLICT_POLICY } from '@/lib/conflict-policy';
import { generateUUID } from '@/lib/uuid';
import { cn } from '@/lib/cn';
import type { AllowedAction } from '@/types/bundle';
import type { ApiConflictCurrent } from '@/integrations/api-client';
import type { OfflineAction } from '@/integrations/offline-queue';

/**
 * ApiActionButton - JEMBATAN LEGACY v2 (integration engine, Fase 6).
 *
 * Mengirim `allowed_actions` dari metadata langsung lewat `api-client` (jalur
 * online-only) dan meneruskan konflik 409 ke `ConflictResolver`. Tombol operator
 * di lantai produksi TIDAK memakai komponen ini - itu `ActionButton` (3 tombol besar).
 *
 * Dinamai `ApiActionButton` sejak Fase 15 supaya nama `ActionButton` bisa dipakai
 * tombol operator. Hapus file ini saat halaman bundle ditulis ulang di Fase 17.
 */

export interface ActionConflictPayload {
  current: ApiConflictCurrent;
  /** OfflineAction minimal - cukup untuk ConflictResolver (Fase 6). */
  action: OfflineAction;
}

interface ApiActionButtonProps {
  action: AllowedAction;
  /** Dipakai Fase 7 (submitAction); saat ini diteruskan ke payload konflik. */
  resource: string;
  resourceId: number | string;
  baseVersion: string;
  onSuccess?: () => void;
  onConflict?: (payload: ActionConflictPayload) => void;
}

export function ApiActionButton({
  action,
  resource,
  resourceId,
  baseVersion,
  onSuccess,
  onConflict,
}: ApiActionButtonProps) {
  const client = useApiClient();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleClick(): Promise<void> {
    const endpoint = action.endpoint;
    if (endpoint === undefined) {
      setError('Aksi tanpa endpoint');
      return;
    }

    setPending(true);
    setError(null);

    const idempotencyKey = generateUUID();
    const conflictPolicy = CONFLICT_POLICY[action.id] ?? 'manual';
    const body = { action: action.id, resource_id: resourceId };

    const res = await client.post(endpoint, body, { idempotencyKey, baseVersion, conflictPolicy });

    setPending(false);

    if (res.ok) {
      onSuccess?.();
      return;
    }

    if (res.status === 409 && res.conflict !== undefined) {
      const offlineAction: OfflineAction = {
        id: generateUUID(),
        path: endpoint,
        method: 'POST',
        body,
        resource,
        resourceId: String(resourceId),
        ts: Date.now(),
        base_version: baseVersion,
        conflict_policy: conflictPolicy,
        status: 'conflict',
        idempotency_key: idempotencyKey,
        // expected_result sengaja kosong (state lokal belum diketahui) -> resolver tampilkan '-'.
      };
      onConflict?.({ current: res.conflict.current, action: offlineAction });
      return;
    }

    setError(res.error?.message ?? `Gagal (${res.status})`);
  }

  return (
    <div className={cn('inline-flex flex-col gap-1')}>
      <Button
        variant="primary"
        loading={pending}
        title={action.confirm?.message}
        onClick={() => {
          void handleClick();
        }}
      >
        {action.label}
      </Button>
      {error !== null ? <span className="text-xs text-accent-coral">{error}</span> : null}
    </div>
  );
}
