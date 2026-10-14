import type { ButtonHTMLAttributes, ReactNode } from 'react';
import { Loader2, type LucideIcon } from 'lucide-react';
import { cn } from '@/lib/cn';
import { PILL } from '@/lib/tokens';

/**
 * Button - atom tombol (Visual Design System v1.0 bagian 2.1).
 *
 * Warna HANYA dari token OKLCH (`bg-primary`, `bg-accent-coral`, `border-border`,
 * `bg-muted`) - tanpa hex/rgb/palet bawaan Tailwind, tanpa utility varian tema gelap.
 * Base memakai token `PILL` (sudah termasuk `rounded-pill` + `transition-colors`).
 */

export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger';
export type ButtonSize = 'sm' | 'md' | 'lg';

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
  icon?: LucideIcon;
  /** Opsional supaya tombol ikon murni bisa dibuat - WAJIB diberi `aria-label`. */
  children?: ReactNode;
}

const VARIANT_CLASS: Record<ButtonVariant, string> = {
  primary: 'bg-primary text-primary-foreground shadow-pill hover:opacity-90',
  secondary: 'border border-border/80 bg-card hover:bg-muted',
  ghost: 'text-muted-foreground hover:text-foreground hover:bg-muted/50',
  danger: 'bg-accent-coral text-primary-foreground hover:opacity-90',
};

const SIZE_CLASS: Record<ButtonSize, string> = {
  sm: 'min-h-9 px-3 py-1.5 text-xs',
  md: 'min-h-10 px-4 py-2 text-sm',
  lg: 'min-h-12 px-5 py-3 text-base',
};

const BASE =
  'font-semibold tracking-tight focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:opacity-50 disabled:cursor-not-allowed';

export function Button({
  variant = 'primary',
  size = 'md',
  loading = false,
  icon: Icon,
  type = 'button',
  disabled = false,
  className,
  children,
  ...rest
}: ButtonProps) {
  const isDisabled = disabled || loading;

  return (
    <button
      {...rest}
      type={type}
      disabled={isDisabled}
      aria-busy={loading || undefined}
      className={cn(PILL, BASE, VARIANT_CLASS[variant], SIZE_CLASS[size], className)}
    >
      {loading ? (
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
      ) : Icon !== undefined ? (
        <Icon className="h-4 w-4" aria-hidden="true" />
      ) : null}
      {children}
    </button>
  );
}
