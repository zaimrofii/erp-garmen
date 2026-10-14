// ADAPTER - satu-satunya pintu audit produk master MES <-> Odoo (TANPA logic domain).
//
// Halaman WAJIB mengimpor dari sini - JANGAN dari `./real/*` langsung.
//
// F9/9.0 - MODE `audit` === 'real': `GET /audit/products-missing-odoo-id/` (§6.1),
// `IsAuthenticated` (anon 403), read-only (tidak menyentuh Odoo).
// Belum ada versi dummy -> slot dummy diisi implementasi real (pola `api/readiness.ts`).
import { pickAdapter } from './_adapter';
import * as real from './real/audit';

/** Produk master tanpa `odoo_id` + subset yang dipakai bundle terbuka (§6.1). */
export const getProductAudit = pickAdapter('audit', real.getProductAudit, real.getProductAudit);

export {
  PRODUCT_AUDIT_PATH,
  readAuditProduct,
  readAuditProductGroup,
  readProductAudit,
} from './real/audit';
export type { AuditProduct, AuditProductGroup, ProductAudit } from './real/audit';
