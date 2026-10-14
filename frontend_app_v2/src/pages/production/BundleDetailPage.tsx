import { useCallback, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { ArrowLeft, ArrowRightLeft } from 'lucide-react';
import { Button } from '@/components/atoms/Button';
import { Modal } from '@/components/atoms/Modal';
import { Spinner } from '@/components/atoms/Spinner';
import { Toast, type ToastTone } from '@/components/atoms/Toast';
import { BundleCard } from '@/components/molecules/BundleCard';
import { ChatterBox } from '@/components/molecules/ChatterBox';
import { PrintTagButton } from '@/components/molecules/PrintTagButton';
import { SyncActionsCard } from '@/components/molecules/SyncActionsCard';
import { useFeedback } from '@/app/app-runtime';
import { submitBundleAction } from '@/api/bundles';
import { printCoupon } from '@/api/print';
import type { SyncStage } from '@/api/sync';
import { useApiClient } from '@/hooks/useApiClient';
import { useBundle } from '@/hooks/useBundle';
import { useChatter } from '@/hooks/useChatter';
import { useChatterWs } from '@/hooks/useChatterWs';
import { cn } from '@/lib/cn';
import { mergeChatterPreview } from '@/lib/chatter-merge';
import { cardStatusFromState } from '@/lib/state-display';
import { runBundleStageSync } from '@/lib/sync-actions';
import { CARD, PILL_GHOST } from '@/lib/tokens';
import { generateUUID } from '@/lib/uuid';

/**
 * BundleDetailPage (production) - Screen "lihat + aksi sesekali", ONLINE-ONLY.
 *
 * Beda dari ShopFloorPage dengan sengaja (Blueprint bagian 6 "Dua Jalur Aksi"):
 *  - di sini aksi dikirim LANGSUNG lewat `apiClient.post` (via adapter
 *    `submitBundleAction`), tanpa offline queue - cepat & sederhana;
 *  - ShopFloorPage (operator lantai) memakai `submitAction` + offline queue
 *    (tahan offline, ada ConflictResolver).
 * Jalur ini tetap mengirim Idempotency-Key + X-Base-Version (optimistic lock).
 */

/** Aksi yang bisa dikirim dari halaman detail (id = kontrak backend). */
type DetailAction = 'BUNDLE_START' | 'BUNDLE_FINISH' | 'BUNDLE_SCRAP';

export function ProductionBundleDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const client = useApiClient();
  const { trigger } = useFeedback();

  const { data: bundle, isLoading, error: loadError, refetch } = useBundle(id);

  // Chatter: container memegang datanya, ChatterBox hanya merender.
  const [chatterCursor, setChatterCursor] = useState<string | null>(null);
  const chatter = useChatter('bundles', bundle?.id, { limit: 5, cursor: chatterCursor });

  // Real-time (F4): event WS group `bundle.<id>` di-prepend ke `preview` hasil fetch.
  const ws = useChatterWs({ resource: 'bundles', id: bundle?.id });

  const [running, setRunning] = useState<DetailAction | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [scrapOpen, setScrapOpen] = useState(false);

  // F6 — sync manual ERP (WIP/FG) + cetak kupon (efek nyata di Odoo).
  const [syncBusy, setSyncBusy] = useState<SyncStage | null>(null);
  const [couponBusy, setCouponBusy] = useState(false);
  const [ticketCode, setTicketCode] = useState('');
  const [toast, setToast] = useState<{ tone: ToastTone; title: string; description: string } | null>(
    null,
  );

  const goToScan = useCallback((): void => {
    navigate('/production/scan');
  }, [navigate]);

  /**
   * Kirim aksi online. `trigger()` memicu beep + haptic + flash lewat `ActionFeedback`
   * global; tidak ada playBeep langsung di sini supaya bunyi tidak berbunyi berkali-kali.
   */
  const runOnline = useCallback(
    async (action: DetailAction, payload?: Record<string, unknown>): Promise<void> => {
      if (bundle === undefined) return;

      setRunning(action);
      setActionError(null);
      setNotice(null);

      try {
        const outcome = await submitBundleAction(client, bundle.id, action, payload ?? {}, {
          idempotencyKey: generateUUID(),
          baseVersion: bundle.version,
        });

        trigger('success');
        setNotice(outcome.message ?? `Aksi ${action} berhasil.`);
        void refetch();
      } catch (caught) {
        trigger('error');
        setActionError(caught instanceof Error ? caught.message : `Aksi ${action} gagal.`);
      } finally {
        setRunning(null);
      }
    },
    [bundle, client, refetch, trigger],
  );

  const handleStart = useCallback((): void => {
    void runOnline('BUNDLE_START');
  }, [runOnline]);

  const handleFinish = useCallback((): void => {
    void runOnline('BUNDLE_FINISH');
  }, [runOnline]);

  const handleScrap = useCallback((): void => {
    setScrapOpen(false);
    void runOnline('BUNDLE_SCRAP');
  }, [runOnline]);

  /** F6 — sync manual WIP/FG ke Odoo; hasil → feedback (beep+haptic) + toast. */
  const handleSync = useCallback(
    async (stage: SyncStage): Promise<void> => {
      if (bundle === undefined) return;

      setSyncBusy(stage);
      const outcome = await runBundleStageSync(client, stage, {
        id: bundle.id,
        code: bundle.code,
        qty: bundle.qty,
      });
      setSyncBusy(null);
      trigger(outcome.ok ? 'success' : 'error');
      setToast({
        tone: outcome.ok ? 'success' : 'error',
        title: outcome.ok ? `Sync ${stage} terkirim` : `Sync ${stage} gagal`,
        description: outcome.message,
      });
    },
    [bundle, client, trigger],
  );

  /** F6 — cetak kupon piece-rate dari `ticket_code` (kontrak §7.2). */
  const handlePrintCoupon = useCallback(async (): Promise<void> => {
    setCouponBusy(true);

    try {
      const job = await printCoupon(client, ticketCode);
      setCouponBusy(false);
      trigger('success');
      setToast({
        tone: 'success',
        title: 'Kupon terkirim ke printer',
        description: `${job.bytes} bytes (backend ${job.backend}, ref ${job.ref}).`,
      });
    } catch (caught) {
      setCouponBusy(false);
      trigger('error');
      setToast({
        tone: 'error',
        title: 'Gagal mencetak kupon',
        description: caught instanceof Error ? caught.message : 'Gagal mencetak kupon.',
      });
    }
  }, [client, ticketCode, trigger]);

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
        <Button variant="secondary" onClick={goToScan}>
          Scan bundle
        </Button>
      </div>
    );
  }

  const allowed = bundle.allowed_actions;
  const canStart = allowed.some((action) => action.id === 'BUNDLE_START');
  const canFinish = allowed.some((action) => action.id === 'BUNDLE_FINISH');
  const canScrap = allowed.some((action) => action.id === 'BUNDLE_SCRAP');
  const busy = running !== null;

  return (
    <div className="flex min-h-full flex-col bg-background">
      <header className="sticky top-0 z-20 flex h-14 items-center justify-between border-b border-border/40 bg-background/80 px-4 backdrop-blur">
        <button
          type="button"
          onClick={() => navigate(-1)}
          aria-label="Kembali"
          className={cn(
            PILL_GHOST,
            'p-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2',
          )}
        >
          <ArrowLeft className="h-5 w-5" aria-hidden="true" />
        </button>

        <div className="flex min-w-0 flex-col items-center">
          <h1 className="text-base font-semibold tracking-tight text-foreground">Detail Bundle</h1>
          <p className="font-mono text-[11px] tabular-nums text-muted-foreground">{bundle.code}</p>
        </div>

        <span aria-hidden="true" className="h-9 w-9" />
      </header>

      <div className="flex flex-col gap-4 p-4 pb-24">
        <BundleCard
          bundleId={bundle.code}
          size={bundle.size || '-'}
          skuVariant={bundle.sku_variant}
          currentWc={bundle.current_work_center_code ?? '-'}
          status={cardStatusFromState(bundle.state)}
          qty={bundle.qty}
        />

        <section className={cn(CARD, 'flex flex-col gap-3')}>
          <h2 className="text-sm font-semibold tracking-tight text-foreground">Metadata</h2>

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
            <div className="flex flex-col gap-0.5">
              <dt className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground/80">
                Versi
              </dt>
              <dd className="text-sm font-medium tabular-nums text-foreground">{bundle.version}</dd>
            </div>
            <div className="flex flex-col gap-0.5">
              <dt className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground/80">
                Diperbarui
              </dt>
              <dd className="text-sm font-medium text-foreground">
                {new Date(bundle.updated_at).toLocaleString('id-ID')}
              </dd>
            </div>
          </dl>
        </section>

        <section className={cn(CARD, 'flex flex-col gap-2')}>
          <h2 className="text-sm font-semibold tracking-tight text-foreground">Routing</h2>
          <div className="flex items-center gap-2 text-sm text-foreground">
            <ArrowRightLeft className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
            <span className="tabular-nums">{bundle.current_work_center_code ?? '-'}</span>
          </div>
          <p className="text-xs text-muted-foreground">
            DAG routing penuh (`api/routing.ts`) disambungkan di fase berikutnya.
          </p>
        </section>

        <section className={cn(CARD, 'flex flex-col gap-3')}>
          <h2 className="text-sm font-semibold tracking-tight text-foreground">Aksi</h2>

          <div className="flex flex-wrap gap-2">
            <Button
              variant="primary"
              loading={running === 'BUNDLE_START'}
              disabled={!canStart || busy}
              onClick={handleStart}
            >
              MULAI
            </Button>
            <Button
              variant="primary"
              loading={running === 'BUNDLE_FINISH'}
              disabled={!canFinish || busy}
              onClick={handleFinish}
            >
              SELESAI
            </Button>
            <Button
              variant="danger"
              loading={running === 'BUNDLE_SCRAP'}
              disabled={!canScrap || busy}
              onClick={() => setScrapOpen(true)}
            >
              SCRAP
            </Button>
          </div>

          <div className="flex flex-wrap items-center justify-between gap-2">
            <PrintTagButton
              bundleId={String(bundle.id)}
              onSuccess={() => {
                void refetch();
              }}
            />
            <Button variant="ghost" onClick={goToScan}>
              Ke Scan
            </Button>
          </div>
        </section>

        <SyncActionsCard
          state={bundle.state}
          syncBusy={syncBusy}
          couponBusy={couponBusy}
          ticketCode={ticketCode}
          onTicketCodeChange={setTicketCode}
          onSync={(stage) => {
            void handleSync(stage);
          }}
          onPrintCoupon={() => {
            void handlePrintCoupon();
          }}
        />

        {actionError !== null ? (
          <p role="alert" className="text-sm font-medium text-accent-coral">
            {actionError}
          </p>
        ) : null}

        {notice !== null ? <p className="text-sm text-muted-foreground">{notice}</p> : null}

        <section className={CARD}>
          <ChatterBox
            preview={mergeChatterPreview(chatter.data?.preview ?? [], ws.events)}
            loading={chatter.isLoading}
            hasMore={chatter.data?.has_more ?? false}
            onLoadMore={() => setChatterCursor(chatter.data?.next_cursor ?? null)}
          />
        </section>
      </div>

      <Toast
        open={toast !== null}
        onOpenChange={() => setToast(null)}
        tone={toast?.tone ?? 'default'}
        title={toast?.title ?? ''}
        description={toast?.description}
      />

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
            <Button variant="danger" loading={running === 'BUNDLE_SCRAP'} onClick={handleScrap}>
              SCRAP
            </Button>
          </>
        }
      />
    </div>
  );
}
