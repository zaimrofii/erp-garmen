// REAL - WIP per WC FLAT tanpa trend/series (F3A.CLOSE flip / backend B21).
// Endpoint: GET /api/v1/reports/wip/by-wc/
import type { ApiClient } from '@/integrations/api-client';
import { getParsed, isRecord, readNum, readStr } from './_shape';

export const WIP_BY_WC_PATH = '/reports/wip/by-wc/';

export interface WipByWcRow {
  wc_code: string;
  wc_name: string;
  wip_qty: number;
  queue_depth: number;
  /** Umur bundle WIP tertua di WC tsb (jam, 1 desimal). */
  oldest_bundle_age_hours: number;
}

export interface WipByWcReport {
  rows: WipByWcRow[];
  total_wip: number;
  generated_at: string;
}

/** PURE — respons mentah → `WipByWcReport`; `null` kalau `rows` bukan array. */
export function readWipByWcReport(raw: unknown): WipByWcReport | null {
  if (!isRecord(raw)) return null;
  const rows = raw['rows'];
  if (!Array.isArray(rows)) return null;

  const parsed: WipByWcRow[] = [];
  for (const row of rows) {
    if (!isRecord(row)) continue;
    parsed.push({
      wc_code: readStr(row['wc_code']),
      wc_name: readStr(row['wc_name']),
      wip_qty: readNum(row['wip_qty']),
      queue_depth: readNum(row['queue_depth']),
      oldest_bundle_age_hours: readNum(row['oldest_bundle_age_hours']),
    });
  }

  return {
    rows: parsed,
    total_wip: readNum(raw['total_wip']),
    generated_at: readStr(raw['generated_at']),
  };
}

/** Baca laporan WIP ringkas. Gagal HTTP → melempar. */
export async function fetchWipByWc(client: ApiClient): Promise<WipByWcReport> {
  return getParsed(client, WIP_BY_WC_PATH, readWipByWcReport, 'WIP per work center');
}
