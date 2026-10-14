import { afterEach, describe, expect, it, vi } from 'vitest';
import type { ApiClient, ApiResponse } from '@/integrations/api-client';
import { createApiClient } from '@/integrations/api-client';
import {
  bindDevice,
  canBindDevice,
  canUnbindDevice,
  DEVICE_BIND_PATH,
  DEVICE_UNBIND_PATH,
  readBindingOutcome,
  readUnbindOutcome,
  unbindDevice,
} from '@/integrations/device-binding';

/**
 * F7 — `integrations/device-binding.ts`.
 *
 * KontrakNYATA backend (`core/device_profile/api.py`) — BUKAN yang tertulis di brief:
 *   bind   : `{device_profile, wc_code?}` (AllowAny) → `{device_profile, confidence, source:'device_binding', wc_code}`
 *   unbind : `{}`                          (AllowAny) → `{ok, revoked, device_profile, source:'fallback', wc_code}`
 *   (docs §2.2 `{device_code, device_type}` + “IsAuthenticated” = USANG; live bind anon → 400 validasi)
 */

interface PostCall {
  path: string;
  body: unknown;
}

function stubClient(data: unknown, ok = true, status = 200): { client: ApiClient; calls: PostCall[] } {
  const calls: PostCall[] = [];

  const client = {
    post: async <T,>(path: string, body: unknown): Promise<ApiResponse<T>> => {
      calls.push({ path, body });

      return ok
        ? { ok: true, status, data: data as T }
        : { ok: false, status, error: { kind: 'http_error', message: 'HTTP ' + status } };
    },
  } as unknown as ApiClient;

  return { client, calls };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('F7 — bindDevice', () => {
  it('path /devices/bind + body {device_profile} tanpa wc_code kalau kosong', async () => {
    const { client, calls } = stubClient({
      device_profile: 'SCANNER_USB',
      confidence: 'high',
      source: 'device_binding',
      wc_code: null,
    });

    const outcome = await bindDevice(client, 'SCANNER_USB', '   ');

    expect(calls).toEqual([{ path: DEVICE_BIND_PATH, body: { device_profile: 'SCANNER_USB' } }]);
    expect(outcome.ok).toBe(true);
    expect(outcome.deviceProfile).toBe('SCANNER_USB');
    expect(outcome.source).toBe('device_binding');
    expect(outcome.message).toContain('SCANNER_USB');
  });

  it('wc_code diisi → ikut dikirim (trim)', async () => {
    const { client, calls } = stubClient({ source: 'device_binding', device_profile: 'KIOSK_TABLET', wc_code: 'WC-01' });

    const outcome = await bindDevice(client, 'KIOSK_TABLET', ' WC-01 ');

    expect(calls).toEqual([
      { path: DEVICE_BIND_PATH, body: { device_profile: 'KIOSK_TABLET', wc_code: 'WC-01' } },
    ]);
    expect(outcome.wcCode).toBe('WC-01');
  });

  it('readBindingOutcome: 400 berisi detail + allowed → pesan & daftar profil sah', () => {
    const outcome = readBindingOutcome({
      ok: false,
      status: 400,
      data: { detail: 'Profil tidak dikenal.', allowed: ['OPERATOR_HP'] },
      error: { kind: 'http_error', message: 'HTTP 400' },
    });

    expect(outcome.ok).toBe(false);
    expect(outcome.allowed).toEqual(['OPERATOR_HP']);
    expect(outcome.message).toContain('Profil tidak dikenal.');
  });

  it('bindDevice gagal HTTP → union gagal (pesan dari api-client; body error belum diteruskan engine v1)', async () => {
    const { client } = stubClient(null, false, 400);

    const outcome = await bindDevice(client, 'TIDAK-ADA');

    expect(outcome.ok).toBe(false);
    expect(outcome.message).toContain('HTTP 400');
  });

  it('200 tanpa source device_binding dianggap gagal', () => {
    const outcome = readBindingOutcome({ ok: true, status: 200, data: { source: 'fallback' } });

    expect(outcome.ok).toBe(false);
  });

  it('URL penuh + credentials (POST = tulis) lewat api-client', async () => {
    const calls: { url: string; init: RequestInit }[] = [];
    vi.stubGlobal(
      'fetch',
      vi.fn((url: RequestInfo | URL, init?: RequestInit) => {
        calls.push({ url: String(url), init: init ?? {} });

        return Promise.resolve(
          new Response(JSON.stringify({ device_profile: 'DESKTOP', source: 'device_binding', wc_code: null }), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          }),
        );
      }),
    );

    const client = createApiClient({ baseUrl: 'http://localhost:8000/api/v1' });
    const outcome = await bindDevice(client, 'DESKTOP');

    expect(calls[0]?.url).toBe('http://localhost:8000/api/v1/devices/bind');
    expect(calls[0]?.init.method).toBe('POST');
    expect(calls[0]?.init.credentials).toBe('include');
    expect(outcome.ok).toBe(true);
  });
});

describe('F7 — unbindDevice', () => {
  it('path /devices/unbind + body {} + outcome revoked', async () => {
    const { client, calls } = stubClient({ ok: true, revoked: true, source: 'fallback' });

    const outcome = await unbindDevice(client);

    expect(calls).toEqual([{ path: DEVICE_UNBIND_PATH, body: {} }]);
    expect(outcome).toEqual({ ok: true, revoked: true, message: 'Ikatan perangkat dicabut.' });
  });

  it('revoked:false → pesan “memang belum terikat”', () => {
    expect(readUnbindOutcome({ ok: true, status: 200, data: { ok: true, revoked: false } }).message).toContain(
      'belum terikat',
    );
    expect(readUnbindOutcome({ ok: false, status: 500, error: { kind: 'http_error', message: 'HTTP 500' } }).ok).toBe(
      false,
    );
  });
});

describe('F7/7.6 — guard tombol (pure)', () => {
  it('canBindDevice: butuh profil & tidak sibuk', () => {
    expect(canBindDevice({ deviceProfile: 'OPERATOR_HP', busy: false })).toBe(true);
    expect(canBindDevice({ deviceProfile: '   ', busy: false })).toBe(false);
    expect(canBindDevice({ deviceProfile: 'OPERATOR_HP', busy: true })).toBe(false);
  });

  it('canUnbindDevice: butuh status bound & tidak sibuk', () => {
    expect(canUnbindDevice({ busy: false, isBound: true })).toBe(true);
    expect(canUnbindDevice({ busy: false, isBound: false })).toBe(false);
    expect(canUnbindDevice({ busy: true, isBound: true })).toBe(false);
  });
});
