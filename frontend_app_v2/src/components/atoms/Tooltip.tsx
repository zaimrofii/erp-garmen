import type { ReactNode } from 'react';
import { cn } from '@/lib/cn';

/**
 * Tooltip - label melayang untuk elemen ringkas (mis. sidebar ikon).
 *
 * Catatan rule animasi: utility transisi semua-properti dilarang, jadi transisi
 * memakai `transition-opacity` (skala muncul seketika, properti lain tidak ikut
 * ter-animasi). Muncul juga saat elemen di dalamnya menerima fokus keyboard.
 */

interface TooltipProps {
  content: string;
  children: ReactNode;
  className?: string;
}

export function Tooltip({ content, children, className }: TooltipProps) {
  return (
    <span className={cn('group relative inline-flex', className)}>
      {children}
      <span
        role="tooltip"
        className="pointer-events-none absolute left-full top-1/2 z-50 ml-2 -translate-y-1/2 scale-95 whitespace-nowrap rounded-md bg-popover px-2.5 py-1.5 text-xs font-medium text-popover-foreground opacity-0 shadow-pill transition-opacity duration-150 group-hover:scale-100 group-hover:opacity-100 group-focus-within:scale-100 group-focus-within:opacity-100"
      >
        {content}
      </span>
    </span>
  );
}
