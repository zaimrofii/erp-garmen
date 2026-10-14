import { readFileSync } from 'node:fs';
import path from 'node:path';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { fetchDeviceBindingState, readDeviceBindingState } from '@/api/devices';
import { createApiClient } from '@/integrations/api-client';
import {
  requiresLogin,
  deviceBadgeLabel,
  deviceInfoText,
  deviceModeFor,
} from '@/lib/device-mode';

/**
 * F6.4 — auto-detect 3 mode operasi (`useDeviceMode` + `api/devices`).
 *
 * Tanpa DOM/jsdom (`.clinerules` §ENVIRONMENT) hook diuji pada dua lapis:
 *  1. FUNGSI PURE `deviceModeFor()` (kombinasi device/sesi → mode);
 *  2. pembacaan respons backend nyata (`readDeviceBindingState` + `fetchDeviceBindingState`
 *     dengan `fetch` di-stub) — inilah sinyal yang dipakai hook.
 *
 * TEMUAN KONTRAK (penting): `GET /devices/me` **selalu 200** (fallback profile
 * `OPERATOR_HP`), jadi status code TIDAK menandakan binding — satu-satunya sinyal adalah
 * `source === 'device_binding'`.
 */

const BASE_URL = 'http://localhost:8000/api/v1';

function stubFetch(body: unknown, status = 200): { url: string; init: RequestInit }[] {
  const calls: { url: string; init: RequestInit }[] = [];

  vi.stubGlobal(
    'fetch',
    vi.fn((url: RequestInfo | URL, init?: RequestInit) => {
      calls.push({ url: String(url), init: init ?? {} });

      return Promise.resolve(
        new Response(JSON.stringify(body), {
          status,
          headers: { 'Content-Type': 'application/json' },
        }),
      );
    }),
  );

  return calls;
}

function client() {
  return createApiClient({ baseUrl: BASE_URL });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('F6.4 — deviceModeFor + requiresLogin (pure)', () => {
  it('1. cookie device ter-bind → mode device (identitas), TAPI tetap wajib sesi', () => {
    expect(deviceModeFor({ deviceBound: true, hasSession: false })).toBe('device');
    // FIX ROUTE: binding tanpa user = anonim di backend → login tetap wajib.
    expect(requiresLogin({ deviceBound: true, hasSession: false })).toBe(true);
  });

  it('2. tanpa device tapi ada sesi → mode session & tidak perlu login', () => {
    expect(deviceModeFor({ deviceBound: false, hasSession: true })).toBe('session');
    expect(requiresLogin({ deviceBound: false, hasSession: true })).toBe(false);
  });

  it('3. tanpa device & tanpa sesi → none (AuthGuard akan redirect /login)', () => {
    expect(deviceModeFor({ deviceBound: false, hasSession: false })).toBe('none');
    expect(requiresLogin({ deviceBound: false, hasSession: false })).toBe(true);
  });

  it('device menang atas session untuk badge (kios yang juga punya sesi lama)', () => {
    expect(deviceModeFor({ deviceBound: true, hasSession: true })).toBe('device');
    // kios BER-USER tetap auto-masuk: cookie device-nya sendiri yang mengisi sesi.
    expect(requiresLogin({ deviceBound: true, hasSession: true })).toBe(false);
  });
});

describe('F6.4 — pembacaan /devices/me (sinyal `source`)', () => {
  it('1b. 200 + source=device_binding → bound true + profil & WC', async () => {
    stubFetch({
      device_profile: 'KIOS',
      confidence: 'high',
      source: 'device_binding',
      wc_code: 'SEW-01',
    });

    const state = await fetchDeviceBindingState(client());

    expect(state.bound).toBe(true);
    expect(state.profile).toBe('KIOS');
    expect(state.wcCode).toBe('SEW-01');
    expect(state.source).toBe('device_binding');
    expect(state.message).toBeNull();
  });

  it('2b. 200 + source=fallback (TANPA cookie device) → bound false walau status 200', () => {
    const state = readDeviceBindingState({
      ok: true,
      status: 200,
      data: { device_profile: 'OPERATOR_HP', confidence: 'low', source: 'fallback', wc_code: null },
    });

    expect(state.bound).toBe(false);
    expect(state.wcCode).toBeNull();
    expect(state.profile).toBe('OPERATOR_HP');
  });

  it('3b. gagal jaringan → bound false + pesan (bukan throw)', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.reject(new Error('offline'))));

    const state = await fetchDeviceBindingState(client());

    expect(state.bound).toBe(false);
    expect(state.source).toBe('error');
    expect(state.message).toBe('offline');
  });

  it('4b. respons bukan objek / field hilang → aman (bound false, profil null)', () => {
    const state = readDeviceBindingState({ ok: true, status: 200, data: 'bukan objek' });

    expect(state.bound).toBe(false);
    expect(state.profile).toBeNull();
    expect(state.source).toBe('fallback');
  });
});

describe('F6.4 — label siap-tampil', () => {
  it('badge TopBar: "Device: <profil> @ <WC>" (WC opsional)', () => {
    expect(deviceBadgeLabel('KIOS', 'SEW-01')).toBe('Device: KIOS @ SEW-01');
    expect(deviceBadgeLabel('OPERATOR_HP', null)).toBe('Device: OPERATOR_HP');
    expect(deviceBadgeLabel(null, 'SEW-01')).toBe('Device');
  });

  it('info halaman login menjelaskan perangkat sudah terikat (tanpa klaim auto-login)', () => {
    expect(deviceInfoText('KIOS', 'SEW-01')).toContain('Device: KIOS @ SEW-01');
    // FIX ROUTE: teks lama "login tidak diperlukan" menyesatkan untuk binding TANPA user.
    expect(deviceInfoText('KIOS', 'SEW-01')).toContain('sudah terikat');
    expect(deviceInfoText(null, null)).toBe('Perangkat ini belum ter-bind.');
  });

  it('4. refresh: hook memakai seam global `deviceProfileRefresh()` (assert sumber)', () => {
    const root = path.resolve(import.meta.dirname, '../../..');
    const hook = readFileSync(path.join(root, 'src/hooks/useDeviceMode.ts'), 'utf8');

    // probe ulang saat mount & saat event global dipicu (tanpa reload halaman)
    expect(hook).toContain('useEffect(');
    expect(hook).toContain('DEVICE_PROFILE_REFRESH_EVENT');
    expect(hook).toContain('setNonce((current) => current + 1)');
    expect(hook).toContain('deviceModeFor({ deviceBound: bound, hasSession: user !== null })');
  });
});
