import { Kanban, LayoutGrid, List, type LucideIcon } from 'lucide-react';
import { Button } from '@/components/atoms/Button';
import { cn } from '@/lib/cn';
import { persistViewMode, VIEW_MODE_LABELS, type ViewMode } from '@/lib/view-mode';

/**
 * ViewToggle - pemilih mode tampilan halaman list (FASE K3): list | grid | kanban.
 *
 * Kontrol TERKENDALI (`value` + `onChange`) supaya halaman tetap pemilik state, tetapi
 * memori user disimpan di sini: klik -> `localStorage[storageKey] = mode` lalu
 * `onChange`. Nilai tersimpan dibaca halaman lewat `readViewMode()` (helper yang sama).
 *
 * Aksesibilitas: `role="group"` + `aria-label` grup, setiap tombol punya `aria-label`
 * ("Mode List/Grid/Kanban") dan `aria-pressed` (mode aktif) - ikon saja tidak cukup.
 */

export interface ViewToggleProps {
  modes: readonly ViewMode[];
  value: ViewMode;
  onChange: (mode: ViewMode) => void;
  /** Kunci localStorage (mis. `mes-view-bundles`); tanpa ini preferensi tidak disimpan. */
  storageKey?: string;
  label?: string;
  className?: string;
}

const MODE_ICON: Record<ViewMode, LucideIcon> = {
  list: List,
  grid: LayoutGrid,
  kanban: Kanban,
};

export function ViewToggle({
  modes,
  value,
  onChange,
  storageKey,
  label = 'Mode tampilan',
  className,
}: ViewToggleProps) {
  function handleSelect(mode: ViewMode): void {
    if (storageKey !== undefined) persistViewMode(storageKey, mode);
    if (mode !== value) onChange(mode);
  }

  return (
    <div
      role="group"
      aria-label={label}
      className={cn('flex flex-wrap items-center gap-1', className)}
    >
      {modes.map((mode) => {
        const Icon = MODE_ICON[mode];
        const isActive = mode === value;

        return (
          <Button
            key={mode}
            size="sm"
            variant={isActive ? 'secondary' : 'ghost'}
            icon={Icon}
            aria-label={`Mode ${VIEW_MODE_LABELS[mode]}`}
            aria-pressed={isActive}
            onClick={() => handleSelect(mode)}
          >
            {VIEW_MODE_LABELS[mode]}
          </Button>
        );
      })}
    </div>
  );
}
