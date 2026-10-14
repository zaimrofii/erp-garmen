// REAL - wrap integration engine v1 (api-client). Endpoint: POST /print/kupon/ + /print/bundle-tag/
//
// F6 - adapter kupon (kontrak §7.2):
//   body  : {"ticket_code": "TKT-0001"}   <- WAJIB; BUKAN bundle_id
//   sukses: {ok, resource, resource_id, bytes, backend, print_job_id, ref, status}
//   gagal : 400 {"detail": "..."} (kupon/order line tidak ada, field kosong, printer gagal)
//
// F14 (opsi B: migrasi penuh) - `printBundleTag` DIPINDAH ke sini dari
// `integrations/print-tag.ts` (file itu dihapus). Body `{"bundle_id": <id>}` (§7.1) dan
// bentuk respons SAMA PERSIS dengan kupon (`send_to_printer` di backend) — dikonfirmasi
// live: `{"bundle_id":1}` → 200 `{ok:true, resource:"bundle", resource_id:"1", bytes:292,
// backend:"mock", print_job_id:19, ref:"BND-DEMO-001", status:"SENT"}`.
//
// Kedua endpoint `AllowAny` (live: POST body kosong/tidak valid → **400**, bukan 403/404).
import type { ApiClient } from '@/integrations/api-client';
import { unwrap } from '../client';

/** Path relatif terhadap `VITE_API_BASE_URL`. */
export const PRINT_COUPON_PATH = '/print/kupon/';

/** F14 — `POST /print/bundle-tag/` (§7.1). */
export const PRINT_BUNDLE_TAG_PATH = '/print/bundle-tag/';

/** Body `POST /print/kupon/` (§7.2). */
export interface PrintCouponInput {
  ticket_code: string;
}

/** Body `POST /print/bundle-tag/` (§7.1). */
export interface PrintBundleTagInput {
  bundle_id: number | string;
}

/** Respons sukses cetak (kupon & bundle-tag memakai bentuk yang sama). */
export interface PrintJobResponse {
  ok: boolean;
  resource: string;
  resource_id: string;
  /** Jumlah bytes ESC/POS yang benar-benar dikirim ke printer. */
  bytes: number;
  backend: string;
  print_job_id: number | null;
  ref: string;
  status: string;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/**
 * PURE - response cetak mentah → `PrintJobResponse`; `null` kalau bentuknya tidak
 * dikenali (pemanggil membedakan "gagal parse" dari "gagal cetak").
 */
export function readPrintJob(raw: unknown): PrintJobResponse | null {
  if (!isRecord(raw)) return null;
  if (raw['ok'] !== true) return null;

  const bytes = raw['bytes'];
  if (typeof bytes !== 'number' || !Number.isFinite(bytes)) return null;

  const resourceId = raw['resource_id'];

  return {
    ok: true,
    resource: typeof raw['resource'] === 'string' ? raw['resource'] : '',
    resource_id: typeof resourceId === 'string' ? resourceId : String(resourceId ?? ''),
    bytes,
    backend: typeof raw['backend'] === 'string' ? raw['backend'] : 'printer',
    print_job_id: typeof raw['print_job_id'] === 'number' ? raw['print_job_id'] : null,
    ref: typeof raw['ref'] === 'string' ? raw['ref'] : '',
    status: typeof raw['status'] === 'string' ? raw['status'] : '',
  };
}

/**
 * Cetak kupon piece-rate dari `ticket_code`. Gagal HTTP (400/403/…) → melempar
 * pesan backend (`unwrap`); bentuk respons tak dikenal → melempar pesan jelas.
 */
export async function printCoupon(
  client: ApiClient,
  ticketCode: string,
): Promise<PrintJobResponse> {
  const body: PrintCouponInput = { ticket_code: ticketCode.trim() };
  const res = await client.post<unknown>(PRINT_COUPON_PATH, body);
  const parsed = readPrintJob(unwrap(res));

  if (parsed === null) {
    throw new Error('Bentuk respons cetak kupon tidak dikenali.');
  }

  return parsed;
}

/* --------------------------------------------------------------------------
   F14 — cetak tag bundle (`POST /print/bundle-tag/`, §7.1).
   -------------------------------------------------------------------------- */

/**
 * PURE — body `POST /print/bundle-tag/`: `bundle_id` numerik kalau bisa di-`Number()`,
 * kalau tidak dikirim apa adanya (perilaku lama `integrations/print-tag.ts` dipertahankan
 * supaya tidak ada regresi untuk pemanggil yang mengirim id non-numerik).
 */
export function buildPrintBundleTagBody(bundleId: number | string): PrintBundleTagInput {
  const numeric = Number(bundleId);

  return { bundle_id: Number.isFinite(numeric) && String(bundleId).trim() !== '' ? numeric : bundleId };
}

/**
 * Cetak tag bundle (QR + barcode). Gagal HTTP (400 bundle tidak ada / printer gagal) →
 * melempar pesan backend (`unwrap`); bentuk respons tak dikenal → melempar pesan jelas.
 *
 * F14: jalur ini MENGGANTIKAN `integrations/print-tag.ts` (dihapus) — pemanggilnya
 * `PrintTagButton` yang kini menangkap error sendiri untuk Toast.
 */
export async function printBundleTag(
  client: ApiClient,
  bundleId: number | string,
): Promise<PrintJobResponse> {
  const res = await client.post<unknown>(
    PRINT_BUNDLE_TAG_PATH,
    buildPrintBundleTagBody(bundleId),
  );
  const parsed = readPrintJob(unwrap(res));

  if (parsed === null) {
    throw new Error('Bentuk respons cetak tag bundle tidak dikenali.');
  }

  return parsed;
}
