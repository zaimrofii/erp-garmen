// REAL - wrap integration engine v1 (api-client). Endpoint: GET /audit/products-missing-odoo-id/ (§6.1)
//
// F9/9.0 - adapter BARU. Backend `ProductAuditView` memakai `IsAuthenticated` → anonim 403;
// read-only dan **tidak** menyentuh Odoo (pengisian `odoo_id` tetap tugas sync_master_products).
//
// Bentuk respons NYATA (`ProductAuditService.audit()`), sumber kebenaran:
//   `{count, products: [{id, code, name}], used_in_open_bundles: {count, limit,
//     products: [{id, code, name}]}}`
// docs §6.1 menulis `{missing: [...], used_in_open_bundles: [{product_code, bundle_count}], count}`
// — USANG (dokumen ini juga salah di §2.2/§2.3/§5.2/§5.5). Reader menerima nama kunci docs
// sebagai fallback, tetapi `products`/objek `used_in_open_bundles` dari backend yang dipakai.
import type { ApiClient } from '@/integrations/api-client';
import { unwrap } from '../client';

/** Path relatif terhadap `VITE_API_BASE_URL` — kontrak §6.1. */
export const PRODUCT_AUDIT_PATH = '/audit/products-missing-odoo-id/';

/** Satu produk master tanpa `odoo_id` (payload ringkas, read-only). */
export interface AuditProduct {
  id: number;
  code: string;
  name: string;
}

/** Potret "dipakai bundle terbuka": `{count, limit, products}` (backend §6.1). */
export interface AuditProductGroup {
  count: number;
  limit: number | null;
  products: AuditProduct[];
}

/** Respons 200 `GET /audit/products-missing-odoo-id/`. */
export interface ProductAudit {
  /** Jumlah SELURUH produk tanpa `odoo_id` (bukan panjang `products`, yang dipotong `limit`). */
  count: number;
  products: AuditProduct[];
  used_in_open_bundles: AuditProductGroup;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function readNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function readText(value: unknown): string | null {
  return typeof value === 'string' ? value : null;
}

/** PURE — satu produk mentah → `AuditProduct`; `null` kalau tanpa `id` angka. */
export function readAuditProduct(raw: unknown): AuditProduct | null {
  if (!isRecord(raw)) return null;

  const id = raw['id'];
  if (typeof id !== 'number' || !Number.isFinite(id)) return null;

  return { id, code: readText(raw['code']) ?? '', name: readText(raw['name']) ?? '' };
}

function readProductList(value: unknown): AuditProduct[] {
  if (!Array.isArray(value)) return [];

  const products: AuditProduct[] = [];
  for (const item of value) {
    const product = readAuditProduct(item);
    if (product !== null) products.push(product);
  }

  return products;
}

/**
 * PURE — potret "bundle terbuka". Backend mengirim objek `{count, limit, products}`;
 * docs §6.1 mengirim array `[{product_code, bundle_count}]` (tanpa `id`) → array kosong
 * dengan `count` = panjang array supaya jumlahnya tetap terlihat.
 */
export function readAuditProductGroup(raw: unknown): AuditProductGroup | null {
  if (Array.isArray(raw)) {
    return { count: raw.length, limit: null, products: [] };
  }

  if (!isRecord(raw)) return null;

  const products = readProductList(raw['products']);

  return { count: readNumber(raw['count']) ?? products.length, limit: readNumber(raw['limit']), products };
}

/**
 * PURE — respons mentah → `ProductAudit`; `null` kalau bentuknya tidak dikenali
 * (tanpa daftar produk sama sekali). Menerima `products` (backend) dan `missing` (docs §6.1).
 */
export function readProductAudit(raw: unknown): ProductAudit | null {
  if (!isRecord(raw)) return null;

  const list = raw['products'] ?? raw['missing'];
  if (!Array.isArray(list)) return null;

  const products = readProductList(list);
  const group = readAuditProductGroup(raw['used_in_open_bundles']);
  const count = readNumber(raw['count']);

  return {
    count: count ?? products.length,
    products,
    used_in_open_bundles: group ?? { count: 0, limit: null, products: [] },
  };
}

/**
 * Baca audit produk tanpa `odoo_id`. Gagal HTTP (403 tanpa session) → melempar Error
 * (`unwrap`); bentuk tak dikenal → melempar pesan yang bisa ditampilkan.
 */
export async function getProductAudit(client: ApiClient): Promise<ProductAudit> {
  const res = await client.get<unknown>(PRODUCT_AUDIT_PATH);
  const parsed = readProductAudit(unwrap(res));

  if (parsed === null) {
    throw new Error('Bentuk respons audit produk tidak dikenali.');
  }

  return parsed;
}
