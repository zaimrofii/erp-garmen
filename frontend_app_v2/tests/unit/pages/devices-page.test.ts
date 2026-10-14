import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

/**
 * F7/7.1–7.6 — halaman device (`/settings/devices`).
 *
 * `DevicesPage.tsx` TIDAK ada di repo: route `/settings/devices` merender
 * `DeviceProfilesPage.tsx` (sudah list device + form bind sejak Fase 22). Sesuai aturan
 * brief ("jangan buat halaman baru kalau sudah ada"), F7 menambah seam refresh + guard
 * pure, bukan halaman baru.
 *
 * Rendering penuh butuh Router + QueryClient + provider runtime (di luar gaya tes
 * tanpa DOM), jadi tes ini memaku **wiring** sumber + guard/pure helper yang dipakai.
 */

const ROOT = path.resolve(import.meta.dirname, '../../..');
const PAGE = 'src/pages/settings/DeviceProfilesPage.tsx';

function read(relative: string): string {
  return readFileSync(path.join(ROOT, relative), 'utf8');
}

describe('F7 — route & sumber data', () => {
  it('route /settings/devices merender DeviceProfilesPage', () => {
    const app = read('src/App.tsx');

    expect(app).toContain('path="/settings/devices"');
    expect(app).toContain('<DeviceProfilesPage />');
  });

  it('list device dari GET /devices/me (+ badge bound/unbound)', () => {
    const page = read(PAGE);

    expect(page).toContain("import { fetchMyDevice } from '@/api/devices'");
    expect(page).toContain('fetchMyDevice(apiClient)');
    expect(page).toContain('Perangkat Ini');
    expect(page).toContain('isBound');
  });
});

describe('F7/7.2-7.3 — form bind/unbind', () => {
  it('pakai integration yang SUDAH ADA (tidak dibuat ulang)', () => {
    const page = read(PAGE);

    expect(page).toContain("from '@/integrations/device-binding'");
    // F6.4 — WC final dihitung helper pure (`resolveWcCode`) dari dropdown/input manual.
    expect(page).toContain('bindDevice(apiClient, effectiveProfile, effectiveWc)');
    expect(page).toContain('unbindDevice(apiClient)');
  });

  it('guard tombol memakai helper pure (7.6)', () => {
    const page = read(PAGE);

    expect(page).toContain('canBindDevice({ deviceProfile: effectiveProfile, busy })');
    expect(page).toContain('canUnbindDevice({ busy, isBound })');
  });
});

describe('F7/7.4-7.5 — refresh resolver global + feedback', () => {
  it('setelah bind/unbind → deviceProfileRefresh() + invalidate query', () => {
    const page = read(PAGE);

    expect(page).toContain('deviceProfileRefresh()');
    expect(page).toContain('invalidateQueries({ queryKey: DEVICE_QUERY_KEY })');
  });

  it('feedback beep/haptic + toast', () => {
    const page = read(PAGE);

    expect(page).toContain("feedback.trigger('success')");
    expect(page).toContain("feedback.trigger('error')");
    expect(page).toContain('<Toast');
  });

  it('hook resolver punya method refresh() (tidak me-restructure)', () => {
    const hook = read('src/core/useDeviceProfile.ts');

    expect(hook).toContain('refresh: () => void;');
    expect(hook).toContain('const refresh = useCallback');
    expect(hook).toContain('DEVICE_PROFILE_REFRESH_EVENT');
  });
});

describe('F7 — cookie HttpOnly tidak disentuh', () => {
  it('halaman tidak membaca device_token / document.cookie', () => {
    const page = read(PAGE);

    expect(page).not.toContain('device_token');
    expect(page).not.toContain('document.cookie');
  });
});
