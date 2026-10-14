import { useId, type TextareaHTMLAttributes } from 'react';
import { cn } from '@/lib/cn';

/**
 * Textarea - atom catatan panjang (mis. alasan rework/scrap).
 * Pola sama dengan `Input`: label + id (`useId()`) + pesan error di bawah.
 */

const BASE_TEXTAREA =
  'w-full resize-none rounded-lg border border-input bg-card px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:opacity-50';

interface TextareaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  label?: string;
  error?: string;
}

export function Textarea({ label, error, id, className, rows = 4, ...rest }: TextareaProps) {
  const generatedId = useId();
  const textareaId = id ?? generatedId;
  const hasError = error !== undefined;

  return (
    <div className="w-full">
      {label !== undefined ? (
        <label htmlFor={textareaId} className="mb-1 block text-xs font-medium text-muted-foreground">
          {label}
        </label>
      ) : null}

      <textarea
        {...rest}
        id={textareaId}
        rows={rows}
        aria-invalid={hasError || undefined}
        className={cn(BASE_TEXTAREA, hasError ? 'border-accent-coral' : undefined, className)}
      />

      {hasError ? (
        <p className="mt-1 text-xs text-accent-coral" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}
