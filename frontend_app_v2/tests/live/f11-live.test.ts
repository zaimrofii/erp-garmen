import { describe, expect, it } from 'vitest';

/**
 * F11 LIVE — aksi bundle BUNDLE_SCRAP / BUNDLE_QC (kontrak §4.4, seed state machine).
 *
 *   MES_LIVE=1 ~/.bun/bin/bun --bun run test tests/live
 *     → probe anonim; KALAU bundle masih punya transisi sah, probe DILEWATI (lihat guard)
 *
 *   MES_LIVE=1 MES_LIVE_ALLOW_SCRAP=1 MES_SESSION_COOKIE='sessionid=…' … run test tests/live
 *     → POST nyata dengan session (bundle harus dalam state yang sah; kalau DONE hasilnya 400)
 *
 * TEMUAN RECON PENTING: endpoint aksi `POST /garmen/bundles/{id}/{action}/` memakai
 * `permission_classes = [AllowAny]` (`apps_industry/garment/api/actions/views.py:60`,
 * komentar "auth menyusul Fase 6") sehingga request ANONIM **bisa** mengubah state bila
 * transisinya sah — anonim TIDAK membalas 403. Karena itu tes ini:
 *   1. membaca bundle dulu, dan melewati POST anonim kalau `allowed_actions` tidak kosong
 *      (mencegah tes menyentuh data produksi);
 *   2. memakai id aksi yang mustahil valid (`NGAWUR`) untuk membuktikan route ADA (400 ≠ 404).
 */

const LIVE = process.env['MES_LIVE'] === '1';
const ALLOW_SCRAP = process.env['MES_LIVE_ALLOW_SCRAP'] === '1';
const API_BASE = process.env['MES_API_BASE_URL'] ?? 'http://localhost:8000/api/v1';
const SESSION_COOKIE = process.env['MES_SESSION_COOKIE'] ?? '';
const BUNDLE_ID = process.env['MES_LIVE_BUNDLE_ID'] ?? '1';
const OPTED_IN = ALLOW_SCRAP && SESSION_COOKIE.length > 0;

const BUNDLE_PATH = `/garmen/bundles/${BUNDLE_ID}/`;
const SCRAP_PATH = `${BUNDLE_PATH}BUNDLE_SCRAP/`;
const QC_PATH = `${BUNDLE_PATH}BUNDLE_QC/`;

interface BundleSnapshot {
  state: string;
  version: string;
  allowed_actions: string[];
}

async function readBundle(): Promise<BundleSnapshot> {
  const res = await fetch(`${API_BASE}${BUNDLE_PATH}`);
  const body = (await res.json()) as Record<string, unknown>;
  const actions = Array.isArray(body['allowed_actions'])
    ? (body['allowed_actions'] as Record<string, unknown>[]).map((item) => String(item['id']))
    : [];

  return {
    state: String(body['state'] ?? ''),
    version: String(body['version'] ?? ''),
    allowed_actions: actions,
  };
}

function post(path: string, cookie?: string): Promise<Response> {
  return fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
      ...(cookie === undefined ? {} : { cookie }),
    },
    body: '{}',
  });
}

describe.skipIf(!LIVE)(
  'F11 LIVE — route aksi bundle ADA (anon 403: auth Fase 4.4 dicek LEBIH DULU)',
  () => {
    it('anon POST BUNDLE_SCRAP → 403 (dulu 400 state-machine; endpoint kini butuh login)', async () => {
      const before = await readBundle();

      expect(before.state.length).toBeGreaterThan(0);

      const res = await post(SCRAP_PATH);

      // F14/F15 (perubahan backend eksternal Fase 4.4): permission dinaikkan ke
      // IsAuthenticated → anonim ditolak SEBELUM validasi state machine (dulu 400).
      expect(res.status).toBe(403);
      expect(res.status).not.toBe(404);

      const body = (await res.json()) as Record<string, unknown>;

      expect(String(body['detail'])).toContain('autentikasi');
    });

    it('anon POST BUNDLE_QC → 403 (route ADA, aksi dikenal)', async () => {
      const before = await readBundle();

      expect(before.state.length).toBeGreaterThan(0);

      const res = await post(QC_PATH);

      expect(res.status).toBe(403);
      expect(res.status).not.toBe(404);
    });

    it('id aksi NGAWUR → 403 (route menerima <action> apa pun; auth lebih dulu, bukan 404)', async () => {
      const res = await post(`${BUNDLE_PATH}NGAWUR/`);

      expect(res.status).toBe(403);
      expect(res.status).not.toBe(404);
    });
  },
);

describe.skipIf(!LIVE)('F11 LIVE — opt-in dengan session', () => {
  it.skipIf(!OPTED_IN)('OPT-IN POST BUNDLE_SCRAP → 200 + state DONE + scrap=true (dua kali = 400)', async () => {
    const before = await readBundle();
    const res = await post(SCRAP_PATH, SESSION_COOKIE);

    if (!before.allowed_actions.includes('BUNDLE_SCRAP')) {
      // Bundle sudah DONE (data dev): transisi tidak sah → 400, dan data TIDAK berubah.
      expect(res.status).toBe(400);
      expect((await readBundle()).state).toBe(before.state);

      return;
    }

    expect(res.status).toBe(200);

    const body = (await res.json()) as Record<string, unknown>;
    const expected = body['expected_result'] as Record<string, unknown>;
    const fields = expected['fields'] as Record<string, unknown>;

    expect(body['state']).toBe('DONE');
    expect(fields['scrap']).toBe(true);
    expect((await readBundle()).state).toBe('DONE');

    // Aksi kedua dari DONE harus ditolak (state machine, bukan idempotensi).
    expect((await post(SCRAP_PATH, SESSION_COOKIE)).status).toBe(400);
  });
});
