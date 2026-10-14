import { useEffect, useRef, type ReactNode } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { X } from 'lucide-react';
import { cn } from '@/lib/cn';
import { CARD, PILL_GHOST } from '@/lib/tokens';

/**
 * Modal - dialog untuk aksi kritikal (SCRAP / REWORK / unbind device).
 *
 * A11y: `role="dialog"` + `aria-modal`, tutup via ESC / klik backdrop / tombol X,
 * focus dipindah ke elemen pertama di panel lalu dikembalikan saat modal ditutup,
 * dan Tab di-cycling selama modal terbuka (focus trap sederhana).
 */

const FOCUSABLE =
  'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

interface ModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: string;
  children?: ReactNode;
  footer?: ReactNode;
}

export function Modal({ open, onOpenChange, title, description, children, footer }: ModalProps) {
  const panelRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;

    const panel = panelRef.current;
    const previouslyFocused: Element | null = document.activeElement;

    if (panel !== null) {
      const focusables = Array.from(panel.querySelectorAll<HTMLElement>(FOCUSABLE));
      if (focusables.length > 0) focusables[0].focus();
    }

    function handleKeyDown(event: KeyboardEvent): void {
      if (event.key === 'Escape') {
        onOpenChange(false);
        return;
      }
      if (event.key !== 'Tab' || panel === null) return;

      const nodes = Array.from(panel.querySelectorAll<HTMLElement>(FOCUSABLE));
      if (nodes.length === 0) return;

      const first = nodes[0];
      const last = nodes[nodes.length - 1];

      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }

    document.addEventListener('keydown', handleKeyDown);

    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      if (previouslyFocused instanceof HTMLElement) previouslyFocused.focus();
    };
  }, [open, onOpenChange]);

  return (
    <AnimatePresence>
      {open ? (
        <motion.div
          key="modal-backdrop"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.15 }}
          onClick={() => onOpenChange(false)}
          className="fixed inset-0 z-50 flex items-center justify-center bg-foreground/40 p-4 backdrop-blur-sm"
        >
          <motion.div
            key="modal-panel"
            ref={panelRef}
            role="dialog"
            aria-modal="true"
            aria-label={title}
            initial={{ opacity: 0, scale: 0.97, y: 8 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.97, y: 8 }}
            transition={{ duration: 0.18 }}
            onClick={(event) => event.stopPropagation()}
            className={cn(CARD, 'w-full max-w-md')}
          >
            <header className="flex items-start justify-between gap-3">
              <div className="flex flex-col gap-1">
                <h2 className="text-base font-semibold tracking-tight text-foreground">{title}</h2>
                {description !== undefined ? (
                  <p className="text-sm text-muted-foreground">{description}</p>
                ) : null}
              </div>
              <button
                type="button"
                onClick={() => onOpenChange(false)}
                aria-label="Tutup"
                className={cn(PILL_GHOST, 'h-8 w-8 shrink-0 p-0')}
              >
                <X className="h-4 w-4" aria-hidden="true" />
              </button>
            </header>

            {children !== undefined ? (
              <div className="mt-4 text-sm text-foreground">{children}</div>
            ) : null}

            {footer !== undefined ? (
              <div className="mt-6 flex flex-wrap items-center justify-end gap-2">{footer}</div>
            ) : null}
          </motion.div>
        </motion.div>
      ) : null}
    </AnimatePresence>
  );
}
