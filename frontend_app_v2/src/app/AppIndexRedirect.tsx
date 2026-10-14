import type { ReactNode } from 'react';
import { Navigate } from 'react-router-dom';
import { AccessDenied } from '@/app/AccessDenied';
import { appLandingPath, findAppById } from '@/app/nav-config';
import { useCurrentPath } from '@/app/use-current-path';
import { isAppAllowed, useRole } from '@/app/useRole';

/**
 * AppIndexRedirect.tsx — route "indeks app" (FIX ROUTE).
 *
 * `NAV_APPS[].path` untuk app dengan menu (Production, Inventory, Purchase, Quality,
 * Reports, Settings, Finance) hanyalah **prefix**, bukan route (lihat catatan di
 * `menu-config.ts`). Sebelumnya klik ikon app di Sidebar mendarat di path prefix itu →
 * tidak ada route yang cocok → `RoleGuardFallback` (404/redirect) → user melihat "halaman
 * kosong". Route indeks ini menerjemahkan prefix ke **halaman pertama app** (menu pertama
 * `topbar`), sehingga URL manual (`/production`) dan klik Sidebar sama-sama mendarat benar.
 *
 * Urutan keputusan: role tidak berhak atas app-nya → "Akses Ditolak" (bukan redirect diam);
 * app belum punya halaman → pesan jelas; selain itu → redirect ke halaman pertama.
 */

export const APP_LANDING_MISSING_MESSAGE = 'App ini belum punya halaman.';

interface AppLandingMissingProps {
  /** Id app (mis. `production`). */
  app: string;
}

/** Presentasional — app tanpa menu/halaman sama sekali. */
export function AppLandingMissing({ app }: AppLandingMissingProps): ReactNode {
  return (
    <div
      data-app-landing-missing={app}
      className="flex min-h-[60vh] flex-col items-center justify-center gap-2 p-4 text-center"
    >
      <h1 className="text-xl font-bold tracking-tight text-foreground">
        {APP_LANDING_MISSING_MESSAGE}
      </h1>
      <p className="text-sm text-muted-foreground">
        App “{app}” belum memiliki halaman yang bisa dibuka.
      </p>
    </div>
  );
}

interface AppIndexRedirectProps {
  /** Id app dari `NAV_APPS` (mis. `production`). */
  app: string;
}

/** Route indeks app: `/production` → menu pertama Production (`/production/scan`). */
export function AppIndexRedirect({ app }: AppIndexRedirectProps): ReactNode {
  const role = useRole();
  const [pathname] = useCurrentPath();
  const target = appLandingPath(findAppById(app));

  if (!isAppAllowed(role, app)) return <AccessDenied />;

  // Defensif: app tanpa menu, atau path yang sudah menjadi halaman pertama itu sendiri.
  if (target === undefined || target === pathname) return <AppLandingMissing app={app} />;

  return <Navigate to={target} replace />;
}
