import { useCallback, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { ArrowLeft, ArrowRightLeft, WifiOff } from 'lucide-react';
import { Button } from '@/components/atoms/Button';
import { Modal } from '@/components/atoms/Modal';
import { Spinner } from '@/components/atoms/Spinner';
import { ConflictResolver } from '@/components/ConflictResolver';
import { ActionButton } from '@/components/molecules/ActionButton';
import { BundleCard } from '@/components/molecules/BundleCard';
import { OfflineBanner } from '@/components/molecules/OfflineBanner';
import { useBundle } from '@/hooks/useBundle';
import { useWideViewport } from '@/hooks/use-wide-viewport';
import { cn } from '@/lib/cn';
import { cardStatusFromState } from '@/lib/state-display';
import { BADGE, CARD, PILL_GHOST } from '@/lib/tokens';
import { useOperatorActions } from '@/pages/production/useOperatorActions';
import type { AllowedAction } from '@/lib/schemas/action.schema';

/**
 * ShopFloorPage - halaman UTAMA operator (Screen A HP / Screen B Kios).
 *
 * Offline-safe: aksi dikirim lewat `submitAction` + offline queue (lihat
 * `useOperatorActions`). Tombol hanya tampil aktif kalau backend mengizinkan aksinya
 * (`bundle.allowed_actions`) - frontend tidak pernah menebak transisi state.
 *
 * Responsif tanpa hook tambahan untuk layout:
 *  - < lg  : satu kolom + action bar FIXED di bawah (Screen A);
 *  - >= lg : grid 12 kolom - info di kiri (col-span-7), panel aksi di kanan (col-span-5,
 *            Screen B kios) dan ukuran tombol naik ke `kiosk` (min-h-14 / 56px).
 */

export function ShopFloorPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const isWide = useWideViewport();

  const { data: bundle, isLoading, error: loadError, refetch } = useBundle(id);

  const allowedActions = useMemo<AllowedAction[]>(
    () => bundle?.allowed_actions ?? [],
    [bundle],
  );

  const {
    run,
    pending,
    error: actionError,
    notice,
    conflict,
    clearConflict,
    isOnline,
    pendingCount,
  } = useOperatorActions({
    resourceId: id ?? '',
    baseVersion: bundle?.version ?? '',
    allowedActions,
  });

  const [scrapOpen, setScrapOpen] = useState(false);

  /** Gate "jangan tampilkan aksi yang tidak diizinkan backend". */
  const canStart = allowedActions.some((action) => action.id === 'BUNDLE_START');
  const canFinish = allowedActions.some((action) => action.id === 'BUNDLE_FINISH');
  const canScrap = allowedActions.some((action) => action.id === 'BUNDLE_SCRAP');

  const actionSize = isWide ? 'kiosk' : 'hp';
  const busy = pending !== null;

  const goNextBundle = useCallback((): void => {
    navigate('/production/scan');
  }, [navigate]);

  const handleStart = useCallback((): void => {
    void run('BUNDLE_START').then((ok) => {
      if (!ok) return;
      void refetch();
      goNextBundle();
    });
  }, [goNextBundle, refetch, run]);

  const handleFinish = useCallback((): void => {
    void run('BUNDLE_FINISH').then((ok) => {
      if (!ok) return;
      void refetch();
      goNextBundle();
    });
  }, [goNextBundle, refetch, run]);

  const handleScrap = useCallback((): void => {
    void run('BUNDLE_SCRAP').then((ok) => {
      setScrapOpen(false);
      if (!ok) return;
      void refetch();
      goNextBundle();
    });
  }, [goNextBundle, refetch, run]);

  if (isLoading) {
    return (
      <div className="flex min-h-full items-center justify-center p-8">
        <Spinner size="lg" />
      </div>
    );
  }

  if (loadError !== null || bundle === undefined) {
    return (
      <div className="flex min-h-full flex-col items-center justify-center gap-4 p-8">
        <p className="text-sm font-semibold text-foreground">Bundle tidak ditemukan</p>
        <Button variant="secondary" onClick={goNextBundle}>
          Scan bundle lain
        </Button>
      </div>
    );
  }

  return (
    <div className="flex min-h-full flex-col bg-background lg:grid lg:grid-cols-12 lg:items-start lg:gap-6 lg:p-6">
      <header className="sticky top-0 z-20 flex h-14 items-center justify-between border-b border-border/40 bg-background/80 px-4 backdrop-blur lg:static lg:col-span-12 lg:h-auto lg:border-0 lg:bg-transparent lg:px-0">
        <button
          type="button"
          onClick={goNextBundle}
          aria-label="Kembali ke Scan"
          className={cn(
            PILL_GHOST,
            'p-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2',
          )}
        >
          <ArrowLeft className="h-5 w-5" aria-hidden="true" />
        </button>

        <div className="flex min-w-0 flex-col items-center">
          <h1 className="text-base font-semibold tracking-tight text-foreground">Shop Floor</h1>
          <p className="font-mono text-[11px] tabular-nums text-muted-foreground">{bundle.code}</p>
        </div>

        <span
          className={cn(
            BADGE,
            isOnline
              ? 'bg-accent-blue/10 text-accent-blue'
              : 'bg-accent-coral/10 text-accent-coral',
          )}
        >
          {isOnline ? (
            <>
              <span className="h-1.5 w-1.5 rounded-pill bg-accent-blue" aria-hidden="true" />
              Online
            </>
          ) : (
            <>
              <WifiOff className="h-3 w-3" aria-hidden="true" />
              Offline {pendingCount}
            </>
          )}
        </span>
      </header>

      <div className="flex flex-1 flex-col gap-4 p-4 pb-40 lg:col-span-7 lg:p-0 lg:pb-0">
        <OfflineBanner pending={pendingCount} online={isOnline} />

        <BundleCard
          bundleId={bundle.code}
          size={bundle.size || '-'}
          skuVariant={bundle.sku_variant}
          currentWc={bundle.current_work_center_code ?? '-'}
          status={cardStatusFromState(bundle.state)}
          qty={bundle.qty}
        />

        <section className={cn(CARD, 'flex flex-col gap-2')}>
          <h2 className="text-sm font-semibold tracking-tight text-foreground">Alur berikutnya</h2>

          <div className="flex items-center gap-2 text-sm text-foreground">
            <ArrowRightLeft className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
            <span className="tabular-nums">{bundle.current_work_center_code ?? '-'}</span>
          </div>

          <dl className="grid grid-cols-2 gap-3">
            <div className="flex flex-col gap-0.5">
              <dt className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground/80">
                Work Order
              </dt>
              <dd className="text-sm font-medium tabular-nums text-foreground">
                {bundle.work_order_id ?? '-'}
              </dd>
            </div>
            <div className="flex flex-col gap-0.5">
              <dt className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground/80">
                Line
              </dt>
              <dd className="text-sm font-medium text-foreground">
                {bundle.production_line_code ?? '-'}
              </dd>
            </div>
          </dl>

          <p className="text-xs text-muted-foreground">
            Work center berikutnya diambil dari DAG routing (`api/routing.ts`) - disambungkan di
            fase berikutnya.
          </p>
        </section>

        {actionError !== null ? (
          <p role="alert" className="text-sm font-medium text-accent-coral">
            {actionError}
          </p>
        ) : null}

        {notice !== null ? <p className="text-sm text-muted-foreground">{notice}</p> : null}
      </div>

      <div className="fixed inset-x-0 bottom-0 z-30 border-t border-border/40 bg-background/95 p-4 backdrop-blur lg:static lg:z-auto lg:col-span-5 lg:border-0 lg:bg-transparent lg:p-0 lg:backdrop-blur-none">
        <div className="mx-auto max-w-lg space-y-3 lg:max-w-none lg:rounded-card lg:border lg:border-border/80 lg:bg-card lg:p-6">
          <h2 className="hidden text-sm font-semibold tracking-tight text-foreground lg:block">
            Aksi Operator
          </h2>

          <div className="grid grid-cols-2 gap-3 lg:grid-cols-1">
            <ActionButton
              variant="start"
              label="MULAI"
              onAction={handleStart}
              size={actionSize}
              loading={pending === 'BUNDLE_START'}
              disabled={!canStart || busy}
            />
            <ActionButton
              variant="finish"
              label="SELESAI"
              onAction={handleFinish}
              size={actionSize}
              loading={pending === 'BUNDLE_FINISH'}
              disabled={!canFinish || busy}
            />
          </div>

          <ActionButton
            variant="scrap"
            label="SCRAP"
            onAction={() => setScrapOpen(true)}
            size={actionSize}
            disabled={!canScrap || busy}
          />

          {!canStart && !canFinish && !canScrap ? (
            <p className="text-center text-xs text-muted-foreground">
              Tidak ada aksi yang diizinkan backend untuk bundle ini.
            </p>
          ) : null}
        </div>
      </div>

      <Modal
        open={scrapOpen}
        onOpenChange={setScrapOpen}
        title="Konfirmasi SCRAP"
        description={`Bundle ${bundle.code} akan dibuang permanen. Lanjutkan?`}
        footer={
          <>
            <Button variant="secondary" onClick={() => setScrapOpen(false)}>
              Batal
            </Button>
            <Button variant="danger" loading={pending === 'BUNDLE_SCRAP'} onClick={handleScrap}>
              SCRAP
            </Button>
          </>
        }
      />

      {conflict !== null ? (
        <ConflictResolver
          open
          action={conflict.action}
          current={conflict.current}
          onResolve={(choice) => {
            clearConflict();
            if (choice === 'server_wins') void refetch();
          }}
          onClose={clearConflict}
        />
      ) : null}
    </div>
  );
}
