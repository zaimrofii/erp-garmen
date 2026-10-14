import { Factory, type LucideIcon } from 'lucide-react';
import { cn } from '@/lib/cn';

/**
 * AppSidebar - rel ikon aplikasi (sisi kiri, gaya Odoo).
 * Dipakai AppShell Fase 16; di layar < `lg` tersembunyi (navigasi HP pakai TopBar).
 * Setiap tombol ikon punya `aria-label` + tooltip melayang saat hover/focus.
 *
 * Catatan Fase 16: kaki sidebar menampilkan avatar inisial user (prop opsional `user`).
 * Teks avatar memakai token `text-primary-foreground`, BUKAN warna putih literal dari
 * referensi (palet bawaan Tailwind dilarang Aturan Mutlak #1).
 */

export interface SidebarItem {
  id: string;
  label: string;
  icon: LucideIcon;
  path: string;
}

/** Avatar user di kaki sidebar (inisial + label untuk tooltip/title). */
export interface SidebarUser {
  initials: string;
  label: string;
}

interface AppSidebarProps {
  items: SidebarItem[];
  activeId: string;
  onNavigate: (path: string) => void;
  /** Opsional - kalau diisi, avatar inisial tampil di kaki sidebar. */
  user?: SidebarUser;
  className?: string;
}

export function AppSidebar({ items, activeId, onNavigate, user, className }: AppSidebarProps) {
  return (
    <aside
      className={cn(
        'hidden w-16 shrink-0 bg-transparent lg:sticky lg:top-0 lg:z-50 lg:flex lg:h-screen lg:flex-col lg:items-center md:mx-4',
        className,
      )}
    >
      <div className="pb-2 pt-4">
        <div className="flex h-11 w-11 items-center justify-center rounded-full bg-primary text-primary-foreground">
          <Factory className="h-5 w-5" aria-hidden="true" />
        </div>
      </div>

      <nav className="flex flex-1 flex-col items-center gap-2 overflow-visible py-4">
        {items.map((item) => {
          const Icon = item.icon;
          const isActive = item.id === activeId;

          return (
            <div key={item.id} className="group relative">
              <button
                type="button"
                onClick={() => onNavigate(item.path)}
                aria-label={item.label}
                aria-current={isActive ? 'page' : undefined}
                className={cn(
                  'flex h-11 w-11 items-center justify-center rounded-full transition-colors',
                  isActive
                    ? 'bg-primary/5 text-primary'
                    : 'bg-card text-muted-foreground hover:bg-primary/5 hover:text-foreground',
                )}
              >
                <Icon className="h-5 w-5 shrink-0" strokeWidth={1.5} aria-hidden="true" />
              </button>

              <span
                role="tooltip"
                className="pointer-events-none absolute left-full top-1/2 z-50 ml-2 -translate-y-1/2 scale-95 whitespace-nowrap rounded-md bg-popover px-2.5 py-1.5 text-xs font-medium text-popover-foreground opacity-0 shadow-pill transition-opacity duration-150 group-hover:scale-100 group-hover:opacity-100 group-focus-within:scale-100 group-focus-within:opacity-100"
              >
                {item.label}
              </span>
            </div>
          );
        })}
      </nav>

      {user !== undefined ? (
        <div className="pb-4">
          <div
            role="img"
            aria-label={user.label}
            title={user.label}
            className="flex h-9 w-9 items-center justify-center rounded-full bg-accent-blue text-[11px] font-semibold text-primary-foreground"
          >
            {user.initials}
          </div>
        </div>
      ) : null}
    </aside>
  );
}
