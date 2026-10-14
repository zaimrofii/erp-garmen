import { useId, type SelectHTMLAttributes } from 'react';
import { ChevronDown } from 'lucide-react';
import { cn } from '@/lib/cn';

/**
 * Select - atom dropdown (Visual Design System v1.0 bagian 2.2).
 * Chevron custom (`appearance-none`) supaya tampilan konsisten lintas browser,
 * posisinya absolut di kanan (`pointer-events-none` agar tetap bisa diklik ke select).
 */

export interface SelectOption {
  value: string;
  label: string;
}

const BASE_SELECT =
  'w-full rounded-lg border border-input bg-card px-3 py-2 text-sm text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:opacity-50';

interface SelectProps extends SelectHTMLAttributes<HTMLSelectElement> {
  label?: string;
  error?: string;
  options: SelectOption[];
}

export function Select({ label, error, options, id, className, ...rest }: SelectProps) {
  const generatedId = useId();
  const selectId = id ?? generatedId;
  const hasError = error !== undefined;

  return (
    <div className="w-full">
      {label !== undefined ? (
        <label htmlFor={selectId} className="mb-1 block text-xs font-medium text-muted-foreground">
          {label}
        </label>
      ) : null}

      <div className="relative">
        <select
          {...rest}
          id={selectId}
          aria-invalid={hasError || undefined}
          className={cn(
            'appearance-none pr-9',
            BASE_SELECT,
            hasError ? 'border-accent-coral' : undefined,
            className,
          )}
        >
          {options.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
        <ChevronDown
          className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
          aria-hidden="true"
        />
      </div>

      {hasError ? (
        <p className="mt-1 text-xs text-accent-coral" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}
