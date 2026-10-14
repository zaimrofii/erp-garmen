import { describe, expect, it } from 'vitest';
import {
  BUNDLE_ACTION_IDS,
  BUNDLE_ACTION_SOURCE_STATES,
  bundleActionSourceStates,
  canRunBundleAction,
  canSubmitBundleAction,
  defaultActionPath,
  hasAllowedAction,
  readActionState,
  resolveActionPath,
  resolveActionState,
  resolveActionVisualState,
  slugifyActionId,
} from '@/lib/action-runner';
import type { ActionResponse } from '@/types/api';

/** F1 — D1 (endpoint relatif, anti double-prefix) + D2 (state respons di top-level). */

const BASE_URL = 'http://localhost:8000/api/v1';
const ENDPOINT = '/garmen/bundles/16/BUNDLE_START/';

describe('D1 — resolveActionPath memakai baseUrl SEKALI saja', () => {
  it('kasus 1: endpoint relatif normal → baseUrl + endpoint', () => {
    expect(resolveActionPath(BASE_URL, ENDPOINT)).toBe(
      'http://localhost:8000/api/v1/garmen/bundles/16/BUNDLE_START/'
    );
  });

  it('kasus 2: endpoint sudah absolut (http/https) → dipakai apa adanya', () => {
    const absolute = 'https://mes.example.com/api/v1/garmen/bundles/16/BUNDLE_START/';

    expect(resolveActionPath(BASE_URL, absolute)).toBe(absolute);
  });

  it('kasus 3: endpoint sudah membawa /api/v1 → tidak di-prefix dua kali', () => {
    expect(resolveActionPath(BASE_URL, `/api/v1${ENDPOINT}`)).toBe(
      'http://localhost:8000/api/v1/garmen/bundles/16/BUNDLE_START/'
    );
  });

  it('baseUrl kosong → path dikembalikan apa adanya (env belum diisi)', () => {
    expect(resolveActionPath('', ENDPOINT)).toBe(ENDPOINT);
  });

  it('baseUrl tanpa prefix /api/v1 TIDAK memotong path yang memakai /api/v1', () => {
    expect(resolveActionPath('http://host', '/api/v1/garmen/bundles/1/')).toBe(
      'http://host/api/v1/garmen/bundles/1/'
    );
  });

  it('fallback konvensi (backend lama tanpa endpoint) tetap tersedia', () => {
    // Konvensi lama: `BUNDLE_START` + resource `bundles` → prefix `BUNDLES_` tidak cocok,
    // jadi slug yang dihasilkan `bundle-start` (hanya dipakai kalau backend TIDAK kirim endpoint).
    expect(slugifyActionId('BUNDLE_START', 'bundles')).toBe('bundle-start');
    expect(slugifyActionId('BUNDLES_START', 'bundles')).toBe('start');
    expect(defaultActionPath('BUNDLE_START', 'bundles', '16')).toBe('/bundles/16/bundle-start/');
  });
});

describe('F11 — konstanta aksi bundle BUNDLE_SCRAP/BUNDLE_QC', () => {
  it('id aksi apa adanya + terdaftar lengkap', () => {
    expect(BUNDLE_ACTION_IDS.SCRAP).toBe('BUNDLE_SCRAP');
    expect(BUNDLE_ACTION_IDS.QC).toBe('BUNDLE_QC');
    expect(Object.values(BUNDLE_ACTION_IDS)).toEqual([
      'BUNDLE_START',
      'BUNDLE_ADVANCE',
      'BUNDLE_QC',
      'BUNDLE_FINISH',
      'BUNDLE_SCRAP',
      'BUNDLE_REWORK',
    ]);
  });

  it('state asal mengikuti seed `garment.bundle` (docs §4.4)', () => {
    expect(BUNDLE_ACTION_SOURCE_STATES['BUNDLE_QC']).toEqual(['SEWING']);
    expect(BUNDLE_ACTION_SOURCE_STATES['BUNDLE_SCRAP']).toEqual([
      'DRAFT',
      'CUTTING',
      'SEWING',
      'QC',
    ]);
    expect(bundleActionSourceStates('bundle_scrap')).toEqual(['DRAFT', 'CUTTING', 'SEWING', 'QC']);
    expect(bundleActionSourceStates('NGAWUR')).toBeUndefined();
  });

  it('canRunBundleAction: QC hanya SEWING, SCRAP kecuali DONE', () => {
    expect(canRunBundleAction('BUNDLE_QC', 'SEWING')).toBe(true);
    expect(canRunBundleAction('BUNDLE_QC', 'QC')).toBe(false);
    expect(canRunBundleAction('BUNDLE_SCRAP', 'QC')).toBe(true);
    expect(canRunBundleAction('BUNDLE_SCRAP', 'DONE')).toBe(false);
    expect(canRunBundleAction('BUNDLE_SCRAP', undefined)).toBe(false);
  });

  it('canSubmitBundleAction = metadata ∧ state', () => {
    const allowed = [{ id: 'BUNDLE_SCRAP' }];

    expect(hasAllowedAction(allowed, 'BUNDLE_SCRAP')).toBe(true);
    expect(canSubmitBundleAction(allowed, 'BUNDLE_SCRAP', 'SEWING')).toBe(true);
    expect(canSubmitBundleAction(allowed, 'BUNDLE_SCRAP', 'DONE')).toBe(false);
  });
});

describe('D2 — state respons aksi dibaca dari TOP-LEVEL dulu', () => {
  const RESPONSE: ActionResponse = {
    ok: true,
    resource: 'bundles',
    id: 16,
    action: 'BUNDLE_START',
    version: 'new-sha256',
    state: 'CUTTING',
    expected_result: { state: 'CUTTING', fields: { state: 'CUTTING' } },
  };

  it('kontrak v4.3: {ok,resource,id,action,version,state,expected_result}', () => {
    expect(resolveActionState(RESPONSE)).toBe('CUTTING');
    expect(readActionState(RESPONSE)).toBe('CUTTING');
  });

  it('top-level menang kalau berbeda dari expected_result.state', () => {
    const drifted = {
      ...RESPONSE,
      state: 'SEWING',
      expected_result: { state: 'CUTTING' },
    };

    expect(readActionState(drifted)).toBe('SEWING');
  });

  it('fallback `expected_result.state` (respons backend lama)', () => {
    expect(readActionState({ ok: true, expected_result: { state: 'QC' } })).toBe('QC');
  });

  it('state tidak ada/tidak valid → null (tidak menebak)', () => {
    expect(readActionState({ ok: true })).toBeNull();
    expect(readActionState({ state: '' })).toBeNull();
    expect(readActionState({ state: 12 })).toBeNull();
    expect(readActionState(null)).toBeNull();
    expect(readActionState(['CUTTING'])).toBeNull();
    expect(resolveActionState(undefined)).toBeNull();
  });

  it('resolver state VISUAL tombol terpisah dari resolver state respons', () => {
    const resolution = resolveActionVisualState({
      actionId: 'BUNDLE_START',
      mode: 'optimistic',
      resourceId: '16',
      pendingByResource: new Map([['16', 'BUNDLE_START']]),
      online: true,
    });

    expect(resolution).toEqual({ state: 'optimistic', disabled: true, badge: 'none' });
  });
});
