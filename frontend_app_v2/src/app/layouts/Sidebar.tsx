import { AppSidebar } from '@/components/molecules/AppSidebar';
import { DUMMY_USER } from '@/app/dummy-user';
import { findAppByPath } from '@/app/nav-config';
import { useVisibleApps } from '@/app/useRole';

/**
 * Sidebar.tsx (layout) - pembungkus `AppSidebar` molecule.
 *
 * Tugasnya hanya 3 hal: ambil app yang BOLEH dilihat role aktif (`useVisibleApps`),
 * tentukan app aktif dari pathname (`findAppByPath`), lalu serahkan ke molecule.
 * Molecule tetap presentational (tidak tahu router maupun role).
 */

interface SidebarProps {
  currentPath: string;
  onNavigate: (path: string) => void;
}

export function Sidebar({ currentPath, onNavigate }: SidebarProps) {
  const visibleApps = useVisibleApps();
  const activeApp = findAppByPath(currentPath);

  return (
    <AppSidebar
      items={visibleApps}
      activeId={activeApp?.id ?? ''}
      onNavigate={onNavigate}
      user={{ initials: DUMMY_USER.initials, label: DUMMY_USER.name }}
    />
  );
}
