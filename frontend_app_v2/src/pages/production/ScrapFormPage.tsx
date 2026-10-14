import { useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { ArrowLeft, Ban, Trash2 } from 'lucide-react';
import { Badge } from '@/components/atoms/Badge';
import { Button } from '@/components/atoms/Button';
import { Input } from '@/components/atoms/Input';
import { Modal } from '@/components/atoms/Modal';
import { Spinner } from '@/components/atoms/Spinner';
import { Textarea } from '@/components/atoms/Textarea';
import { Toast, type ToastTone } from '@/components/atoms/Toast';
import { PageHeader } from '@/components/molecules/PageHeader';
import { submitBundleAction } from '@/api/bundles';
import { useFeedback } from '@/app/app-runtime';
import { useApiClient } from '@/hooks/useApiClient';
import { useBundle } from '@/hooks/useBundle';
import { BUNDLE_ACTION_IDS, canRunBundleAction, hasAllowedAction } from '@/lib/action-runner';
import { generateUUID } from '@/lib/uuid';
import { cn } from '@/lib/cn';
import { CARD } from '@/lib/tokens';

/**
 * ScrapFormPage - route `/production/scrap/:id` (F11/11.1).
 *
 * Form scrap satu bundle → `POST /garmen/bundles/{id}/BUNDLE_SCRAP/` (kontrak §4.4,
 * state machine `garment.bundle`: DRAFT/CUTTING/SEWING/QC → DONE, mode PESSIMISTIC).
 *
 * Dikirim lewat `submitBundleAction` (jalur ONLINE-only halaman detail, path dari segmen
 * id + action apa adanya) dengan `Idempotency-Key` + `X-Base-Version` (optimistic lock):
 *   - `idempotencyKey` → anti dobel-klik/retry (backend menyimpan replay);
 *   - `baseVersion`    → 409 kalau bundle sudah berubah di server (pesan ditampilkan apa adanya).
 *
 * PENTING (hasil recon backend, dicatat di laporan F11): executor aksi TIDAK menyimpan field
 * tambahan dari body — yang berubah hanya `state` (+ `updated_at`/`version`) dan
 * `expected_result.fields` berisi `state` + `scrap: True` (`EXTRA_CRITICAL_FIELDS`). Jadi
 * `scrap_qty`/`reason` di sini = catatan konfirmasi operator di layar (juga masuk hash
 * idempotensi), BUKAN kolom yang tersimpan di bundle. Qty yang benar-benar dikirim ke Odoo
 * tetap lewat jalur sync scrap (F6, `POST /sync/scrap/`).
 *
 * Guard submit (11.1d): qty bilangan ≥ 1 dan ≤ `bundle.qty`, alasan ≥ 3 karakter, id aksi ADA
 * di `allowed_actions` (metadata backend), state sekarang SAH menurut state machine, dan tidak
 * sedang mengirim. Salah satu gagal → tombol mati + pesan penyebabnya (bukan diam-diam 400).
 */

const MIN_REASON_LENGTH = 3;

interface ToastState {
  tone: ToastTone;
  title: string;
  description: string;
}

/** PURE — string input user → qty ≥ 1, atau `null` kalau bukan bilangan. */
function parseScrapQty(value: string): number | null {
  const trimmed = value.trim();
  if (!/^\d+$/.test(trimmed)) return null;

  const parsed = Number(trimmed);

  return parsed >= 1 ? parsed : null;
}

export function ScrapFormPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const client = useApiClient();
  const { trigger } = useFeedback();

  const { data: bundle, isLoading, error: loadError, refetch } = useBundle(id);

  const [qtyInput, setQtyInput] = useState('1');
  const [reason, setReason] = useState('');
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [toast, setToast] = useState<ToastState | null>(null);

  const allowedActions = useMemo(() => bundle?.allowed_actions ?? [], [bundle]);
  const metadataAllows = hasAllowedAction(allowedActions, BUNDLE_ACTION_IDS.SCRAP);
  const stateAllows = canRunBundleAction(BUNDLE_ACTION_IDS.SCRAP, bundle?.state);

  const qty = parseScrapQty(qtyInput);
  const bundleQty = bundle?.qty;
  const qtyError =
    qty === null
      ? 'Isi jumlah pcs (bilangan minimal 1).'
      : bundleQty !== undefined && qty > bundleQty
        ? `Maksimal ${String(bundleQty)} pcs (qty bundle).`
        : undefined;
  const reasonError =
    reason.trim().length < MIN_REASON_LENGTH
      ? `Alasan minimal ${String(MIN_REASON_LENGTH)} karakter.`
      : undefined;

  const canSubmit =
    bundle !== undefined &&
    metadataAllows &&
    stateAllows &&
    qtyError === undefined &&
    reasonError === undefined &&
    !submitting;

  async function handleConfirm(): Promise<void> {
    if (id === undefined || bundle === undefined || qty === null) return;

    setConfirmOpen(false);
    setSubmitting(true);

    try {
      const outcome = await submitBundleAction(
        client,
        id,
        BUNDLE_ACTION_IDS.SCRAP,
        { scrap_qty: qty, reason: reason.trim() },
        { idempotencyKey: generateUUID(), baseVersion: bundle.version },
      );

      trigger('success');
      setToast({
        tone: 'success',
        title: 'Bundle di-scrap',
        description: `${bundle.code} → ${outcome.state} (${String(qty)} pcs, ${reason.trim()}).`,
      });
      setQtyInput('1');
      setReason('');
      void refetch();
      navigate('/production/scan');
    } catch (caught) {
      trigger('error');
      setToast({
        tone: 'error',
        title: 'Scrap gagal',
        description:
          caught instanceof Error ? caught.message : 'Aksi BUNDLE_SCRAP gagal dikirim.',
      });
    } finally {
      setSubmitting(false);
    }
  }

  const blockedMessage = !metadataAllows
    ? 'Backend tidak mengizinkan SCRAP untuk bundle ini (tidak ada di allowed_actions).'
    : !stateAllows
      ? `Bundle berstatus ${bundle?.state ?? '-'} — SCRAP hanya berlaku untuk DRAFT/CUTTING/SEWING/QC.`
      : null;

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <PageHeader
        title="Form Scrap Bundle"
        subtitle="Buang bundle + catat alasan (aksi nyata: state bundle berubah menjadi DONE)"
        breadcrumb={[{ label: 'Production' }, { label: 'Scrap' }]}
        actions={
          <Button
            variant="ghost"
            icon={ArrowLeft}
            onClick={() => {
              navigate(id === undefined ? '/production/scan' : `/production/qc/${id}`);
            }}
          >
            Kembali
          </Button>
        }
      />

      {isLoading ? (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Spinner size="sm" /> Memuat bundle…
        </div>
      ) : null}

      {loadError !== null && loadError !== undefined ? (
        <section className={cn(CARD, 'flex flex-col gap-2')}>
          <p role="alert" className="text-sm font-medium text-accent-coral">
            Gagal memuat bundle (perlu login atau bundle tidak ada).
          </p>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => {
              void refetch();
            }}
          >
            Coba Lagi
          </Button>
        </section>
      ) : null}

      {bundle !== undefined ? (
        <section className={cn(CARD, 'flex flex-wrap items-center gap-3')}>
          <span className="font-mono text-sm font-semibold text-foreground">{bundle.code}</span>
          <Badge tone="coral">{bundle.state}</Badge>
          <span className="text-xs text-muted-foreground">
            {String(bundle.qty)} pcs · WC {bundle.current_work_center_code ?? '-'}
          </span>
        </section>
      ) : null}

      {blockedMessage !== null ? (
        <section
          className={cn(CARD, 'flex items-start gap-2 border-accent-coral/40 bg-accent-coral/10')}
        >
          <Ban className="mt-0.5 h-4 w-4 shrink-0 text-accent-coral" aria-hidden="true" />
          <p role="alert" className="text-sm text-foreground">
            {blockedMessage}
          </p>
        </section>
      ) : null}

      <section className={cn(CARD, 'flex flex-col gap-4')}>
        <Input
          type="number"
          min={1}
          max={bundleQty}
          label="Qty scrap (pcs)"
          value={qtyInput}
          {...(qtyError === undefined ? {} : { error: qtyError })}
          onChange={(event) => {
            setQtyInput(event.target.value);
          }}
        />

        <Textarea
          label="Alasan scrap"
          rows={3}
          value={reason}
          placeholder="mis. kain sobek di bagian badan setelah QC"
          {...(reasonError === undefined ? {} : { error: reasonError })}
          onChange={(event) => {
            setReason(event.target.value);
          }}
        />

        <Button
          variant="danger"
          icon={Trash2}
          size="lg"
          className="w-full"
          loading={submitting}
          disabled={!canSubmit}
          onClick={() => {
            setConfirmOpen(true);
          }}
        >
          SCRAP BUNDLE
        </Button>
      </section>

      <Modal
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        title="Konfirmasi SCRAP"
        description={`Bundle ${bundle?.code ?? '-'} akan dibuang permanen (state menjadi DONE). Lanjutkan?`}
        footer={
          <>
            <Button variant="secondary" onClick={() => setConfirmOpen(false)}>
              Batal
            </Button>
            <Button
              variant="danger"
              loading={submitting}
              onClick={() => {
                void handleConfirm();
              }}
            >
              SCRAP
            </Button>
          </>
        }
      >
        <ul className="flex flex-col gap-1 text-sm text-muted-foreground">
          <li>Qty: {qty === null ? '-' : `${String(qty)} pcs`}</li>
          <li>Alasan: {reason.trim()}</li>
          <li>Aksi: {BUNDLE_ACTION_IDS.SCRAP} (state → DONE, scrap=true)</li>
        </ul>
      </Modal>

      <Toast
        open={toast !== null}
        onOpenChange={(open) => {
          if (!open) setToast(null);
        }}
        tone={toast?.tone ?? 'default'}
        title={toast?.title ?? ''}
        description={toast?.description}
      />
    </div>
  );
}
