import type { ReactNode } from 'react';
import type { LucideIcon } from 'lucide-react';
import { cn } from '@/lib/cn';
import { BADGE } from '@/lib/tokens';

/**
 * Badge - label status ringkas (Visual Design System v1.0 bagian 2.4).
 * Selalu sertakan teks - warna saja tidak boleh jadi satu-satunya pembawa makna.
 */

export type BadgeTone = 'blue' | 'coral' | 'muted' | 'default';

const TONE_CLASS: Record<BadgeTone, string> = {
  blue: 'bg-accent-blue/10 text-accent-blue border border-accent-blue/20',
  coral: 'bg-accent-coral/10 text-accent-coral border border-accent-coral/20',
  muted: 'bg-muted text-muted-foreground',
  default: 'bg-primary/10 text-primary',
};

interface BadgeProps {
  tone?: BadgeTone;
  icon?: LucideIcon;
  children: ReactNode;
  className?: string;
}

export function Badge({ tone = 'default', icon: Icon, children, className }: BadgeProps) {
  return (
    <span className={cn(BADGE, TONE_CLASS[tone], className)}>
      {Icon !== undefined ? <Icon className="h-3 w-3" aria-hidden="true" /> : null}
      {children}
    </span>
  );
}
