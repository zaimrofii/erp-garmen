import type { LucideIcon } from 'lucide-react';
import { cn } from '@/lib/cn';

/**
 * BottomNav - navigasi HP (sidebar disembunyikan di bawah `lg`).
 * Selalu `lg:hidden`; AppShell juga tidak merendernya di alur tugas operator supaya
 * tombol aksi besar tidak bertabrakan dengan navigasi.
 */

export interface BottomNavItem {
  id: string;
  label: string;
  icon: LucideIcon;
  path: string;
}

/** Fase 17: cukup 4-5 app pertama (tanpa drawer "More"). */
const MAX_ITEMS = 5;

interface BottomNavProps {
  items: BottomNavItem[];
  activeId: string;
  onNavigate: (path: string) => void;
  className?: string;
}

export function BottomNav({ items, activeId, onNavigate, className }: BottomNavProps) {
  const visibleItems = items.slice(0, MAX_ITEMS);

  if (visibleItems.length === 0) return null;

  return (
    <nav
      aria-label="Navigasi utama"
      className={cn(
        'fixed inset-x-0 bottom-0 z-40 flex items-center justify-around border-t border-border/40 bg-background/95 px-2 pb-[env(safe-area-inset-bottom)] pt-2 backdrop-blur lg:hidden',
        className,
      )}
    >
      {visibleItems.map((item) => {
        const Icon = item.icon;
        const isActive = item.id === activeId;

        return (
          <button
            key={item.id}
            type="button"
            onClick={() => onNavigate(item.path)}
            aria-current={isActive ? 'page' : undefined}
            aria-label={item.label}
            className={cn(
              'flex flex-col items-center gap-1 rounded-pill px-3 py-2 transition-colors',
              'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2',
              isActive ? 'text-primary' : 'text-muted-foreground',
            )}
          >
            <Icon className="h-5 w-5" strokeWidth={1.5} aria-hidden="true" />
            <span className="text-[10px] font-medium">{item.label}</span>
          </button>
        );
      })}
    </nav>
  );
}
