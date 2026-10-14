import { AnimatePresence, motion } from 'framer-motion';
import { AlertOctagon, CheckCircle2, Info, X, type LucideIcon } from 'lucide-react';
import { cn } from '@/lib/cn';
import { CARD, PILL_GHOST } from '@/lib/tokens';

/**
 * Toast - notifikasi ringkas (Visual Design System v1.0 bagian 2.9).
 * Muncul/keluar lewat `AnimatePresence` (Framer Motion) dan selalu bisa ditutup
 * manual. Pesan diumumkan ke screen reader (`role="status"` + `aria-live`).
 */

export type ToastTone = 'default' | 'success' | 'error';

const TONE_ICON: Record<ToastTone, LucideIcon> = {
  default: Info,
  success: CheckCircle2,
  error: AlertOctagon,
};

const TONE_ICON_CLASS: Record<ToastTone, string> = {
  default: 'text-accent-blue',
  success: 'text-accent-blue',
  error: 'text-accent-coral',
};

interface ToastProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: string;
  tone?: ToastTone;
}

export function Toast({ open, onOpenChange, title, description, tone = 'default' }: ToastProps) {
  const Icon = TONE_ICON[tone];

  return (
    <AnimatePresence>
      {open ? (
        <motion.div
          key="toast"
          role="status"
          aria-live="polite"
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: 12 }}
          transition={{ duration: 0.18 }}
          className={cn(CARD, 'fixed bottom-4 right-4 z-50 flex max-w-sm items-start gap-3')}
        >
          <Icon className={cn('h-4 w-4 shrink-0', TONE_ICON_CLASS[tone])} aria-hidden="true" />

          <div className="flex flex-col gap-0.5">
            <p className="text-sm font-semibold text-foreground">{title}</p>
            {description !== undefined ? (
              <p className="text-xs text-muted-foreground">{description}</p>
            ) : null}
          </div>

          <button
            type="button"
            onClick={() => onOpenChange(false)}
            aria-label="Tutup"
            className={cn(PILL_GHOST, 'ml-auto h-6 w-6 shrink-0 p-0')}
          >
            <X className="h-4 w-4" aria-hidden="true" />
          </button>
        </motion.div>
      ) : null}
    </AnimatePresence>
  );
}
