import { describe, expect, it } from 'vitest';
import { DEVICE_BIND_PATH, DEVICE_UNBIND_PATH } from '@/integrations/device-binding';

/**
 * F7 LIVE — device binding (`core/device_profile/api.py`).
 *
 *   MES_LIVE=1 ~/.bun/bin/bun --bun run test tests/live
 *     → probe anonim SAJA (tidak mengubah binding apa pun)
 *
 *   MES_LIVE=1 MES_LIVE_ALLOW_BIND=1 … run test tests/live
 *     → bind nyata (membuat/meng-update baris `DeviceBinding` + cookie `device_token`
 *       pada request itu), verifikasi `/devices/me` berubah, lalu unbind lagi.
 *
 * Catatan kontrak (diperbarui F15 atas perubahan backend Fase 4.4): endpoint bind/unbind
 * kini **IsAuthenticated** → probe anonim = **403** (sebelumnya AllowAny: 400/200).
 * Jalur OPT-IN kini juga memakai session cookie.
 */

const LIVE = process.env['MES_LIVE'] === '1';
const ALLOW_BIND = process.env['MES_LIVE_ALLOW_BIND'] === '1';
const API_BASE = process.env['MES_API_BASE_URL'] ?? 'http://localhost:8000/api/v1';
const SESSION_COOKIE = process.env['MES_SESSION_COOKIE'] ?? '';
const PROFILE_OVERRIDE = process.env['MES_LIVE_DEVICE_PROFILE'] ?? '';
const OPTED_IN = ALLOW_BIND && SESSION_COOKIE.length > 0;

const KNOWN_SOURCES = ['device_binding', 'url_override', 'user_preference', 'backend_hint', 'fallback'];

async function postJson(path: string, body: unknown, cookie?: string): Promise<Response> {
  return fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
      ...(cookie === undefined ? {} : { cookie }),
    },
    body: JSON.stringify(body),
  });
}

describe.skipIf(!LIVE)('F7 LIVE — device resolver & binding', () => {
  it('GET /devices/me anon → 200 {device_profile, confidence, source, wc_code}', async () => {
    const res = await fetch(`${API_BASE}/devices/me`);

    expect(res.status).toBe(200);

    const body = (await res.json()) as Record<string, unknown>;

    expect(typeof body['device_profile']).toBe('string');
    expect(['high', 'medium', 'low']).toContain(body['confidence']);
    expect(KNOWN_SOURCES).toContain(body['source']);
    expect(body).toHaveProperty('wc_code');
  });

  it('POST /devices/bind anon → 403 (Fase 4.4 hardening: dulu 400 validasi profil)', async () => {
    const res = await postJson(DEVICE_BIND_PATH, {});

    expect(res.status).toBe(403);
    expect(res.status).not.toBe(404);

    const body = (await res.json()) as Record<string, unknown>;

    expect(String(body['detail'])).toContain('autentikasi');
  });

  it('POST /devices/unbind anon → 403 (Fase 4.4 hardening: dulu 200 {ok:true})', async () => {
    const res = await postJson(DEVICE_UNBIND_PATH, {});

    expect(res.status).toBe(403);
    expect(res.status).not.toBe(404);
  });

  it.skipIf(!OPTED_IN)(
    'OPT-IN: bind → cookie HttpOnly → /devices/me berubah → unbind (MES_LIVE_ALLOW_BIND=1 + MES_SESSION_COOKIE)',
    async () => {
      // Kode profil diambil dari backend (bukan hardcode) supaya selalu sinkron DB.
      // Bind/unbind kini butuh session → probe + bind + unbind memakai cookie yang sama.
      const probe = await postJson(DEVICE_BIND_PATH, {}, SESSION_COOKIE);
      const allowed = ((await probe.json()) as { allowed?: string[] }).allowed ?? [];
      const profile = PROFILE_OVERRIDE.length > 0 ? PROFILE_OVERRIDE : (allowed[0] ?? '');

      expect(profile.length).toBeGreaterThan(0);

      const bindRes = await postJson(
        DEVICE_BIND_PATH,
        { device_profile: profile },
        SESSION_COOKIE,
      );

      expect(bindRes.status).toBe(200);

      const bindBody = (await bindRes.json()) as Record<string, unknown>;

      expect(bindBody['source']).toBe('device_binding');
      expect(bindBody['device_profile']).toBe(profile);

      const headers = bindRes.headers as Headers & { getSetCookie?: () => string[] };
      const setCookie = headers.getSetCookie?.()[0] ?? headers.get('set-cookie') ?? '';

      expect(setCookie).toContain('device_token=');
      expect(setCookie.toLowerCase()).toContain('httponly');

      const cookie = setCookie.split(';')[0] ?? '';
      // Fase 4.4: /devices/me & unbind kini boleh/butuh session → kirim dua cookie.
      const cookieHeader = [cookie, SESSION_COOKIE].filter((item) => item.length > 0).join('; ');

      const meRes = await fetch(`${API_BASE}/devices/me`, { headers: { cookie: cookieHeader } });
      const me = (await meRes.json()) as Record<string, unknown>;

      expect(me['device_profile']).toBe(profile);
      expect(me['source']).toBe('device_binding');

      const unbindRes = await postJson(DEVICE_UNBIND_PATH, {}, cookieHeader);

      expect(unbindRes.status).toBe(200);

      const unbindBody = (await unbindRes.json()) as Record<string, unknown>;

      expect(unbindBody['ok']).toBe(true);
      expect(unbindBody['revoked']).toBe(true);
    }
  );
});
