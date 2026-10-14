/**
 * state-display.ts - jembatan tampilan v2 -> v3 + label tampilan domain.
 *
 * Halaman lama (yang belum ditulis ulang di Fase 17) menerima `state` MENTAH dari
 * backend (`DRAFT` / `CUTTING` / `SEWING` / `QC` / `DONE` / `SCRAPPED`) dan perlu
 * memetakannya ke status komponen baru (`StatusChip`, `BundleCard`).
 *
 * Ditaruh di `lib/` (bukan di file komponen) supaya file komponen hanya mengekspor
 * komponen - syarat Fast Refresh (`react/only-export-components`).
 */

import type { DefectRegion, DefectType } from '@/types/qc';
import type { BadgeTone } from '@/components/atoms/Badge';

export type StatusChipStatus = 'on_track' | 'delay' | 'bottleneck' | 'neutral';

export type BundleCardStatus = 'waiting' | 'in_progress' | 'done' | 'rework' | 'scrap';

const CHIP_STATUS_BY_STATE: Record<string, StatusChipStatus> = {
  DRAFT: 'neutral',
  CUTTING: 'on_track',
  SEWING: 'on_track',
  QC: 'delay',
  DONE: 'on_track',
  SCRAPPED: 'bottleneck',
};

const CARD_STATUS_BY_STATE: Record<string, BundleCardStatus> = {
  DRAFT: 'waiting',
  CUTTING: 'in_progress',
  SEWING: 'in_progress',
  QC: 'in_progress',
  DONE: 'done',
  SCRAPPED: 'scrap',
};

/** PURE - state backend -> status `StatusChip` (fallback `neutral`). */
export function chipStatusFromState(state: string): StatusChipStatus {
  const mapped = CHIP_STATUS_BY_STATE[state.toUpperCase()];
  return mapped === undefined ? 'neutral' : mapped;
}

/** PURE - state backend -> status `BundleCard` (fallback `waiting`). */
export function cardStatusFromState(state: string): BundleCardStatus {
  const mapped = CARD_STATUS_BY_STATE[state.toUpperCase()];
  return mapped === undefined ? 'waiting' : mapped;
}

/* ------------------------------------------------------------------
   Label tampilan QC (Fase 18) - dipakai QCPage + 3 halaman Quality.
   Nilai enum tetap snake_case dari backend; hanya LABEL yang diterjemahkan.
   ------------------------------------------------------------------ */

export const DEFECT_TYPE_LABELS: Record<DefectType, string> = {
  jahitan_loncat: 'Jahitan Loncat',
  ukuran_tidak_sesuai: 'Ukuran Tidak Sesuai',
  kain_rusak: 'Kain Rusak',
  lainnya: 'Lainnya',
};

export const DEFECT_REGION_LABELS: Record<DefectRegion, string> = {
  sleeve_left: 'Lengan kiri',
  sleeve_right: 'Lengan kanan',
  body: 'Badan',
  collar: 'Kerah',
  hem: 'Keliman bawah',
  pocket: 'Kantong',
};

export const QC_ACTION_LABELS: Record<'rework' | 'scrap', string> = {
  rework: 'Rework',
  scrap: 'Scrap',
};

/* ------------------------------------------------------------------
   F8 — tampilan readiness material (WAITING/PARTIAL/READY, §5.4).
   Nilai enum tetap dari backend; hanya LABEL & TONE yang dipetakan.
   ------------------------------------------------------------------ */

/** Label Indonesia untuk status readiness. */
export const READINESS_STATUS_LABELS: Record<string, string> = {
  WAITING: 'Menunggu PO',
  PARTIAL: 'Sebagian',
  READY: 'Siap',
};

/** Label untuk baris yang belum pernah dihitung (status `null`). */
export const READINESS_UNCOMPUTED_LABEL = 'Belum dihitung';

/**
 * PURE — status readiness → tone `Badge` (token OKLCH, TANPA warna hardcode).
 * `READY` = biru (aman), `PARTIAL` = coral (butuh perhatian), `WAITING` = muted,
 * nilai asing/`null` = default.
 */
export function readinessTone(status: string | null): BadgeTone {
  switch (status) {
    case 'READY':
      return 'blue';
    case 'PARTIAL':
      return 'coral';
    case 'WAITING':
      return 'muted';
    default:
      return 'default';
  }
}

/** PURE — label siap-tampil untuk status readiness (`null` = belum dihitung). */
export function readinessLabel(status: string | null): string {
  if (status === null) return READINESS_UNCOMPUTED_LABEL;

  return READINESS_STATUS_LABELS[status] ?? status;
}

/* ------------------------------------------------------------------
   F15 — tampilan status SYNC (PENDING/SENT/FAILED/DUPLICATE).
   Dipakai halaman monitoring: Invoice Queue + Sync Monitor.
   ------------------------------------------------------------------ */

/** Label Indonesia untuk `SyncStatus`. */
export const SYNC_STATUS_LABELS: Record<string, string> = {
  PENDING: 'Menunggu',
  SENT: 'Terkirim',
  FAILED: 'Gagal',
  DUPLICATE: 'Duplikat',
  // H1.7 — resource MES-only (mis. `master.work_center`): ledger ditulis tapi
  // memang tidak dikirim ke ERP (lihat `erp_sync/idempotency.mark_skipped`).
  SKIPPED: 'Dilewati',
};

/**
 * PURE — status sync → tone `Badge` (token OKLCH, tanpa warna hardcode).
 * `SENT` = biru (aman), `FAILED` = coral (butuh tindakan), `PENDING` = muted,
 * `DUPLICATE`/asing = default.
 */
export function syncStatusTone(status: string): BadgeTone {
  switch (status.trim().toUpperCase()) {
    case 'SENT':
      return 'blue';
    case 'FAILED':
      return 'coral';
    case 'PENDING':
      return 'muted';
    default:
      return 'default';
  }
}

/** PURE — label siap-tampil status sync (`''` → `-`). */
export function syncStatusLabel(status: string): string {
  const key = status.trim().toUpperCase();
  if (key.length === 0) return '-';

  return SYNC_STATUS_LABELS[key] ?? status;
}
