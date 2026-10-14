import type { AllowedAction } from '@/lib/schemas/action.schema';

/**
 * qc-row.ts - tipe resource backend `qc` = **ScrapAccumulator** (F2/2.3).
 *
 * PENTING (keputusan F2 opsi a): ini tipe **BARU** untuk `GET /garmen/qc/`, SENGAJA
 * terpisah dari `types/qc.ts` (`QCLog` = form defect visual: `defect_entries`, `action`,
 * `created_at`, `wc_asal`) yang **tidak punya endpoint backend**.
 * JANGAN memetakan baris nyata -> `QCLog`: `action`/`defect_entries`/`created_at` harus
 * DIKARANG kalau dipaksa (lossy). Halaman QC lama tetap dummy sampai F3+ memutuskan UI-nya.
 *
 * Field `snake_case` dari backend dipakai APA ADANYA (kontrak §2.3 + §4.5).
 */

/** Satu baris `GET /garmen/qc/` (ScrapAccumulator per work center). */
export interface QcRow {
  id: number;
  /** Kode work center pencatat (`work_center.code`). */
  work_center_code: string | null;
  bundle_code: string | null;
  qty: number;
  rework_qty: number;
  end_loss_qty: number;
  reason: string | null;
}

/** `GET /garmen/qc/{id}/` — detail + `version` (optimistic lock) + `allowed_actions`. */
export interface QcDetail extends QcRow {
  bundle_id: number | null;
  notes: string;
  updated_at: string;
  version: string;
  allowed_actions: AllowedAction[];
}
