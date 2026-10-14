// REAL - wrap integration engine v1 (api-client). Endpoint: GET /garmen/qc/, GET /garmen/qc/{id}/
//
// Resource backend `qc` = ScrapAccumulator (read-only, kontrak §4.5: "QC = ScrapAccumulator
// (read-only, tidak ada action POST)"). F2/2.3 - adapter BARU: key LAMA di barrel `api/qc.ts`
// (`qcLog`/`qcAql`/`qcRework`/`qcSubmit`) tetap dummy karena `/quality/*` belum ada.
import type { ApiClient } from '@/integrations/api-client';
import type { ListPage } from '@/lib/schemas/list.schema';
import type { QcDetail, QcRow } from '@/types/qc-row';
import { unwrap } from '../client';

/** Path relatif terhadap `VITE_API_BASE_URL`. */
export const QC_PATH = '/garmen/qc/';

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function readNumber(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0;
}

function readNullableString(value: unknown): string | null {
  return typeof value === 'string' ? value : null;
}

/**
 * PURE - satu baris `qc` mentah -> `QcRow`. `null` kalau bukan objek / `id` bukan angka
 * (baris rusak dibuang, bukan menjatuhkan seluruh halaman).
 */
export function readQcRow(raw: unknown): QcRow | null {
  if (!isRecord(raw)) return null;

  const id = raw['id'];
  if (typeof id !== 'number' || !Number.isFinite(id)) return null;

  return {
    id,
    work_center_code: readNullableString(raw['work_center_code']),
    bundle_code: readNullableString(raw['bundle_code']),
    qty: readNumber(raw['qty']),
    rework_qty: readNumber(raw['rework_qty']),
    end_loss_qty: readNumber(raw['end_loss_qty']),
    reason: readNullableString(raw['reason']),
  };
}

/**
 * PURE - semua baris valid dari `page.rows` (baris rusak dilewati, urutan dipertahankan).
 * Menerima array mentah supaya bisa dipakai sebelum envelope divalidasi Zod.
 */
export function readQcRows(rows: readonly unknown[]): QcRow[] {
  const parsed: QcRow[] = [];

  for (const raw of rows) {
    const row = readQcRow(raw);
    if (row !== null) parsed.push(row);
  }

  return parsed;
}

/** Daftar catatan QC (offset paginasi - pola `getBundles`). */
export async function getQcRows(
  client: ApiClient,
  params: { limit?: number; offset?: number } = {},
): Promise<ListPage> {
  const qs = new URLSearchParams();
  if (params.limit != null) qs.set('limit', String(params.limit));
  if (params.offset != null) qs.set('offset', String(params.offset));
  const suffix = qs.toString() ? `?${qs}` : '';

  const res = await client.get<ListPage>(`${QC_PATH}${suffix}`);
  return unwrap(res);
}

/** Detail satu catatan QC (`version` dipakai untuk optimistic lock). */
export async function getQcRow(client: ApiClient, id: number | string): Promise<QcDetail> {
  const res = await client.get<QcDetail>(`${QC_PATH}${id}/`);
  return unwrap(res);
}

export type { QcDetail, QcRow } from '@/types/qc-row';
