import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';
import {
  changePassword as changePasswordRequest,
  getMe,
  login as loginRequest,
  loginOperator as loginOperatorRequest,
  logout as logoutRequest,
  type AuthUser,
} from '@/api/auth';
import { AuthContext, type AuthContextValue } from '@/hooks/auth-context';
import { useApiClient } from '@/hooks/useApiClient';
import type { ApiClient } from '@/integrations/api-client';

/**
 * useAuth.tsx — `AuthProvider`: SATU sumber kebenaran user yang sedang login (F6.2).
 *
 * `AuthProvider` diletakkan sekali di `App.tsx` (membungkus App Shell + halaman) supaya
 * `TopBar` (di dalam App Shell) dan `AuthGuard`/`LoginPage` memakai state yang SAMA.
 * Kalau provider ditaruh di dalam `AuthGuard`, `TopBar` berada di LUAR provider tersebut
 * (App Shell membungkus `<Routes>`) sehingga butuh provider kedua → dua state user yang
 * bisa berbeda. Keputusan ini dicatat di `docs/current-project.json` (F6.2).
 *
 * Hook `useAuth()` + konteksnya ada di `hooks/auth-context.ts` (aturan lint
 * `react(only-export-components)`: file komponen tidak boleh mengekspor non-komponen).
 *
 * Perilaku:
 *  - saat mount → `getMe()` (probe sesi). 401 → `user = null`; network/5xx → `user = null`
 *    juga (guard mengarahkan ke `/login`; halaman login yang menampilkan pesan
 *    "Koneksi gagal, cek jaringan" saat submit);
 *  - `login()`/`loginOperator()` menyimpan hasil login LALU memanggil `getMe()` sekali lagi
 *    supaya profil lengkap (E2 mengirim subset; E4 menambahkan `device_profile`);
 *  - `logout()` selalu membersihkan state lokal walau request-nya gagal (best-effort).
 */

interface AuthProviderProps {
  children: ReactNode;
  /** Seam test / reuse: klien alternatif (default: `useApiClient()`). */
  client?: ApiClient;
}

export function AuthProvider({ children, client }: AuthProviderProps) {
  const defaultClient = useApiClient();
  const api = client ?? defaultClient;

  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);

  /** Probe sesi tanpa mengubah state (dipakai login agar tidak sempat men-set null). */
  const probe = useCallback(async (): Promise<AuthUser | null> => {
    try {
      return await getMe(api);
    } catch {
      // Network/5xx ≠ bukti "tidak login", tetapi tanpa sesi aplikasi tidak bisa apa-apa →
      // perlakukan sama seperti belum login (guard akan menampilkan halaman login).
      return null;
    }
  }, [api]);

  const refresh = useCallback(async (): Promise<AuthUser | null> => {
    const current = await probe();
    setUser(current);

    return current;
  }, [probe]);

  useEffect(() => {
    let cancelled = false;

    // Probe sesi awal. `setState` hanya terjadi SETELAH promise selesai (bukan sinkron
    // di dalam effect) — mengikuti aturan lint `react-hooks/set-state-in-effect`.
    // `loading` sudah `true` sejak state awal, jadi tidak perlu di-set ulang di sini.
    void (async () => {
      const current = await probe();
      if (cancelled) return;

      setUser(current);
      setLoading(false);
    })();

    return () => {
      cancelled = true;
    };
  }, [probe]);

  const login = useCallback(
    async (username: string, password: string): Promise<AuthUser> => {
      const loggedIn = await loginRequest(api, username, password);
      const full = await probe();
      const next = full ?? loggedIn;

      setUser(next);

      return next;
    },
    [api, probe],
  );

  const loginOperator = useCallback(
    async (operatorCode: string): Promise<AuthUser> => {
      const loggedIn = await loginOperatorRequest(api, operatorCode);
      const full = await probe();
      const next = full ?? loggedIn;

      setUser(next);

      return next;
    },
    [api, probe],
  );

  const logout = useCallback(async (): Promise<void> => {
    try {
      await logoutRequest(api);
    } catch {
      // Best-effort: sesi lokal tetap dibersihkan supaya user tidak terjebak di UI bersesi.
    } finally {
      setUser(null);
    }
  }, [api]);

  const changePassword = useCallback(
    async (oldPassword: string, newPassword: string): Promise<void> => {
      await changePasswordRequest(api, oldPassword, newPassword);
    },
    [api],
  );

  const value = useMemo<AuthContextValue>(
    () => ({ user, loading, login, loginOperator, logout, refresh, changePassword }),
    [user, loading, login, loginOperator, logout, refresh, changePassword],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
