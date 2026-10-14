import type { ReactNode } from 'react';
import { Sidebar } from '@/app/layouts/Sidebar';
import { TopBar } from '@/app/layouts/TopBar';
import { useOffline } from '@/app/app-runtime';
import { findAppByPath, isImmersiveOperatorPath } from '@/app/nav-config';
import { isAppAllowed, useRole, useVisibleApps } from '@/app/useRole';
import { useCurrentPath } from '@/app/use-current-path';
import { BottomNav } from '@/components/molecules/BottomNav';
import { OfflineBanner } from '@/components/molecules/OfflineBanner';
import { cn } from '@/lib/cn';

/**
 * AppShell.tsx - kerangka Odoo-style (Blueprint v3 bagian 5.1).
 *
 *   [ rel ikon ]  [ TopBar: judul app + menu kontekstual + dark toggle + user ]
 *   [ Sidebar  ]  [ MAIN CONTENT (children = <Routes />) ]
 *
 * Gerbang role: `findAppByPath` menemukan app dari URL, lalu dicek ke `isAppAllowed`.
 * Kalau user mengetik URL app yang bukan haknya, TopBar TIDAK menampilkan judul/menu
 * app itu (gate "tidak ada route bocor"); penjagaan per-halaman ada di `app/RoleRoute.tsx`.
 *
 * Fase 17 - alur tugas operator (`isImmersiveOperatorPath`):
 *  - TopBar disembunyikan di bawah `lg` (halaman memakai header sendiri - Screen A);
 *  - BottomNav tidak dirender supaya tidak bertabrakan dengan action bar `fixed bottom`.
 *  - `OfflineBanner` global muncul di atas konten saat offline (satu queue dari context).
 *
 * Catatan deviasi 1 kelas dari blueprint: root TIDAK memakai `bg-background` karena
 * body sudah punya radial mesh gradient OKLCH di `styles/tailwind.css`; utility
 * `bg-background` bersifat opaque dan akan menutupinya (glass-card kehilangan efek).
 */

interface AppShellProps {
  children: ReactNode;
}

export function AppShell({ children }: AppShellProps) {
  const [pathname, navigate] = useCurrentPath();
  const role = useRole();
  const visibleApps = useVisibleApps();
  const { isOnline, pendingCount } = useOffline();

  const activeApp = findAppByPath(pathname);
  const authorizedApp =
    activeApp !== undefined && isAppAllowed(role, activeApp.id) ? activeApp : undefined;
  const immersive = isImmersiveOperatorPath(pathname);

  return (
    <div className="flex min-h-screen">
      <Sidebar currentPath={pathname} onNavigate={navigate} />

      <div className="flex flex-1 flex-col overflow-hidden">
        <div className={cn(immersive && 'hidden lg:block')}>
          <TopBar app={authorizedApp} currentPath={pathname} onNavigate={navigate} />
        </div>

        <main className="flex-1 overflow-y-auto">
          {!isOnline ? (
            <div className="px-4 pt-4 lg:px-6">
              <OfflineBanner pending={pendingCount} online={isOnline} />
            </div>
          ) : null}

          {children}
        </main>
      </div>

      {immersive ? null : (
        <BottomNav items={visibleApps} activeId={activeApp?.id ?? ''} onNavigate={navigate} />
      )}
    </div>
  );
}
