import { postSyncOdoo, postSyncScrap, type SyncStage, type SyncStageInput } from '@/api/sync';
import type { ApiClient } from '@/integrations/api-client';

/**
 * sync-actions.ts - logika MURNI tombol sync manual ERP (F6).
 *
 * Dipisah dari halaman supaya bisa diuji tanpa DOM (jsdom tidak jalan di bun):
 *  - `canSync*` = guard state bundle (§6.6);
 *  - `buildBundleSyncInput` = body kontrak §5.1;
 *  - `runBundleStageSync`/`runScrapSync` = pemanggil `postSyncOdoo`/`postSyncScrap`
 *    (adapter F2, signature TIDAK diubah) yang selalu mengembalikan union
 *    `{ok, message}` — tidak pernah throw supaya UI cukup menampilkan pesan.
 *
 * PENTING: `POST /sync/*` berefek samping NYATA di Odoo (tulis stok). Tombol ini
 * hanya memanggil API saat operator menekannya — tidak pernah otomatis.
 */

/** State bundle yang boleh sync WIP (produksi sedang berjalan, belum selesai). */
export const WIP_SYNC_STATES = ['CUTTING', 'SEWING', 'QC'] as const;

/** State bundle yang boleh sync FG (barang jadi siap terima). */
export const FG_SYNC_STATES = ['DONE'] as const;

/** State bundle yang boleh sync scrap manual (halaman QC — §6.6). */
export const SCRAP_SYNC_STATES = ['QC'] as const;

function inStates(state: string, states: readonly string[]): boolean {
  return states.includes(state.trim().toUpperCase());
}

/** PURE - boleh sync WIP (bahan keluar) untuk state ini? */
export function canSyncWip(state: string): boolean {
  return inStates(state, WIP_SYNC_STATES);
}

/** PURE - boleh sync FG (barang jadi) untuk state ini? */
export function canSyncFg(state: string): boolean {
  return inStates(state, FG_SYNC_STATES);
}

/** PURE - boleh sync scrap manual untuk state ini? */
export function canSyncScrap(state: string): boolean {
  return inStates(state, SCRAP_SYNC_STATES);
}

export interface BundleSyncSource {
  id: number | string;
  code: string;
  qty: number;
}

/** PURE - body kontrak §5.1 untuk satu bundle: `{resource, resource_id, payload:{qty, ref}}`. */
export function buildBundleSyncInput(bundle: BundleSyncSource, stage: SyncStage): SyncStageInput {
  return {
    resource: 'bundle',
    resource_id: String(bundle.id),
    payload: { qty: bundle.qty, ref: `${stage}-${bundle.code}` },
  };
}

export interface SyncActionResult {
  ok: boolean;
  message: string;
}

/**
 * Kirim sync two-stage (WIP/FG) untuk satu bundle. `postSyncOdoo` melempar saat HTTP
 * gagal (mis. 403 tanpa session) → ditangkap & diterjemahkan jadi pesan.
 */
export async function runBundleStageSync(
  client: ApiClient,
  stage: SyncStage,
  bundle: BundleSyncSource,
): Promise<SyncActionResult> {
  try {
    const queued = await postSyncOdoo(client, stage, buildBundleSyncInput(bundle, stage));

    return { ok: true, message: `Sync ${stage} di-queue (task ${queued.task_id}).` };
  } catch (caught) {
    return {
      ok: false,
      message: caught instanceof Error ? caught.message : `Sync ${stage} gagal dikirim.`,
    };
  }
}

/** Kirim sync scrap manual (semua ScrapAccumulator pending) — `{sent, failed, skipped}`. */
export async function runScrapSync(client: ApiClient): Promise<SyncActionResult> {
  try {
    const result = await postSyncScrap(client);

    return {
      ok: true,
      message: `Scrap terkirim: ${result.sent} sukses, ${result.failed} gagal, ${result.skipped} dilewati.`,
    };
  } catch (caught) {
    return {
      ok: false,
      message: caught instanceof Error ? caught.message : 'Sync scrap gagal dikirim.',
    };
  }
}
