import { Dropdown, type DropdownItem } from '@/components/atoms/Dropdown';
import { findMenuItemPath, type MenuItem } from '@/app/menu-config';
import { cn } from '@/lib/cn';
import { PILL } from '@/lib/tokens';

/**
 * AppMenuBar.tsx (organism) — **menu DALAM app yang sedang aktif** (TopBar).
 *
 * F16 (fix F5): sebelumnya komponen ini menerima `menus: MenuApp[]` (satu entry per APP,
 * dipanggil `TopBar` dengan daftar app yang boleh dilihat role) sehingga TopBar menampilkan
 * ULANG daftar app = duplikat `Sidebar`. Sekarang kontraknya `items: MenuItem[]` — irisan
 * `NavApp.topbar` milik app AKTIF (mis. Inventory → Products/Operations/Reporting/Configuration).
 *
 * Aturan render (keputusan user):
 *  - item **tanpa** `children` → dirender sebagai **link** (`<button>` + `aria-current`), BUKAN dropdown;
 *  - item **dengan** `children` → `<Dropdown>` (atom F5), isi = anak-anaknya (`Products ▾ → List | New`).
 *
 * Komponen tetap presentational: navigasi diserahkan ke `onNavigate` (router-agnostic);
 * warna HANYA token OKLCH (`PILL`, `bg-primary`, `hover:bg-muted`).
 */

interface AppMenuBarProps {
  /** Menu milik app aktif (`NavApp.topbar`) — BUKAN daftar app. */
  items: readonly MenuItem[];
  currentPath: string;
  onNavigate: (path: string) => void;
  className?: string;
}

/** Anak menu → item `Dropdown` (id = path supaya `onSelect` mudah dipetakan balik). */
function toDropdownItems(children: readonly MenuItem[]): DropdownItem[] {
  return children.map((child) => ({
    id: child.path ?? child.id ?? child.label,
    label: child.label,
    ...(child.disabled === true ? { disabled: true } : {}),
    ...(child.hint === undefined ? {} : { hint: child.hint }),
  }));
}

export function AppMenuBar({ items, currentPath, onNavigate, className }: AppMenuBarProps) {
  return (
    <nav
      role="menubar"
      aria-label="Menu aplikasi"
      data-app-menu-bar="true"
      className={cn('flex flex-wrap items-center gap-1', className)}
    >
      {items.map((item) => {
        const key = item.path ?? item.id ?? item.label;
        const children = item.children ?? [];

        if (children.length > 0) {
          const activeChildPath = findMenuItemPath(item, currentPath);

          return (
            <Dropdown
              key={key}
              label={item.label}
              items={toDropdownItems(children)}
              {...(activeChildPath === undefined ? {} : { activeId: activeChildPath })}
              onSelect={(id) => {
                const child = children.find(
                  (candidate) => (candidate.path ?? candidate.id ?? candidate.label) === id,
                );
                if (child?.path === undefined) return;

                onNavigate(child.path);
              }}
            />
          );
        }

        const isActive = findMenuItemPath(item, currentPath) !== undefined;

        return (
          <button
            key={key}
            type="button"
            role="menuitem"
            aria-current={isActive ? 'page' : undefined}
            disabled={item.disabled === true}
            onClick={() => {
              if (item.path === undefined) return;
              onNavigate(item.path);
            }}
            className={cn(
              PILL,
              'px-3 py-1.5 text-sm font-medium transition-colors',
              'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2',
              isActive
                ? 'bg-primary text-primary-foreground shadow-pill'
                : 'text-muted-foreground hover:bg-muted hover:text-foreground',
              item.disabled === true && 'cursor-not-allowed opacity-70',
            )}
          >
            {item.label}
          </button>
        );
      })}
    </nav>
  );
}
