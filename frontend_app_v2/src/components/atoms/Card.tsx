import type { ReactNode } from 'react';
import { cn } from '@/lib/cn';
import { CARD } from '@/lib/tokens';

/**
 * Card - permukaan kaca (Visual Design System v1.0 bagian 2.6).
 * Selalu memakai token `CARD` (`glass-card rounded-card p-6`) supaya semua kartu
 * seragam; judul/konten spesifik ditulis pemanggil di dalam `children`.
 */

export type CardTag = 'article' | 'section' | 'div';

interface CardProps {
  as?: CardTag;
  className?: string;
  children: ReactNode;
}

export function Card({ as: Tag = 'div', className, children }: CardProps) {
  return <Tag className={cn(CARD, className)}>{children}</Tag>;
}
