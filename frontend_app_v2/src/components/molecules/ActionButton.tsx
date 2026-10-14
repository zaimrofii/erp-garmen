import { motion } from 'framer-motion';
import {
  Check,
  ClipboardCheck,
  Loader2,
  Play,
  RotateCcw,
  Trash2,
  type LucideIcon,
} from 'lucide-react';
import { cn } from '@/lib/cn';
import { PILL } from '@/lib/tokens';
import { flashError, flashSuccess, haptic, playBeep, type BeepKind } from '@/lib/feedback';

/**
 * ActionButton - tombol aksi operator lantai produksi (3 tombol besar).
 *
 * Menggantikan tombol generik v2. Setiap aksi WAJIB memberi feedback: `playBeep` +
 * `haptic` + flash layar (aturan UX bagian 7.1). Ukuran default `hp` (min-h-12 = 48px);
 * pakai `kiosk` (min-h-14 = 56px) untuk tablet kios.
 */

export type ActionButtonVariant = 'start' | 'finish' | 'qc' | 'scrap' | 'rework';
export type ActionButtonSize = 'hp' | 'kiosk';

const VARIANT_CLASS: Record<ActionButtonVariant, string> = {
  start: 'bg-primary text-primary-foreground hover:opacity-90',
  finish: 'bg-primary text-primary-foreground hover:opacity-90',
  // F11 — "LULUS QC" (BUNDLE_QC, SEWING → QC): aksi maju, bukan destruktif → tone biru.
  qc: 'bg-accent-blue text-primary-foreground hover:opacity-90',
  scrap: 'bg-accent-coral text-primary-foreground hover:opacity-90',
  rework: 'border-2 border-accent-coral bg-card text-accent-coral hover:bg-accent-coral/10',
};

const VARIANT_ICON: Record<ActionButtonVariant, LucideIcon> = {
  start: Play,
  finish: Check,
  qc: ClipboardCheck,
  scrap: Trash2,
  rework: RotateCcw,
};

interface ActionFeedbackPreset {
  beep: BeepKind;
  haptic: 'success' | 'error';
  flash: 'success' | 'error';
}

const VARIANT_FEEDBACK: Record<ActionButtonVariant, ActionFeedbackPreset> = {
  start: { beep: 'success', haptic: 'success', flash: 'success' },
  finish: { beep: 'success', haptic: 'success', flash: 'success' },
  qc: { beep: 'success', haptic: 'success', flash: 'success' },
  scrap: { beep: 'error', haptic: 'error', flash: 'error' },
  rework: { beep: 'warning', haptic: 'error', flash: 'error' },
};

const SIZE_CLASS: Record<ActionButtonSize, string> = {
  hp: 'min-h-12 px-5 py-3 text-base',
  kiosk: 'min-h-14 px-6 py-4 text-lg',
};

interface ActionButtonProps {
  variant: ActionButtonVariant;
  label: string;
  onAction: () => void;
  disabled?: boolean;
  loading?: boolean;
  size?: ActionButtonSize;
  className?: string;
}

export function ActionButton({
  variant,
  label,
  onAction,
  disabled = false,
  loading = false,
  size = 'hp',
  className,
}: ActionButtonProps) {
  const Icon = VARIANT_ICON[variant];
  const isDisabled = disabled || loading;

  function handleTap(): void {
    if (isDisabled) return;

    const feedback = VARIANT_FEEDBACK[variant];
    playBeep(feedback.beep);
    haptic(feedback.haptic);
    if (feedback.flash === 'success') flashSuccess();
    else flashError();

    onAction();
  }

  return (
    <motion.button
      type="button"
      whileTap={{ scale: 0.97 }}
      whileHover={{ y: -1 }}
      disabled={isDisabled}
      aria-busy={loading || undefined}
      onClick={handleTap}
      className={cn(
        PILL,
        'relative w-full gap-3 font-semibold tracking-tight shadow-pill focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50',
        VARIANT_CLASS[variant],
        SIZE_CLASS[size],
        className,
      )}
    >
      {loading ? (
        <Loader2 className="h-5 w-5 animate-spin" aria-hidden="true" />
      ) : (
        <Icon className="h-5 w-5 shrink-0" aria-hidden="true" />
      )}
      {label}
    </motion.button>
  );
}
