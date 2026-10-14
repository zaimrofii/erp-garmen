import { Loader2 } from 'lucide-react';
import { cn } from '@/lib/cn';

/**
 * Spinner - indikator memuat (Visual Design System v1.0 bagian 2.8).
 * `role="status"` + `aria-label` supaya screen reader tahu ada proses berjalan.
 */

export type SpinnerSize = 'sm' | 'md' | 'lg';

const SIZE_CLASS: Record<SpinnerSize, string> = {
  sm: 'h-4 w-4',
  md: 'h-6 w-6',
  lg: 'h-8 w-8',
};

interface SpinnerProps {
  size?: SpinnerSize;
  className?: string;
}

export function Spinner({ size = 'md', className }: SpinnerProps) {
  return (
    <Loader2
      role="status"
      aria-label="Memuat"
      className={cn('animate-spin text-muted-foreground', SIZE_CLASS[size], className)}
    />
  );
}
