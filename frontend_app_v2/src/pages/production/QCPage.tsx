import { useCallback, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { ArrowLeft, Plus, RefreshCw, Trash2, WifiOff } from 'lucide-react';
import { Badge } from '@/components/atoms/Badge';
import { Button } from '@/components/atoms/Button';
import { Modal } from '@/components/atoms/Modal';
import { Spinner } from '@/components/atoms/Spinner';
import { Toast, type ToastTone } from '@/components/atoms/Toast';
import { ConflictResolver } from '@/components/ConflictResolver';
import { ActionButton } from '@/components/molecules/ActionButton';
import { DefectCounter } from '@/components/molecules/DefectCounter';
import { DefectSilhouette } from '@/components/molecules/DefectSilhouette';
import { PhotoUpload } from '@/components/molecules/PhotoUpload';
import { ScanInput } from '@/components/molecules/ScanInput';
import { useFeedback, useOffline } from '@/app/app-runtime';
import { submitQCRecord } from '@/api/qc';
import { useApiClient } from '@/hooks/useApiClient';
import { useBundle } from '@/hooks/useBundle';
import { cn } from '@/lib/cn';
import { BUNDLE_ACTION_IDS, canSubmitBundleAction, hasAllowedAction } from '@/lib/action-runner';
import { canSyncScrap, runScrapSync } from '@/lib/sync-actions';
import { DEFECT_REGION_LABELS, DEFECT_TYPE_LABELS, QC_ACTION_LABELS } from '@/lib/state-display';
import { BADGE, CARD, PILL_GHOST } from '@/lib/tokens';
import { useOperatorActions } from '@/pages/production/useOperatorActions';
import { useQCDefects } from '@/pages/quality/useQCDefects';
import type { AllowedAction } from '@/lib/schemas/action.schema';
import type { DefectRegion, DefectType } from '@/types/qc';

/**
 * QCPage - Screen C (Visual Design System v3 bagian 3.3): form defect visual + multi-qty.
 *
 * TIGA aksi dengan makna berbeda (lihat laporan Fase 18):
 *  - REWORK / SCRAP = **aksi bundle** nyata (`BUNDLE_REWORK` / `BUNDLE_SCRAP`) lewat
 *    `useOperatorActions` -> offline queue + modal konfirmasi;
 *  - SUBMIT = **catat hasil inspeksi QC** ke resource `qc` (`api/qc.ts`). Backend v4.3
 *    belum punya endpoint create untuk `qc` (read-only: `allowed_actions: []`), sehingga
 *    adapter `qcSubmit` masih DUMMY (menambah `LOCAL_QC_LOGS` -> tampil di DefectLogPage).
 *
 * Route: `/production/qc` (scan dulu) dan `/production/qc/:id` (langsung dari Shop Floor).
 */

const DEFECT_TYPES: DefectType[] = [
  'jahitan_loncat',
  'ukuran_tidak_sesuai',
  'kain_rusak',
  'lainnya',
];

type QCDecision = 'rework' | 'scrap';
/** F11/11.2a — `BUNDLE_QC` = aksi nyata masuk tahap QC (SEWING → QC), bukan catatan lokal. */
type ConfirmAction = 'BUNDLE_REWORK' | 'BUNDLE_SCRAP' | 'BUNDLE_QC';

/** Judul/tombol modal konfirmasi per aksi (F11 menambah QC). */
const CONFIRM_TITLE: Record<ConfirmAction, string> = {
  BUNDLE_REWORK: 'Konfirmasi REWORK',
  BUNDLE_SCRAP: 'Konfirmasi SCRAP',
  BUNDLE_QC: 'Konfirmasi LULUS QC',
};

const CONFIRM_BUTTON: Record<ConfirmAction, string> = {
  BUNDLE_REWORK: 'REWORK',
  BUNDLE_SCRAP: 'SCRAP',
  BUNDLE_QC: 'LULUS QC',
};

/** Pilihan keputusan QC yang dicatat di SUBMIT (mirror `QCLog.action`). */
const QC_DECISIONS: QCDecision[] = ['rework', 'scrap'];

export function QCPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { trigger } = useFeedback();
  const { isOnline, pendingCount } = useOffline();
  const client = useApiClient();

  const { data: bundle, isLoading, error: loadError, refetch } = useBundle(id);

  const defects = useQCDefects();
  const [selectedRegions, setSelectedRegions] = useState<DefectRegion[]>([]);
  const [defectType, setDefectType] = useState<DefectType>('jahitan_loncat');
  const [qty, setQty] = useState(1);
  const [photo, setPhoto] = useState<string | undefined>(undefined);
  const [decision, setDecision] = useState<QCDecision>('rework');
  const [confirmAction, setConfirmAction] = useState<ConfirmAction | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  // F6 — sync scrap manual (semua ScrapAccumulator pending) ke Odoo.
  const [scrapSyncBusy, setScrapSyncBusy] = useState(false);
  const [syncToast, setSyncToast] = useState<{
    tone: ToastTone;
    title: string;
    description: string;
  } | null>(null);

  const allowedActions = useMemo<AllowedAction[]>(() => bundle?.allowed_actions ?? [], [bundle]);

  const {
    run,
    pending,
    error: actionError,
    notice,
    conflict,
    clearConflict,
  } = useOperatorActions({
    resourceId: id ?? '',
    baseVersion: bundle?.version ?? '',
    allowedActions,
  });

  // F11/11.2c — guard DUA lapis: aksi harus ADA di `allowed_actions` (metadata backend) DAN
  // state sekarang sah menurut state machine `garment.bundle` (BUNDLE_QC hanya dari SEWING,
  // BUNDLE_SCRAP dari semua state non-terminal/DRAFT..QC). REWORK tidak dipetakan di runner
  // (bukan transisi state machine) → cukup metadata.
  const canRework = hasAllowedAction(allowedActions, BUNDLE_ACTION_IDS.REWORK);
  const canQc = canSubmitBundleAction(allowedActions, BUNDLE_ACTION_IDS.QC, bundle?.state);
  const canScrap = canSubmitBundleAction(allowedActions, BUNDLE_ACTION_IDS.SCRAP, bundle?.state);
  const busy = pending !== null || submitting;
  const canScrapSync = bundle === undefined ? false : canSyncScrap(bundle.state);

  /** F6 — kirim scrap pending ke Odoo (efek nyata); hasil → feedback + toast. */
  const handleScrapSync = useCallback(async (): Promise<void> => {
    setScrapSyncBusy(true);
    const outcome = await runScrapSync(client);
    setScrapSyncBusy(false);
    trigger(outcome.ok ? 'success' : 'error');
    setSyncToast({
      tone: outcome.ok ? 'success' : 'error',
      title: outcome.ok ? 'Sync scrap selesai' : 'Sync scrap gagal',
      description: outcome.message,
    });
  }, [client, trigger]);

  const toggleRegion = useCallback((region: DefectRegion): void => {
    setSelectedRegions((current) =>
      current.includes(region) ? current.filter((item) => item !== region) : [...current, region],
    );
  }, []);

  /** Tambah satu entry per region terpilih (multi-region dalam sekali input). */
  const handleAddDefect = useCallback((): void => {
    if (selectedRegions.length === 0 || qty < 1) return;

    for (const region of selectedRegions) {
      defects.upsertEntry({
        type: defectType,
        location: region,
        qty,
        ...(photo === undefined ? {} : { photo }),
      });
    }

    setSelectedRegions([]);
    setQty(1);
    setPhoto(undefined);
  }, [defectType, defects, photo, qty, selectedRegions]);

  const goNextBundle = useCallback((): void => {
    navigate('/production/scan');
  }, [navigate]);

  /** REWORK / SCRAP: aksi bundle nyata (offline-safe) + payload defect. */
  const handleDecision = useCallback(
    async (action: ConfirmAction): Promise<void> => {
      setConfirmAction(null);

      const ok = await run(action, { defect_entries: defects.toPayload() });
      if (!ok) return;

      defects.clear();
      goNextBundle();
    },
    [defects, goNextBundle, run],
  );

  /** SUBMIT: catat hasil inspeksi QC (adapter `qcSubmit`). */
  const handleSubmitRecord = useCallback(async (): Promise<void> => {
    if (bundle === undefined || defects.isEmpty) return;

    setSubmitting(true);
    setSubmitError(null);

    try {
      const entries = defects.toPayload();
      const first = entries[0];

      if (first === undefined) return;

      await submitQCRecord(client, {
        bundle_id: bundle.id,
        defect_type: first.type,
        qty: entries.reduce((total, entry) => total + entry.qty, 0),
        reason: entries.map((entry) => entry.location).join(', '),
        action: decision,
      });

      trigger('success');
      defects.clear();
      goNextBundle();
    } catch (caught) {
      trigger('error');
      setSubmitError(caught instanceof Error ? caught.message : 'Gagal menyimpan catatan QC.');
    } finally {
      setSubmitting(false);
    }
  }, [bundle, client, decision, defects, goNextBundle, trigger]);

  if (id === undefined) {
    return (
      <div className="flex min-h-full flex-col bg-background">
        <header className="sticky top-0 z-20 flex h-14 items-center gap-3 border-b border-border/40 bg-background/80 px-4 backdrop-blur">
          <button
            type="button"
            onClick={() => navigate('/')}
            aria-label="Kembali ke Dashboard"
            className={cn(
              PILL_GHOST,
              'p-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2',
            )}
          >
            <ArrowLeft className="h-5 w-5" aria-hidden="true" />
          </button>
          <h1 className="text-base font-semibold tracking-tight text-foreground">QC Defect</h1>
        </header>

        <div className="flex flex-1 flex-col gap-4 p-4">
          <section className={cn(CARD, 'flex flex-col gap-3')}>
            <h2 className="text-sm font-semibold tracking-tight text-foreground">Scan bundle</h2>
            <p className="text-xs text-muted-foreground">
              Scan QR bundle yang akan diperiksa, lalu form defect terbuka.
            </p>
            <ScanInput
              onScan={(code) => navigate(`/production/qc/${code.replace(/^.*\//, '')}`)}
            />
          </section>
        </div>
      </div>
    );
  }

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
          Scan bundle
        </Button>
      </div>
    );
  }

  return (
    <div className="flex min-h-full flex-col bg-background">
      <header className="sticky top-0 z-20 flex h-14 items-center gap-3 border-b border-border/40 bg-background/80 px-4 backdrop-blur">
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

        <h1 className="text-base font-semibold tracking-tight text-foreground">QC Defect</h1>

        <span
          className={cn(
            BADGE,
            'ml-auto',
            isOnline
              ? 'bg-accent-blue/10 text-accent-blue'
              : 'bg-accent-coral/10 text-accent-coral',
          )}
        >
          {isOnline ? (
            'Online'
          ) : (
            <>
              <WifiOff className="h-3 w-3" aria-hidden="true" />
              Offline {pendingCount}
            </>
          )}
        </span>
      </header>

      <div className="flex flex-1 flex-col gap-4 p-4 pb-48">
        {/* 1. Konteks bundle */}
        <section className={cn(CARD, 'flex items-center justify-between gap-3 py-3')}>
          <div className="flex min-w-0 flex-col gap-0.5">
            <span className="truncate font-mono text-sm font-semibold tabular-nums text-foreground">
              {bundle.code}
            </span>
            <span className="text-xs text-muted-foreground">
              WC asal: {bundle.current_work_center_code ?? '-'}
            </span>
          </div>

          <Badge tone={defects.entries.length > 0 ? 'coral' : 'muted'}>
            {defects.entries.length > 0 ? `${defects.totalQty} pcs defect` : 'Belum ada defect'}
          </Badge>
        </section>

        {/* 1b. Sync scrap manual ke Odoo (F6) — aksi global: semua scrap yang belum terkirim */}
        <section className={cn(CARD, 'flex flex-col gap-3')}>
          <div className="flex items-center justify-between gap-2">
            <h2 className="text-sm font-semibold tracking-tight text-foreground">
              Sync Scrap ke Odoo
            </h2>
            <Badge tone={canScrapSync ? 'default' : 'muted'}>{bundle.state}</Badge>
          </div>

          <Button
            variant="secondary"
            icon={RefreshCw}
            loading={scrapSyncBusy}
            disabled={!canScrapSync || scrapSyncBusy}
            onClick={() => {
              void handleScrapSync();
            }}
          >
            Sync Scrap
          </Button>

          <p className="text-xs text-muted-foreground">
            Mengirim semua catatan scrap yang belum terkirim ke Odoo (efek nyata). Aktif saat bundle
            di state QC.
          </p>
        </section>

        {/* 2. Siluet pakaian */}
        <section className={cn(CARD, 'flex flex-col gap-3')}>
          <h2 className="text-sm font-semibold tracking-tight text-foreground">Lokasi Cacat</h2>
          <DefectSilhouette
            selected={selectedRegions}
            onToggle={toggleRegion}
            className="[&_svg]:max-w-[320px]"
          />
          <p className="text-xs text-muted-foreground">
            Ketuk area pada siluet (region terkecil &gt;= 44x44 px pada lebar ini) atau chip di
            bawahnya. Bisa beberapa lokasi sekaligus.
          </p>
        </section>

        {/* 3. Jenis cacat + qty */}
        <section className={cn(CARD, 'flex flex-col gap-3')}>
          <h2 className="text-sm font-semibold tracking-tight text-foreground">Jenis Cacat</h2>

          <fieldset className="flex flex-col gap-1">
            <legend className="sr-only">Jenis cacat</legend>
            {DEFECT_TYPES.map((type) => (
              <label
                key={type}
                className="flex cursor-pointer items-center gap-3 rounded-lg px-2 py-2.5 transition-colors hover:bg-muted/50"
              >
                <input
                  type="radio"
                  name="defect-type"
                  value={type}
                  checked={defectType === type}
                  onChange={() => setDefectType(type)}
                  className="h-4 w-4 shrink-0 accent-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                />
                <span className="text-sm text-foreground">{DEFECT_TYPE_LABELS[type]}</span>
              </label>
            ))}
          </fieldset>

          <div className="flex items-center justify-between gap-3 border-t border-border/40 pt-3">
            <div className="flex flex-col">
              <span className="text-xs font-medium text-muted-foreground">Qty per lokasi</span>
              <span className="text-[11px] text-muted-foreground/80">
                {selectedRegions.length} lokasi terpilih
              </span>
            </div>
            <DefectCounter value={qty} onChange={setQty} min={1} max={99} label="defect" />
          </div>

          <Button
            variant="secondary"
            icon={Plus}
            disabled={selectedRegions.length === 0 || qty < 1 || busy}
            onClick={handleAddDefect}
          >
            Tambah Defect
          </Button>
        </section>

        {/* 4. Daftar entry defect (multi-qty) */}
        <section className={cn(CARD, 'flex flex-col gap-3')}>
          <div className="flex items-center justify-between gap-2">
            <h2 className="text-sm font-semibold tracking-tight text-foreground">Daftar Defect</h2>
            <Badge tone="default">{defects.totalQty} pcs</Badge>
          </div>

          {defects.isEmpty ? (
            <p className="text-xs text-muted-foreground">Belum ada defect ditambahkan.</p>
          ) : (
            <ul className="flex flex-col gap-2">
              {defects.entries.map((entry) => (
                <li
                  key={entry.id}
                  className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border/40 p-3"
                >
                  <div className="flex min-w-0 flex-col gap-0.5">
                    <span className="text-sm font-medium text-foreground">
                      {DEFECT_TYPE_LABELS[entry.type]}
                    </span>
                    <span className="text-xs text-muted-foreground">
                      {DEFECT_REGION_LABELS[entry.location]}
                      {entry.photo === undefined ? '' : ' - ada foto'}
                    </span>
                  </div>

                  <div className="flex items-center gap-2">
                    <DefectCounter
                      value={entry.qty}
                      onChange={(next) => defects.setQty(entry.id, next)}
                      min={1}
                      max={99}
                      label={DEFECT_TYPE_LABELS[entry.type]}
                    />
                    <button
                      type="button"
                      onClick={() => defects.removeEntry(entry.id)}
                      aria-label={`Hapus defect ${DEFECT_TYPE_LABELS[entry.type]}`}
                      className={cn(
                        PILL_GHOST,
                        'h-9 w-9 shrink-0 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2',
                      )}
                    >
                      <Trash2 className="h-4 w-4" aria-hidden="true" />
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>

        {/* 5. Bukti foto + keputusan QC */}
        <section className={cn(CARD, 'flex flex-col gap-3')}>
          <h2 className="text-sm font-semibold tracking-tight text-foreground">
            Bukti &amp; Keputusan
          </h2>

          <PhotoUpload value={photo} onChange={setPhoto} disabled={busy} />

          <fieldset className="flex flex-col gap-1">
            <legend className="text-xs font-medium text-muted-foreground">
              Keputusan QC (dipakai tombol SUBMIT)
            </legend>
            {QC_DECISIONS.map((option) => (
              <label
                key={option}
                className="flex cursor-pointer items-center gap-3 rounded-lg px-2 py-2.5 transition-colors hover:bg-muted/50"
              >
                <input
                  type="radio"
                  name="qc-decision"
                  value={option}
                  checked={decision === option}
                  onChange={() => setDecision(option)}
                  className="h-4 w-4 shrink-0 accent-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                />
                <span className="text-sm text-foreground">{QC_ACTION_LABELS[option]}</span>
              </label>
            ))}
          </fieldset>
        </section>

        {actionError !== null ? (
          <p role="alert" className="text-sm font-medium text-accent-coral">
            {actionError}
          </p>
        ) : null}

        {submitError !== null ? (
          <p role="alert" className="text-sm font-medium text-accent-coral">
            {submitError}
          </p>
        ) : null}

        {notice !== null ? <p className="text-sm text-muted-foreground">{notice}</p> : null}
      </div>

      <Toast
        open={syncToast !== null}
        onOpenChange={() => setSyncToast(null)}
        tone={syncToast?.tone ?? 'default'}
        title={syncToast?.title ?? ''}
        description={syncToast?.description}
      />

      {/* Footer aksi (Screen C) */}
      <div className="fixed inset-x-0 bottom-0 z-30 border-t border-border/40 bg-background/95 p-4 backdrop-blur">
        <div className="mx-auto max-w-lg space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <ActionButton
              variant="rework"
              label="REWORK"
              onAction={() => setConfirmAction('BUNDLE_REWORK')}
              size="hp"
              loading={pending === 'BUNDLE_REWORK'}
              disabled={!canRework || defects.isEmpty || busy}
            />
            <ActionButton
              variant="scrap"
              label="SCRAP"
              onAction={() => setConfirmAction('BUNDLE_SCRAP')}
              size="hp"
              loading={pending === 'BUNDLE_SCRAP'}
              disabled={!canScrap || defects.isEmpty || busy}
            />
          </div>

          {/* F11/11.2a — BUNDLE_QC (SEWING → QC): aksi nyata lewat queue offline-safe yang sama. */}
          <ActionButton
            variant="qc"
            label="LULUS QC"
            onAction={() => setConfirmAction('BUNDLE_QC')}
            size="hp"
            loading={pending === 'BUNDLE_QC'}
            disabled={!canQc || busy}
          />

          <Button
            variant="primary"
            size="lg"
            className="w-full"
            loading={submitting}
            disabled={defects.isEmpty || busy}
            onClick={() => {
              void handleSubmitRecord();
            }}
          >
            SUBMIT
          </Button>

          {!canQc && !canRework && !canScrap ? (
            <p className="text-center text-xs text-muted-foreground">
              Backend tidak mengizinkan QC/REWORK/SCRAP untuk bundle ini - pakai SUBMIT untuk
              mencatat inspeksi.
            </p>
          ) : null}
        </div>
      </div>

      <Modal
        open={confirmAction !== null}
        onOpenChange={(open) => {
          if (!open) setConfirmAction(null);
        }}
        title={CONFIRM_TITLE[confirmAction ?? 'BUNDLE_REWORK']}
        description={
          confirmAction === 'BUNDLE_SCRAP'
            ? `Bundle ${bundle.code} akan dibuang permanen. Lanjutkan?`
            : confirmAction === 'BUNDLE_QC'
              ? `Bundle ${bundle.code} dinyatakan lolos sewing (masuk tahap QC). Lanjutkan?`
              : `Bundle ${bundle.code} dikembalikan ke work center sebelumnya untuk rework. Lanjutkan?`
        }
        footer={
          <>
            {/* F11/11.1 — jalan masuk ke form scrap lengkap (qty + alasan) dari modal konfirmasi. */}
            {confirmAction === 'BUNDLE_SCRAP' ? (
              <Button
                variant="ghost"
                onClick={() => {
                  setConfirmAction(null);
                  navigate(`/production/scrap/${id ?? ''}`);
                }}
              >
                Isi Form Scrap
              </Button>
            ) : null}
            <Button variant="secondary" onClick={() => setConfirmAction(null)}>
              Batal
            </Button>
            <Button
              variant={confirmAction === 'BUNDLE_QC' ? 'primary' : 'danger'}
              loading={busy}
              onClick={() => {
                if (confirmAction === null) return;
                void handleDecision(confirmAction);
              }}
            >
              {CONFIRM_BUTTON[confirmAction ?? 'BUNDLE_REWORK']}
            </Button>
          </>
        }
      >
        <ul className="flex flex-col gap-1">
          {defects.entries.map((entry) => (
            <li key={entry.id} className="text-sm text-muted-foreground">
              {DEFECT_TYPE_LABELS[entry.type]} - {DEFECT_REGION_LABELS[entry.location]} x
              {entry.qty}
            </li>
          ))}
        </ul>
      </Modal>

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
