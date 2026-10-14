import { useId, type InputHTMLAttributes } from 'react';
import { cn } from '@/lib/cn';

/**
 * Checkbox - atom centang (mis. "saya sudah cek fisik bundle").
 * `label` opsional; kalau kosong, pemanggil tetap bisa mengirim `aria-label`
 * lewat `...rest` supaya kontrol tidak tanpa nama (a11y).
 */

interface CheckboxProps
  extends Omit<InputHTMLAttributes<HTMLInputElement>, 'type' | 'checked' | 'defaultChecked'> {
  label?: string;
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
}

export function Checkbox({ label, checked, onCheckedChange, id, className, ...rest }: CheckboxProps) {
  const generatedId = useId();
  const inputId = id ?? generatedId;

  return (
    <div className={cn('flex items-center gap-2', className)}>
      <input
        {...rest}
        id={inputId}
        type="checkbox"
        checked={checked}
        onChange={(event) => onCheckedChange(event.target.checked)}
        className="h-4 w-4 shrink-0 rounded-sm border border-input accent-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:opacity-50"
      />
      {label !== undefined ? (
        <label htmlFor={inputId} className="text-sm text-foreground">
          {label}
        </label>
      ) : null}
    </div>
  );
}
