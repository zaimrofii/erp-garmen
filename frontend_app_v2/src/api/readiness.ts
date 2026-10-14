// ADAPTER - satu-satunya pintu material readiness (TANPA logic domain).
//
// Halaman WAJIB mengimpor dari sini - JANGAN dari `./real/*` langsung.
//
// F2/2.9b - MODE `readiness` === 'real': `GET /garmen/orders/{id}/readiness/` (§5.4),
// `IsAuthenticated` (anon 403). Path memakai `orders` (id ORDER, bukan OrderLine) —
// helper `buildOrderReadinessPath` di-reexport di bawah supaya pemanggil tidak menyalin.
// Belum ada versi dummy -> slot dummy diisi implementasi real (pola `api/devices.ts`).
import { pickAdapter } from './_adapter';
import * as real from './real/readiness';

/** Kesiapan material satu Order (baris per OrderLine). */
export const getOrderReadiness = pickAdapter(
  'readiness',
  real.getOrderReadiness,
  real.getOrderReadiness,
);

/**
 * F8 — `POST /garmen/orders/{id}/recompute-readiness/` (§5.5): hitung ulang lewat Odoo
 * (efek nyata) lalu balas counter `{processed, waiting, partial, ready, errors}`.
 */
export const postRecomputeReadiness = pickAdapter(
  'readiness',
  real.postRecomputeReadiness,
  real.postRecomputeReadiness,
);

export { buildOrderReadinessPath, ORDER_READINESS_PATH } from './real/orderLines';
export {
  buildOrderRecomputePath,
  READINESS_STATUSES,
  readOrderReadiness,
  readReadinessLine,
  readRecomputeResult,
} from './real/readiness';
export type {
  OrderReadiness,
  OrderReadinessLine,
  ReadinessStatus,
  RecomputeReadinessResult,
} from './real/readiness';
