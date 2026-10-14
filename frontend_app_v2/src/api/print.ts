// ADAPTER - satu-satunya pintu cetak (kupon §7.2 + tag bundle §7.1). TANPA logic domain.
//
// Halaman WAJIB mengimpor dari sini - JANGAN dari `./real/*` langsung.
// MODE.print === 'real' (endpoint ADA; live: POST body invalid → 400, bukan 404).
//
// F14 (opsi B): `printBundleTag` MIGRASI ke sini dari `integrations/print-tag.ts`
// (file legacy itu dihapus) supaya hanya ada SATU implementasi cetak.
import { pickAdapter } from './_adapter';
import * as real from './real/print';

/** `POST /print/kupon/` — cetak kupon dari `ticket_code`. */
export const printCoupon = pickAdapter('print', real.printCoupon, real.printCoupon);

/** `POST /print/bundle-tag/` — cetak tag bundle dari `bundle_id` (§7.1). */
export const printBundleTag = pickAdapter('print', real.printBundleTag, real.printBundleTag);

export {
  buildPrintBundleTagBody,
  PRINT_BUNDLE_TAG_PATH,
  PRINT_COUPON_PATH,
  readPrintJob,
} from './real/print';
export type {
  PrintBundleTagInput,
  PrintCouponInput,
  PrintJobResponse,
} from './real/print';
