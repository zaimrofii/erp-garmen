import type { ReactNode } from 'react';
import { AccessDenied } from '@/app/AccessDenied';
import { findAppByPath } from '@/app/nav-config';
import { useCurrentPath } from '@/app/use-current-path';
import { isAppAllowed, useRole, type Role } from '@/app/useRole';
import { NotFoundPage } from '@/pages/NotFoundPage';

/**
 * RoleRoute - gerbang role level halaman (gate "tidak ada route bocor").
 *
 * FIX ROUTE: role yang tidak berhak kini melihat halaman **"Akses Ditolak"**
 * (`app/AccessDenied.tsx`) — dulu `RoleRoute` diam-diam `<Navigate to="/" />` sehingga user
 * merasa halamannya "hilang"/kosong tanpa penjelasan. Halaman itu juga punya tombol
 * "Kembali ke Dashboard" + auto-redirect 5 detik, jadi perilaku aman (tidak nyangkut) tetap
 * terjaga. Anti-loop tidak lagi bergantung pada redirect: `/` sendiri memakai `RootRoute`
 * yang memilih halaman sesuai role.
 */

interface RoleRouteProps {
  roles: Role[];
  children: ReactNode;
}

export function RoleRoute({ roles, children }: RoleRouteProps): ReactNode {
  const role = useRole();

  if (!roles.some((allowed) => allowed === role)) return <AccessDenied />;

  return <>{children}</>;
}

/**
 * Fallback route `*`:
 *  - path milik app yang TIDAK boleh dilihat role aktif (mis. operator membuka
 *    `/inventory/products`) -> halaman "Akses Ditolak" (FIX ROUTE, dulu redirect `/`);
 *  - path lain yang memang tidak dikenal -> `NotFoundPage`.
 */
export function RoleGuardFallback(): ReactNode {
  const role = useRole();
  const [pathname] = useCurrentPath();

  const app = findAppByPath(pathname);
  if (app !== undefined && !isAppAllowed(role, app.id)) return <AccessDenied />;

  return <NotFoundPage />;
}
