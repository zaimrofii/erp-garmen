import { useCallback, useEffect, useId, useRef, useState, type KeyboardEvent } from 'react';
import { ChevronDown, type LucideIcon } from 'lucide-react';
import {
  firstEnabledIndex,
  isCloseKey,
  resolveSelection,
  stepFocusIndex,
  stepForKey,
} from '@/lib/dropdown-state';
import { cn } from '@/lib/cn';
import { PILL } from '@/lib/tokens';

/**
 * Dropdown - atom menu dropdown yang ACCESSIBLE (F5, menu bar Odoo-style).
 *
 * Aksesibilitas:
 *  - trigger: `aria-haspopup="menu"` + `aria-expanded` + `aria-controls` (saat terbuka);
 *  - menu: `role="menu"` + item `role="menuitem"`, item `disabled` juga `aria-disabled`;
 *  - keyboard: `Escape` menutup, `ArrowDown`/`ArrowUp` memindah fokus (item disabled
 *    dilewati, wrap), `Enter`/`Space` memilih item yang sedang difokuskan;
 *  - klik di luar menutup menu (listener `mousedown` hanya saat terbuka);
 *  - `focus-visible:ring-*` di trigger & item; warna HANYA token OKLCH
 *    (`bg-popover`, `border-border`, `ring-ring`, `bg-muted`).
 *
 * `defaultOpen` = seam test: `react-dom/server` tidak menjalankan klik, jadi struktur
 * menu terbuka diuji dengan prop ini (tanpa DOM/jsdom).
 */

export interface DropdownItem {
  id: string;
  label: string;
  icon?: LucideIcon;
  /** Item placeholder (mis. app yang belum punya halaman) - tidak bisa diklik. */
  disabled?: boolean;
  /** Penjelasan singkat kenapa item disabled (ditampilkan kecil di sebelah label). */
  hint?: string;
}

interface DropdownProps {
  label: string;
  items: DropdownItem[];
  onSelect?: (id: string) => void;
  /** Id item aktif (highlight + `aria-current="page"`). */
  activeId?: string;
  align?: 'start' | 'end';
  className?: string;
  /** Seam test - render langsung terbuka. */
  defaultOpen?: boolean;
}

const TRIGGER_BASE =
  'gap-2 border px-3 py-1.5 text-sm font-semibold tracking-tight focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2';

const ITEM_BASE =
  'w-full justify-start gap-2 px-3 py-2 text-sm font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset disabled:opacity-50 disabled:cursor-not-allowed';

export function Dropdown({
  label,
  items,
  onSelect,
  activeId,
  align = 'start',
  className,
  defaultOpen = false,
}: DropdownProps) {
  const [open, setOpen] = useState(defaultOpen);
  const [focusIndex, setFocusIndex] = useState(() => firstEnabledIndex(items));
  const containerRef = useRef<HTMLDivElement>(null);
  const menuId = useId();

  const activeItem = items.find((item) => item.id === activeId);

  const closeMenu = useCallback((): void => {
    setOpen(false);
  }, []);

  const openMenu = useCallback((): void => {
    setFocusIndex(firstEnabledIndex(items));
    setOpen(true);
  }, [items]);

  useEffect(() => {
    if (!open) return undefined;

    function handlePointerDown(event: MouseEvent): void {
      const container = containerRef.current;
      if (container === null) return;
      if (event.target instanceof Node && !container.contains(event.target)) setOpen(false);
    }

    document.addEventListener('mousedown', handlePointerDown);

    return () => document.removeEventListener('mousedown', handlePointerDown);
  }, [open]);

  function handleTriggerClick(): void {
    if (open) {
      closeMenu();
      return;
    }

    openMenu();
  }

  function handleTriggerKeyDown(event: KeyboardEvent<HTMLButtonElement>): void {
    if (stepForKey(event.key) === 1) {
      event.preventDefault();
      openMenu();
      return;
    }

    if (isCloseKey(event.key)) closeMenu();
  }

  function handleMenuKeyDown(event: KeyboardEvent<HTMLDivElement>): void {
    if (isCloseKey(event.key)) {
      event.preventDefault();
      closeMenu();
      return;
    }

    const direction = stepForKey(event.key);
    if (direction !== 0) {
      event.preventDefault();
      setFocusIndex((current) => stepFocusIndex(items, current, direction));
      return;
    }

    if (event.key !== 'Enter' && event.key !== ' ') return;

    event.preventDefault();
    const selected = resolveSelection(items, focusIndex);
    if (selected === null) return;

    onSelect?.(selected);
    closeMenu();
  }

  return (
    <div
      ref={containerRef}
      className={cn('relative', className)}
      data-dropdown={label}
      onKeyDown={handleMenuKeyDown}
    >
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        {...(open ? { 'aria-controls': menuId } : {})}
        {...(activeItem === undefined ? {} : { 'aria-current': 'page' as const })}
        data-dropdown-trigger={label}
        onClick={handleTriggerClick}
        onKeyDown={handleTriggerKeyDown}
        className={cn(
          PILL,
          TRIGGER_BASE,
          activeItem === undefined
            ? 'border-border/80 bg-card text-foreground hover:bg-muted'
            : 'border-transparent bg-primary text-primary-foreground shadow-pill',
        )}
      >
        <span className="truncate">{label}</span>
        <ChevronDown className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
      </button>

      {open ? (
        <ul
          id={menuId}
          role="menu"
          aria-label={label}
          data-dropdown-menu={label}
          className={cn(
            'absolute z-30 mt-2 flex min-w-48 flex-col gap-1 rounded-card border border-border/80 bg-popover p-1 shadow-soft-card',
            align === 'end' ? 'right-0' : 'left-0',
          )}
        >
          {items.map((item, index) => {
            const Icon = item.icon;

            return (
              <li key={item.id} role="none">
                <button
                  type="button"
                  role="menuitem"
                  disabled={item.disabled === true}
                  {...(item.disabled === true ? { 'aria-disabled': true } : {})}
                  {...(item.id === activeId ? { 'aria-current': 'page' as const } : {})}
                  data-menu-item={item.id}
                  {...(index === focusIndex ? { 'data-focused': 'true' } : {})}
                  onClick={() => {
                    if (item.disabled === true) return;
                    onSelect?.(item.id);
                    closeMenu();
                  }}
                  className={cn(
                    PILL,
                    ITEM_BASE,
                    item.id === activeId
                      ? 'bg-primary text-primary-foreground'
                      : 'text-foreground hover:bg-muted',
                  )}
                >
                  {Icon === undefined ? null : <Icon className="h-4 w-4 shrink-0" aria-hidden="true" />}
                  <span className="truncate">{item.label}</span>
                  {item.hint === undefined ? null : (
                    <span className="ml-auto text-[11px] font-normal text-muted-foreground">
                      {item.hint}
                    </span>
                  )}
                </button>
              </li>
            );
          })}
        </ul>
      ) : null}
    </div>
  );
}
