import { describe, expect, it } from 'vitest';
import { ACTION_MODES, normalizeActionMode, type ActionResponse } from '@/types/api';
import { readActionState } from '@/lib/action-runner';
import { AllowedActionSchema } from '@/lib/schemas/action.schema';
import { resolveTransitionMode } from '@/lib/transition-rules';

/** F1 — D2 (`ActionResponse.state` top-level) + D6 (`allowed_actions[].mode` lowercase). */

describe('D6 — metadata `allowed_actions[].mode` LOWERCASE', () => {
  it('contoh kontrak v4.3 (§3.2) lolos schema apa adanya', () => {
    const parsed = AllowedActionSchema.safeParse({
      id: 'BUNDLE_START',
      label: 'Mulai Bundle',
      mode: 'optimistic',
      endpoint: '/garmen/bundles/16/BUNDLE_START/',
    });

    expect(parsed.success).toBe(true);
    if (parsed.success) {
      expect(parsed.data.mode).toBe('optimistic');
      expect(parsed.data.endpoint).toBe('/garmen/bundles/16/BUNDLE_START/');
    }
  });

  it('ACTION_MODES hanya berisi lowercase', () => {
    expect([...ACTION_MODES]).toEqual(['optimistic', 'pessimistic']);
  });

  it('normalizeActionMode: uppercase di-lowercase, nilai asing → undefined', () => {
    expect(normalizeActionMode('OPTIMISTIC')).toBe('optimistic');
    expect(normalizeActionMode('  Pessimistic ')).toBe('pessimistic');
    expect(normalizeActionMode('optimistic')).toBe('optimistic');
    expect(normalizeActionMode('auto')).toBeUndefined();
    expect(normalizeActionMode('')).toBeUndefined();
    expect(normalizeActionMode(1)).toBeUndefined();
    expect(normalizeActionMode(null)).toBeUndefined();
  });

  it('schema MENOLAK mode uppercase (kontrak: lowercase)', () => {
    expect(
      AllowedActionSchema.safeParse({ id: 'BUNDLE_START', label: 'Mulai', mode: 'OPTIMISTIC' })
        .success
    ).toBe(false);
  });

  it('TRANSITION_MODE tetap prioritas 1 atas metadata mode', () => {
    expect(resolveTransitionMode('BUNDLE_SCRAP', 'optimistic')).toBe('pessimistic');
    expect(resolveTransitionMode('AKSI_BARU', 'optimistic')).toBe('optimistic');
    expect(resolveTransitionMode('AKSI_BARU')).toBe('pessimistic');
  });
});

describe('D2 — ActionResponse (state top-level)', () => {
  it('respons 200 aksi kontrak v4.3 → state terbaca dari top-level', () => {
    const raw = {
      ok: true,
      resource: 'bundles',
      id: 16,
      action: 'BUNDLE_START',
      version: 'new-sha256',
      state: 'CUTTING',
      expected_result: { state: 'CUTTING', fields: { state: 'CUTTING' } },
    };

    const response: ActionResponse = raw;

    expect(response.state).toBe('CUTTING');
    expect(response.expected_result?.fields).toEqual({ state: 'CUTTING' });
    expect(readActionState(response)).toBe('CUTTING');
  });

  it('field kritis yang diangkat backend tetap bisa dibaca (index signature)', () => {
    const response: ActionResponse = {
      ok: true,
      state: 'CUTTING',
      qty_done: 4,
    };

    expect(response['qty_done']).toBe(4);
  });
});
