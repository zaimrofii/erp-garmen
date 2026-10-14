import { useEffect } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { haptic, playBeep, type BeepKind } from '@/lib/feedback';
import { cn } from '@/lib/cn';

/**
 * ActionFeedback - kedip layar + beep + getar untuk aksi operator.
 *
 * Dipasang sekali di level halaman/shell: set `active` true saat aksi selesai.
 * `useEffect` memicu `playBeep` + `haptic` tepat sekali per perubahan `active`,
 * sedangkan overlay-nya dianimasi `AnimatePresence` (opacity 0 -> 0.4 -> 0).
 */

export type ActionFeedbackKind = Extract<BeepKind, 'success' | 'error' | 'warning'>;

const FLASH_CLASS: Record<ActionFeedbackKind, string> = {
  success: 'bg-accent-blue',
  error: 'bg-accent-coral',
  warning: 'bg-accent-coral/60',
};

interface ActionFeedbackProps {
  kind: ActionFeedbackKind;
  active: boolean;
  className?: string;
}

export function ActionFeedback({ kind, active, className }: ActionFeedbackProps) {
  useEffect(() => {
    if (!active) return;

    playBeep(kind);
    haptic(kind === 'success' ? 'success' : 'error');
  }, [active, kind]);

  return (
    <AnimatePresence>
      {active ? (
        <motion.div
          key="action-feedback"
          aria-hidden="true"
          initial={{ opacity: 0 }}
          animate={{ opacity: [0, 0.4, 0] }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.3 }}
          className={cn('pointer-events-none fixed inset-0 z-50', FLASH_CLASS[kind], className)}
        />
      ) : null}
    </AnimatePresence>
  );
}
