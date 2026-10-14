import { useCallback, useEffect, useState } from 'react';
import type { AuthUser } from '@/api/auth';
import { fetchDeviceBindingState } from '@/api/devices';
import { DEVICE_PROFILE_REFRESH_EVENT } from '@/core/useDeviceProfile';
import { useAuth } from '@/hooks/auth-context';
import { useApiClient } from '@/hooks/useApiClient';
import { deviceModeFor, type DeviceMode } from '@/lib/device-mode';

/**
 * useDeviceMode.ts — auto-detect 3 mode operasi (F6.4).
 *
 *   * **device**  → cookie `device_token` dikenali backend (`source === 'device_binding'`):
 *     identitas perangkat/kios (badge TopBar). **Bukan izin masuk** — binding tanpa user
 *     tetap anonim di backend (FIX ROUTE, lihat `lib/auth-guard.ts`);
 *   * **session** → ada user sesi: login admin/supervisor, operator via kode 4 digit, ATAU
 *     cookie device binding ber-user (backend mengautentikasinya sebagai user itu);
 *   * **none**    → keduanya tidak ada → `AuthGuard` mengarahkan ke `/login`.
 *
 * Sumber data: `GET /devices/me` (lewat `api/devices` → `real/deviceBinding.ts`, yang membaca
 * `source`) dan state sesi dari `AuthProvider` (`GET /auth/me`, F6.2) — TIDAK ada panggilan
 * `/auth/me` kedua.
 *
 * Catatan kontrak: `/devices/me` **selalu 200** (fallback profile) sehingga status code tidak
 * dipakai; hanya `source === 'device_binding'` yang dianggap ter-bind.
 *
 * `refresh()` (atau event global `deviceProfileRefresh()` yang dipicu halaman settings
 * setelah bind/unbind) memaksa probe ulang tanpa reload halaman.
 */

export interface DeviceModeState {
  mode: DeviceMode;
  /** true selama probe device/sesi belum selesai — jangan redirect sebelum ini false. */
  loading: boolean;
  /** Profil perangkat dari cookie device (mentah, mis. `KIOS`) atau `null`. */
  profile: string | null;
  /** Work center binding (dari cookie device) atau `null`. */
  wcCode: string | null;
  /** true kalau cookie device `device_token` dikenali backend. */
  bound: boolean;
  /** User sesi (login admin/operator) atau `null`. */
  user: AuthUser | null;
  /** Probe ulang `GET /devices/me` (mis. setelah bind/unbind). */
  refresh: () => void;
}

export function useDeviceMode(): DeviceModeState {
  const client = useApiClient();
  const { user, loading: authLoading } = useAuth();

  const [bound, setBound] = useState(false);
  const [profile, setProfile] = useState<string | null>(null);
  const [wcCode, setWcCode] = useState<string | null>(null);
  const [deviceLoading, setDeviceLoading] = useState(true);
  const [nonce, setNonce] = useState(0);

  const refresh = useCallback((): void => {
    setNonce((current) => current + 1);
  }, []);

  useEffect(() => {
    let cancelled = false;

    // setState hanya SETELAH promise selesai (aturan lint `react-hooks/set-state-in-effect`);
    // `deviceLoading` sudah `true` sejak state awal sehingga tidak perlu di-set ulang.
    void fetchDeviceBindingState(client).then((state) => {
      if (cancelled) return;

      setBound(state.bound);
      setProfile(state.profile);
      setWcCode(state.wcCode);
      setDeviceLoading(false);
    });

    return () => {
      cancelled = true;
    };
  }, [client, nonce]);

  // Seam global (F7): halaman settings memanggil `deviceProfileRefresh()` setelah bind/unbind
  // → hook ini ikut membaca ulang tanpa reload. Tanpa DOM (SSR/test) listener tidak dipasang.
  useEffect(() => {
    const target = globalThis as {
      addEventListener?: (type: string, listener: () => void) => void;
      removeEventListener?: (type: string, listener: () => void) => void;
    };

    if (typeof target.addEventListener !== 'function') return undefined;

    const listener = (): void => {
      setNonce((current) => current + 1);
    };

    target.addEventListener(DEVICE_PROFILE_REFRESH_EVENT, listener);

    return () => {
      target.removeEventListener?.(DEVICE_PROFILE_REFRESH_EVENT, listener);
    };
  }, []);

  const loading = authLoading || deviceLoading;

  return {
    mode: deviceModeFor({ deviceBound: bound, hasSession: user !== null }),
    loading,
    profile,
    wcCode,
    bound,
    user,
    refresh,
  };
}
