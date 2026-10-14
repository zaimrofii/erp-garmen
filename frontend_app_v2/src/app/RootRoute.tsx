import type { ReactNode } from 'react';
import { Navigate } from 'react-router-dom';
import { AccessDenied } from '@/app/AccessDenied';
import { firstAllowedPathForRole, isAppAllowed, useRole } from '@/app/useRole';
import { AuthLoading } from '@/components/organisms/AuthGuard';
import { useDeviceMode } from '@/hooks/useDeviceMode';
import { loginRedirectPath } from '@/lib/login-form';
import { DashboardPage } from '@/pages/DashboardPage';

/**
 * RootRoute.tsx — komponen untuk route `/` (FIX ROUTE).
 *
 * Dulu `/` langsung merender `DashboardPage` (tanpa keputusan eksplisit) sehingga:
 *  - saat probe auth/device belum selesai halaman sudah tampil (padahal bisa saja user
 *    belum login) — sekarang **loading → spinner**;
 *  - user yang belum login hanya "kebetulan" tertahan `AuthGuard`. Sekarang keputusannya
 *    eksplisit di sini: belum ada sesi → `/login?redirect=/`.
 *
 * Anti-loop: user yang sudah login TAPI role-nya tidak punya app Dashboard (mis.
 * `inventory`, `purchasing`) diarahkan ke **halaman pertama app yang boleh ia buka**
 * (`firstAllowedPathForRole`) — BUKAN ke `/dashboard` (dijaga `SUPERVISOR_ROLES`, akan
 * memantul kembali) dan bukan ke `/` (loop ke dirinya sendiri).
 */

export function RootRoute(): ReactNode {
  const device = useDeviceMode();
  const role = useRole();

  // Jangan pernah memutuskan sebelum probe `/devices/me` + `/auth/me` selesai.
  if (device.loading) return <AuthLoading />;

  if (device.user === null) return <Navigate to={loginRedirectPath('/')} replace />;

  if (isAppAllowed(role, 'dashboard')) return <DashboardPage />;

  const landing = firstAllowedPathForRole(role);

  // Role tanpa app sama sekali (tidak ada di ROLE_APPS) → pesan jelas, bukan loop.
  if (landing === undefined) return <AccessDenied />;

  return <Navigate to={landing} replace />;
}
