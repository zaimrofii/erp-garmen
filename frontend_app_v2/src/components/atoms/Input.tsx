import { useId, type InputHTMLAttributes, type Ref } from 'react';
import type { LucideIcon } from 'lucide-react';
import { cn } from '@/lib/cn';

/**
 * Input - atom input teks (Visual Design System v1.0 bagian 2.2).
 *
 * WAJIB label + id: kalau pemanggil tidak mengirim `id`, atom membuatnya sendiri
 * lewat `useId()` sehingga `<label htmlFor>` selalu terhubung ke `<input>`.
 * `ref` diterima sebagai prop biasa (React 19) supaya `ScanInput` bisa auto-focus.
 */

const BASE_INPUT =
  'w-full rounded-lg border border-input bg-card px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:opacity-50';

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  error?: string;
  icon?: LucideIcon;
  ref?: Ref<HTMLInputElement>;
}

export function Input({ label, error, icon: Icon, id, className, ref, ...rest }: InputProps) {
  const generatedId = useId();
  const inputId = id ?? generatedId;
  const hasError = error !== undefined;

  return (
    <div className="w-full">
      {label !== undefined ? (
        <label htmlFor={inputId} className="mb-1 block text-xs font-medium text-muted-foreground">
          {label}
        </label>
      ) : null}

      <div className="relative">
        {Icon !== undefined ? (
          <Icon
            className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
            aria-hidden="true"
          />
        ) : null}

        <input
          {...rest}
          ref={ref}
          id={inputId}
          aria-invalid={hasError || undefined}
          className={cn(
            BASE_INPUT,
            Icon !== undefined ? 'pl-9' : undefined,
            hasError ? 'border-accent-coral' : undefined,
            className,
          )}
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
