import { AlertOctagon, AlertTriangle, CheckCircle2, Circle, type LucideIcon } from 'lucide-react';
import { cn } from '@/lib/cn';
import { BADGE } from '@/lib/tokens';
import type { StatusChipStatus } from '@/lib/state-display';

/**
 * StatusChip - chip status operasional (Visual Design System v1.0 bagian 2.4).
 * WAJIB selalu ada ikon + teks; warna tidak boleh jadi satu-satunya penanda.
 */

const STATUS_CLASS: Record<StatusChipStatus, string> = {
  on_track: 'bg-accent-blue/10 text-accent-blue border border-accent-blue/20',
  delay: 'bg-accent-coral/10 text-accent-coral border border-accent-coral/20',
  bottleneck:
    'bg-accent-coral/20 text-accent-coral border border-accent-coral/40 animate-pulse',
  neutral: 'bg-muted text-muted-foreground',
};

const STATUS_ICON: Record<StatusChipStatus, LucideIcon> = {
  on_track: CheckCircle2,
  delay: AlertTriangle,
  bottleneck: AlertOctagon,
  neutral: Circle,
};

const STATUS_LABEL: Record<StatusChipStatus, string> = {
  on_track: 'On Track',
  delay: 'Delay',
  bottleneck: 'Bottleneck',
  neutral: 'Netral',
};

interface StatusChipProps {
  status: StatusChipStatus;
  label?: string;
  className?: string;
}

export function StatusChip({ status, label, className }: StatusChipProps) {
  const Icon = STATUS_ICON[status];

  return (
    <span className={cn(BADGE, STATUS_CLASS[status], className)}>
      <Icon className="h-3 w-3" aria-hidden="true" />
      {label ?? STATUS_LABEL[status]}
    </span>
  );
}
