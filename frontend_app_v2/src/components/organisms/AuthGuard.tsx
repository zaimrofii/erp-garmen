import type { ReactNode } from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { Spinner } from '@/components/atoms/Spinner';
import { useDeviceMode } from '@/hooks/useDeviceMode';
import { guardDecision, type GuardDecision } from '@/lib/auth-guard';
import { loginRedirectPath } from '@/lib/login-form';

/**
 * AuthGuard.tsx — gerbang halaman butuh-login (F6.2, diperluas F6.4).
 *
 * Alur: `useDeviceMode()` (mode device/session/none) → `guardDecision()`:
 *
 *   loading   → spinner (probe `/devices/me` + sesi belum selesai);
 *   sesi ada  → render `children` (termasuk kios: cookie device binding ber-user
 *               DIAUTENTIKASI backend sehingga `/auth/me` mengisi `user`);
 *   selain itu→ `<Navigate to="/login?redirect=<halaman>" replace />`.
 *
 * FIX ROUTE: cookie device ter-bind TANPA user TIDAK lagi membuka gerbang — backend
 * memperlakukan binding tanpa user sebagai anonim (`core/auth/authentication.py`), jadi
 * "diizinkan masuk" hanya menghasilkan halaman kosong (semua API 401/403).
 *
 * Strukturnya dipisah tiga lapis supaya bisa diuji tanpa DOM/router:
 *  - `guardDecision()` (`lib/auth-guard.ts`) + `deviceModeFor()` (`lib/device-mode.ts`)
 *    + `loginRedirectPath()` (`lib/login-form.ts`) = fungsi PURE;
 *  - `AuthGate`/`AuthLoading` = presentasional (props in, elemen out → `renderToString`).
 *
 * `AuthProvider`-nya sendiri dipasang SEKALI di `App.tsx` (bukan di dalam komponen ini)
 * karena `TopBar` berada di App Shell yang membungkus `<Routes>` — lihat docstring
 * `hooks/useAuth.tsx`.
 */

/** Tampilan saat sesi sedang diperiksa (`data-auth-loading` = penanda test). */
export function AuthLoading() {
  return (
    <div
      data-auth-loading="true"
      className="flex min-h-screen items-center justify-center p-8"
    >
      <Spinner size="lg" />
    </div>
  );
}

interface AuthGateProps {
  decision: GuardDecision;
  /** URL login (sudah termasuk `?redirect=`). */
  redirectTo: string;
  children: ReactNode;
}

/** Presentasional — menerjemahkan keputusan menjadi elemen. */
export function AuthGate({ decision, redirectTo, children }: AuthGateProps) {
  if (decision === 'loading') return <AuthLoading />;
  if (decision === 'redirect') return <Navigate to={redirectTo} replace />;

  return <>{children}</>;
}

interface AuthGuardProps {
  children: ReactNode;
}

/** Gerbang siap pakai: butuh `<AuthProvider>` + Router di atasnya. */
export function AuthGuard({ children }: AuthGuardProps) {
  const device = useDeviceMode();
  const location = useLocation();

  // F6.4 — satu sumber state: `useDeviceMode()` sudah menggabungkan probe `/devices/me`
  // (cookie device) + sesi `AuthProvider` (`/auth/me`), jadi TIDAK perlu `useAuth()` lagi.
  // FIX ROUTE: `device.bound` sengaja TIDAK dikirim — bukti boleh-masuk hanya `user`.
  const decision = guardDecision({
    loading: device.loading,
    user: device.user,
  });
  // Halaman yang sedang dibuka dibawa ke `?redirect=` supaya setelah login user kembali ke
  // halaman itu (bukan selalu /dashboard).
  const redirectTo = loginRedirectPath(location.pathname, location.search);

  return (
    <AuthGate decision={decision} redirectTo={redirectTo}>
      {children}
    </AuthGate>
  );
}
