import { describe, expect, it } from 'vitest';
import {
  buildForcedInput,
  planConflictResolution,
  readConflictCurrent,
} from '@/integrations/conflict-plan';
import type { OfflineAction } from '@/integrations/offline-queue';

/** F1 — D3: body 409 backend v4.3 → `current` TOP-LEVEL dulu, alias `conflict.current` fallback. */

const BODY_TOP_LEVEL = {
  current: { version: 'old-sha256', state: 'CUTTING', current_work_center: 'SEWING-1' },
  conflict: {
    current: { version: 'alias-sha256', state: 'SABLON', current_work_center: null },
  },
};

const ACTION: OfflineAction = {
  id: 'action-1',
  path: '/garmen/bundles/16/BUNDLE_START/',
  method: 'POST',
  body: { action: 'BUNDLE_START', resource_id: '16' },
  resource: 'bundles',
  resourceId: '16',
  ts: 1_760_000_000_000,
  base_version: 'versi-lokal',
  conflict_policy: 'manual',
  status: 'conflict',
  idempotency_key: 'idem-1',
};

describe('D3 — readConflictCurrent', () => {
  it('kasus 1: `current` TOP-LEVEL ada → itu yang dipakai (bukan alias)', () => {
    expect(readConflictCurrent(BODY_TOP_LEVEL)).toEqual({
      version: 'old-sha256',
      state: 'CUTTING',
      current_work_center: 'SEWING-1',
    });
  });

  it('kasus 2: hanya alias `conflict.current` → tetap terbaca', () => {
    const aliasOnly = {
      conflict: { current: { version: 'old-sha256', state: 'CUTTING' } },
    };

    expect(readConflictCurrent(aliasOnly)).toEqual({ version: 'old-sha256', state: 'CUTTING' });
  });

  it('objek tanpa version/state lengkap → undefined (tidak menebak)', () => {
    expect(readConflictCurrent({ conflict: { current: { state: 'CUTTING' } } })).toBeUndefined();
    expect(readConflictCurrent({ current: { version: 'x' } })).toBeUndefined();
    expect(readConflictCurrent({})).toBeUndefined();
    expect(readConflictCurrent(null)).toBeUndefined();
    expect(readConflictCurrent('409')).toBeUndefined();
  });

  it('`current_work_center: null` tidak dianggap nilai valid', () => {
    expect(readConflictCurrent({ current: { version: 'v', state: 'S', current_work_center: null } })).toEqual(
      { version: 'v', state: 'S' }
    );
  });
});

describe('plan resolusi konflik (tetap konsisten setelah D3)', () => {
  it('server_wins → refetch', () => {
    expect(planConflictResolution('server_wins', ACTION)).toEqual({ kind: 'refetch' });
  });

  it('cancel → keep_queued', () => {
    expect(planConflictResolution('cancel', ACTION)).toEqual({ kind: 'keep_queued' });
  });

  it('retry_force → base_version dari `current` + policy last_write_wins', () => {
    const current = readConflictCurrent(BODY_TOP_LEVEL);
    const plan = planConflictResolution('retry_force', ACTION, current);

    expect(plan).toEqual({
      kind: 'retry_force',
      input: {
        path: ACTION.path,
        method: 'POST',
        body: ACTION.body,
        resource: 'bundles',
        resourceId: '16',
        base_version: 'old-sha256',
        conflict_policy: 'last_write_wins',
      },
    });
  });

  it('buildForcedInput tanpa `current` → base_version lokal dipertahankan', () => {
    expect(buildForcedInput(ACTION, undefined).base_version).toBe('versi-lokal');
  });
});
