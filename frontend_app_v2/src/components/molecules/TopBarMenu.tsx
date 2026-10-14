import { cn } from '@/lib/cn';
import { PILL } from '@/lib/tokens';

/**
 * TopBarMenu - menu kontekstual per aplikasi (kanan atas sidebar, gaya Odoo).
 * Dipakai AppShell Fase 16; daftar menunya datang dari `app/nav-config.ts`.
 */

export interface TopBarMenuItem {
  label: string;
  path: string;
}

interface TopBarMenuProps {
  menus: TopBarMenuItem[];
  activePath: string;
  onNavigate: (path: string) => void;
  className?: string;
}

export function TopBarMenu({ menus, activePath, onNavigate, className }: TopBarMenuProps) {
  return (
    <nav className={cn('flex flex-wrap items-center gap-1', className)}>
      {menus.map((menu) => {
        const isActive = menu.path === activePath;

        return (
          <button
            key={menu.path}
            type="button"
            onClick={() => onNavigate(menu.path)}
            aria-current={isActive ? 'page' : undefined}
            className={cn(
              PILL,
              'px-3 py-1.5 text-sm font-medium',
              isActive
                ? 'bg-primary text-primary-foreground shadow-pill'
                : 'text-muted-foreground hover:bg-muted hover:text-foreground',
            )}
          >
            {menu.label}
          </button>
        );
      })}
    </nav>
  );
}
