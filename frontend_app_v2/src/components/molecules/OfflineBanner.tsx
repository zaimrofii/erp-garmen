import { WifiOff } from 'lucide-react';
import { cn } from '@/lib/cn';

/**
 * OfflineBanner - indikator mode offline + jumlah aksi pending.
 * Tidak dirender sama sekali saat online (`return null`) supaya layout tidak goyang.
 */

interface OfflineBannerProps {
  pending: number;
  online: boolean;
  className?: string;
}

export function OfflineBanner({ pending, online, className }: OfflineBannerProps) {
  if (online) return null;

  return (
    <div
      role="status"
      className={cn(
        'flex items-center gap-2 rounded-lg border border-accent-coral/30 bg-accent-coral/10 px-3 py-2 text-sm',
        className,
      )}
    >
      <WifiOff className="h-4 w-4 shrink-0 text-accent-coral" aria-hidden="true" />
      <span className="font-medium text-foreground">OFFLINE</span>
      <span className="text-muted-foreground">- {pending} aksi pending</span>
    </div>
  );
}
