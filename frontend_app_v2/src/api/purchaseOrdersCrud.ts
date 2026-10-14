// ADAPTER - satu-satunya pintu data **Purchase Order MES** (H2.2, TANPA logic domain).
//
// H2.2: endpoint `/api/v1/garmen/purchase-orders/` SUDAH ADA di backend (transaksi,
// sync SATU ARAH MES → Odoo) → MODE.purchaseOrdersCrud = 'real', tanpa dummy.
// Push ke Odoo hanya saat `CONFIRMED` (create **draft** di Odoo, `partner_ref` =
// nomor MES `PO-<TAHUN>-<SEQ>`).
//
// ⚠️ BUKAN `api/purchase.ts` (B10 monitoring read-only dari Odoo, path
// `/purchase/orders/`) — dua adapter berbeda, tidak saling menyentuh.
import { pickAdapter } from './_adapter';
import * as real from './real/purchaseOrdersCrud';

/** Daftar PO MES + filter (`GET /garmen/purchase-orders/`) — REAL (H2.2). */
export const fetchPurchaseOrdersMes = pickAdapter(
  'purchaseOrdersCrud',
  real.fetchPurchaseOrdersMes,
  real.fetchPurchaseOrdersMes,
);

/** Detail PO MES + `lines[]` (`GET /garmen/purchase-orders/<id>/`) — REAL (H2.2). */
export const fetchPurchaseOrderMes = pickAdapter(
  'purchaseOrdersCrud',
  real.fetchPurchaseOrderMes,
  real.fetchPurchaseOrderMes,
);

/** Buat PO (`POST`; nomor otomatis Sprint C) — REAL (H2.2). */
export const createPurchaseOrderMes = pickAdapter(
  'purchaseOrdersCrud',
  real.createPurchaseOrderMes,
  real.createPurchaseOrderMes,
);

/** Ubah PO (`PUT`, DRAFT-only) — REAL (H2.2). */
export const updatePurchaseOrderMes = pickAdapter(
  'purchaseOrdersCrud',
  real.updatePurchaseOrderMes,
  real.updatePurchaseOrderMes,
);

/** Hapus PO (`DELETE`, DRAFT-only, hard delete) — REAL (H2.2). */
export const deletePurchaseOrderMes = pickAdapter(
  'purchaseOrdersCrud',
  real.deletePurchaseOrderMes,
  real.deletePurchaseOrderMes,
);

/** Transisi state (`POST …/confirm|done|cancel/`) — REAL (H2.2). */
export const runPurchaseOrderMesAction = pickAdapter(
  'purchaseOrdersCrud',
  real.runPurchaseOrderMesAction,
  real.runPurchaseOrderMesAction,
);

/** Baca state Odoo on-demand (`POST …/sync-odoo-state/`, read-only) — REAL (H2.2). */
export const fetchPurchaseOrderOdooState = pickAdapter(
  'purchaseOrdersCrud',
  real.fetchPurchaseOrderOdooState,
  real.fetchPurchaseOrderOdooState,
);

export {
  buildPurchaseOrdersMesPath,
  PURCHASE_ORDERS_MES_LIMIT_DEFAULT,
  PURCHASE_ORDERS_MES_LIMIT_MAX,
  PURCHASE_ORDERS_MES_PATH,
  PURCHASE_ORDER_MES_ACTIONS,
  PURCHASE_ORDER_MES_STATES,
  purchaseOrderMesActionPath,
  purchaseOrderMesDetailPath,
  purchaseOrderMesSyncStatePath,
  readPurchaseOrderMesDetail,
  readPurchaseOrderMesLineRow,
  readPurchaseOrderMesPage,
  readPurchaseOrderMesRow,
  readPurchaseOrderMesSaved,
  readPurchaseOrderOdooState,
  readPurchaseOrderTaxIds,
  toPurchaseOrderMesBody,
  toPurchaseOrderMesLineBody,
} from './real/purchaseOrdersCrud';
export type {
  PurchaseOrderMesAction,
  PurchaseOrderMesPage,
  PurchaseOrdersMesParams,
} from './real/purchaseOrdersCrud';
export type {
  PurchaseOrderMesDetail,
  PurchaseOrderMesInput,
  PurchaseOrderMesLineInput,
  PurchaseOrderMesLineRow,
  PurchaseOrderMesRow,
  PurchaseOrderMesSaved,
  PurchaseOrderOdooState,
  PurchaseOrderState,
} from '@/types/purchase-order';
