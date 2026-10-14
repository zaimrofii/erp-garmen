// ADAPTER - satu-satunya pintu data master produk (H1.1, TANPA logic domain).
//
// H1.1: endpoint `/api/v1/master/products/` SUDAH ADA di backend (MES = source of
// truth master) → MODE.masterProducts = 'real' (`_adapter.ts`), jadi tidak ada
// implementasi dummy untuk resource ini.
import { pickAdapter } from './_adapter';
import * as real from './real/masterProducts';

/** Daftar produk + filter (`GET /master/products/`) — REAL (H1.1, B-H1.1). */
export const fetchProducts = pickAdapter('masterProducts', real.fetchProducts, real.fetchProducts);

/** Detail produk (`GET /master/products/<id>/`) — REAL (H1.1). */
export const fetchProduct = pickAdapter('masterProducts', real.fetchProduct, real.fetchProduct);

/** Buat produk (`POST /master/products/`) — REAL (H1.1; izin admin/owner/purchasing). */
export const createProduct = pickAdapter('masterProducts', real.createProduct, real.createProduct);

/** Ubah produk (`PUT /master/products/<id>/`) — REAL (H1.1). */
export const updateProduct = pickAdapter('masterProducts', real.updateProduct, real.updateProduct);

/** Nonaktifkan produk (`DELETE` = soft delete `active=False`) — REAL (H1.1). */
export const deleteProduct = pickAdapter('masterProducts', real.deleteProduct, real.deleteProduct);

/** H3.5 — ubah harga produk (`PUT /master/products/<id>/price/`) — REAL + audit trail. */
export const updateProductPrice = pickAdapter(
  'masterProducts',
  real.updateProductPrice,
  real.updateProductPrice,
);

/** H3.5 — riwayat harga produk (`GET /master/products/<id>/price-history/`) — REAL. */
export const fetchProductPriceHistory = pickAdapter(
  'masterProducts',
  real.fetchProductPriceHistory,
  real.fetchProductPriceHistory,
);

export {
  buildMasterProductsPath,
  buildPriceHistoryPath,
  MASTER_PRODUCTS_PATH,
  masterProductPriceHistoryPath,
  masterProductPricePath,
  PRODUCTS_LIMIT_DEFAULT,
  PRODUCTS_LIMIT_MAX,
  readMasterProductPage,
  readMasterProductRow,
  readMasterProductSaved,
  readPriceHistoryPage,
  readPriceHistoryRow,
  toMasterProductBody,
  toMasterProductPriceBody,
} from './real/masterProducts';
export type { MasterProductPage, MasterProductsParams } from './real/masterProducts';
export type {
  MasterProductInput,
  MasterProductPriceHistoryPage,
  MasterProductPriceHistoryRow,
  MasterProductPriceInput,
  MasterProductRow,
  MasterProductSaved,
} from '@/types/master-product';
