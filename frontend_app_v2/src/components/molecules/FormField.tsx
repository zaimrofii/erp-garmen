import type { ReactNode } from 'react';
import { cn } from '@/lib/cn';

/**
 * FormField - pembungkus label + kontrol + pesan error.
 * Dipakai saat kontrol bukan atom yang sudah punya label sendiri (`Input`/`Select`/
 * `Textarea` sudah punya). `htmlFor` harus sama dengan id kontrol di dalam `children`.
 */

interface FormFieldProps {
  label: string;
  error?: string;
  required?: boolean;
  children: ReactNode;
  htmlFor?: string;
  className?: string;
}

export function FormField({ label, error, required = false, children, htmlFor, className }: FormFieldProps) {
  return (
    <div className={cn('flex flex-col gap-1', className)}>
      <label htmlFor={htmlFor} className="text-xs font-medium text-muted-foreground">
        {label}
        {required ? (
          <span className="ml-1 text-accent-coral" aria-hidden="true">
            *
          </span>
        ) : null}
      </label>

      {children}

      {error !== undefined ? (
        <p className="text-xs text-accent-coral" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}
