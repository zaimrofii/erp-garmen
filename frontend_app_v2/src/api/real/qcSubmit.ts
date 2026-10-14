// REAL - submit defect QC (F3A.CLOSE flip / backend B7b).
// Endpoint: POST /api/v1/quality/defects/ — `action=scrap` delegasi ke BUNDLE_SCRAP,
// `action=rework` mencatat BundleEvent + siklus QC_REWORK (sisi backend).
import type { ApiClient } from '@/integrations/api-client';
import { unwrap } from '../client';

export const QUALITY_DEFECTS_PATH = '/quality/defects/';

export type DefectAction = 'rework' | 'scrap';

/** Body POST sesuai backend (`bundle_id` WAJIB — bukan `bundle_code`). */
export interface DefectSubmitInput {
  bundle_id: number;
  defect_type: string;
  qty: number;
  reason?: string;
  action: DefectAction;
}

export interface DefectSubmitResult {
  ok: boolean;
  bundle_event_id: string | null;
  /** Hanya ada untuk `action='rework'`. */
  cycle_instance_id: number | null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/** PURE — respons mentah → `DefectSubmitResult`. */
export function readDefectSubmitResult(raw: unknown): DefectSubmitResult {
  const record = isRecord(raw) ? raw : {};

  return {
    ok: record['ok'] === true,
    bundle_event_id:
      typeof record['bundle_event_id'] === 'string' ? record['bundle_event_id'] : null,
    cycle_instance_id:
      typeof record['cycle_instance_id'] === 'number' ? record['cycle_instance_id'] : null,
  };
}

/** Kirim defect baru. Gagal HTTP → melempar (`unwrap`). */
export async function submitDefect(
  client: ApiClient,
  input: DefectSubmitInput,
): Promise<DefectSubmitResult> {
  const res = await client.post<unknown>(QUALITY_DEFECTS_PATH, {
    bundle_id: input.bundle_id,
    defect_type: input.defect_type,
    qty: input.qty,
    reason: input.reason ?? '',
    action: input.action,
  });

  return readDefectSubmitResult(unwrap(res));
}
