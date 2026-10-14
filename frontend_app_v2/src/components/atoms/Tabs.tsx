import { cn } from '@/lib/cn';
import { PILL } from '@/lib/tokens';

/**
 * Tabs - pemilih segmen (mis. tab laporan vs tab konfigurasi).
 * Pola WAI-ARIA `tablist`/`tab`; panel-nya dirender pemanggil.
 */

export interface TabItem {
  id: string;
  label: string;
}

interface TabsProps {
  tabs: TabItem[];
  active: string;
  onChange: (id: string) => void;
  className?: string;
}

export function Tabs({ tabs, active, onChange, className }: TabsProps) {
  return (
    <div
      role="tablist"
      className={cn('flex gap-1 rounded-pill border border-border/80 bg-card p-1', className)}
    >
      {tabs.map((tab) => {
        const isActive = tab.id === active;

        return (
          <button
            key={tab.id}
            type="button"
            role="tab"
            aria-selected={isActive}
            onClick={() => onChange(tab.id)}
            className={cn(
              PILL,
              'px-3 py-1.5 text-sm font-medium',
              isActive
                ? 'bg-primary text-primary-foreground shadow-pill'
                : 'text-muted-foreground hover:text-foreground',
            )}
          >
            {tab.label}
          </button>
        );
      })}
    </div>
  );
}
