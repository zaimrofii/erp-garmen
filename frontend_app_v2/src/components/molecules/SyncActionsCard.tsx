import { Printer, RefreshCw } from 'lucide-react';
import { Button } from '@/components/atoms/Button';
import { Input } from '@/components/atoms/Input';
import { cn } from '@/lib/cn';
import { canSyncFg, canSyncWip } from '@/lib/sync-actions';
import { CARD } from '@/lib/tokens';
import type { SyncStage } from '@/api/sync';

/**
 * SyncActionsCard - tombol sync manual ERP + cetak kupon (F6).
 *
 * Komponen ini **presentational & TANPA hook**: guard state (§6.6) dihitung dari
 * helper murni `lib/sync-actions.ts`, sedangkan pemanggilan API + feedback + toast
 * dilakukan halaman (pemanggil) lewat `onSync`/`onPrintCoupon`. Karena tanpa hook,
 * komponen ini bisa diuji langsung (SSR + walker) tanpa DOM.
 */

interface SyncActionsCardProps {
  /** State bundle backend (`DRAFT`/`CUTTING`/`SEWING`/`QC`/`DONE`/`SCRAPPED`). */
  state: string;
  /** Stage yang sedang dikirim (null = tidak ada). */
  syncBusy: SyncStage | null;
  couponBusy: boolean;
  ticketCode: string;
  onTicketCodeChange: (value: string) => void;
  onSync: (stage: SyncStage) => void;
  onPrintCoupon: () => void;
  className?: string;
}

export function SyncActionsCard({
  state,
  syncBusy,
  couponBusy,
  ticketCode,
  onTicketCodeChange,
  onSync,
  onPrintCoupon,
  className,
}: SyncActionsCardProps) {
  const wipReady = canSyncWip(state);
  const fgReady = canSyncFg(state);
  const syncLocked = syncBusy !== null;
  const couponReady = ticketCode.trim().length > 0;

  /**
   * Guard ganda (§6.6): tombol sudah `disabled`, TAPI handler juga memeriksa ulang
   * supaya klik tidak pernah mengirim sync saat state/lock tidak sesuai (mis. event
   * dari lapisan lain, atau `onClick` dipanggil langsung di test).
   */
  function handleSyncClick(stage: SyncStage, enabled: boolean): void {
    if (!enabled || syncLocked) return;

    onSync(stage);
  }

  function handleCouponClick(): void {
    if (!couponReady || couponBusy) return;

    onPrintCoupon();
  }

  return (
    <section className={cn(CARD, 'flex flex-col gap-3', className)} data-sync-actions={state}>
      <h2 className="text-sm font-semibold tracking-tight text-foreground">
        Sync ERP &amp; Cetak Kupon
      </h2>

      <div className="flex flex-wrap gap-2">
        <Button
          variant="secondary"
          icon={RefreshCw}
          loading={syncBusy === 'WIP'}
          disabled={!wipReady || syncLocked}
          onClick={() => handleSyncClick('WIP', wipReady)}
        >
          Sync WIP
        </Button>

        <Button
          variant="secondary"
          icon={RefreshCw}
          loading={syncBusy === 'FG'}
          disabled={!fgReady || syncLocked}
          onClick={() => handleSyncClick('FG', fgReady)}
        >
          Sync FG
        </Button>
      </div>

      <p className="text-xs text-muted-foreground">
        Sync WIP aktif pada state CUTTING/SEWING/QC · Sync FG aktif pada state DONE. Keduanya
        mengirim stok ke Odoo (efek nyata).
      </p>

      <div className="flex flex-col gap-2 border-t border-border/40 pt-3 sm:flex-row sm:items-end">
        <Input
          label="Kode kupon (ticket_code)"
          value={ticketCode}
          placeholder="mis. TKT-001"
          onChange={(event) => onTicketCodeChange(event.target.value)}
        />

        <Button
          variant="secondary"
          icon={Printer}
          loading={couponBusy}
          disabled={!couponReady || couponBusy}
          onClick={handleCouponClick}
        >
          Cetak Kupon
        </Button>
      </div>
    </section>
  );
}
