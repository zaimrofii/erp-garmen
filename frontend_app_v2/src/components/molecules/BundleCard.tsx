import {
  CheckCircle2,
  ChevronRight,
  Clock,
  PlayCircle,
  QrCode,
  RotateCcw,
  Trash2,
  type LucideIcon,
} from 'lucide-react';
import { cn } from '@/lib/cn';
import { BADGE, CARD, PILL_SECONDARY } from '@/lib/tokens';
import type { BundleCardStatus } from '@/lib/state-display';

/**
 * BundleCard - kartu bundle operator (Visual Design System v1.0 bagian 2.3).
 * Menampilkan QR placeholder + 4 info utama (Size/SKU/WC/Qty) dengan `tabular-nums`
 * supaya angka tidak "melompat" saat berubah.
 */

const STATUS_BADGE: Record<BundleCardStatus, string> = {
  waiting: 'bg-muted text-muted-foreground',
  in_progress: 'bg-accent-blue/10 text-accent-blue border border-accent-blue/20',
  done: 'bg-accent-blue/10 text-accent-blue border border-accent-blue/20',
  rework: 'bg-accent-coral/10 text-accent-coral border border-accent-coral/20',
  scrap: 'bg-accent-coral/20 text-accent-coral border border-accent-coral/40',
};

const STATUS_ICON: Record<BundleCardStatus, LucideIcon> = {
  waiting: Clock,
  in_progress: PlayCircle,
  done: CheckCircle2,
  rework: RotateCcw,
  scrap: Trash2,
};

const STATUS_LABEL: Record<BundleCardStatus, string> = {
  waiting: 'Waiting',
  in_progress: 'In Progress',
  done: 'Done',
  rework: 'Rework',
  scrap: 'Scrap',
};

interface InfoTagProps {
  label: string;
  value: string;
}

function InfoTag({ label, value }: InfoTagProps) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground/80">
        {label}
      </dt>
      <dd className="text-sm font-medium tabular-nums text-foreground">{value}</dd>
    </div>
  );
}

interface BundleCardProps {
  bundleId: string;
  size: string;
  skuVariant: string;
  currentWc: string;
  status: BundleCardStatus;
  qty: number;
  onAction?: () => void;
  className?: string;
}

export function BundleCard({
  bundleId,
  size,
  skuVariant,
  currentWc,
  status,
  qty,
  onAction,
  className,
}: BundleCardProps) {
  const StatusIcon = STATUS_ICON[status];

  return (
    <article className={cn(CARD, 'flex flex-col gap-4', className)}>
      <header className="flex items-start justify-between gap-3">
        <div className="flex flex-col gap-1">
          <span className={cn(BADGE, STATUS_BADGE[status])}>
            <StatusIcon className="h-3 w-3" aria-hidden="true" />
            {STATUS_LABEL[status]}
          </span>
          <h3 className="font-mono text-base font-semibold tabular-nums tracking-tight text-foreground">
            {bundleId}
          </h3>
        </div>

        <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-md bg-muted">
          <QrCode className="h-6 w-6 text-muted-foreground" aria-hidden="true" />
        </div>
      </header>

      <dl className="grid grid-cols-2 gap-3">
        <InfoTag label="Size" value={size} />
        <InfoTag label="SKU" value={skuVariant} />
        <InfoTag label="WC" value={currentWc} />
        <InfoTag label="Qty" value={`${qty} pcs`} />
      </dl>

      {onAction !== undefined ? (
        <button
          type="button"
          onClick={onAction}
          className={cn(PILL_SECONDARY, 'w-full py-2 text-sm font-medium')}
        >
          Lihat Detail
          <ChevronRight className="h-4 w-4" aria-hidden="true" />
        </button>
      ) : null}
    </article>
  );
}
