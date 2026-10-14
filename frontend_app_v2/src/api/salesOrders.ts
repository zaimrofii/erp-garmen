// ADAPTER - satu-satunya pintu data Sales Order (H2.1, TANPA logic domain).
//
// H2.1: endpoint `/api/v1/garmen/orders/` SUDAH ADA di backend (transaksi, sync
// SATU ARAH MES → Odoo) → MODE.salesOrders = 'real' (`_adapter.ts`), tanpa dummy.
// Push ke Odoo hanya saat `CONFIRMED` (create **draft** di Odoo) dan nomor order
// MES (`SO-<TAHUN>-<SEQ>`) dikirim sebagai `client_order_ref`.
import { pickAdapter } from './_adapter';
import * as real from './real/salesOrders';

/** Daftar order + filter (`GET /garmen/orders/`) — REAL (H2.1). */
export const fetchOrders = pickAdapter('salesOrders', real.fetchSalesOrders, real.fetchSalesOrders);

/** Detail order + `lines[]` (`GET /garmen/orders/<id>/`) — REAL (H2.1). */
export const fetchOrder = pickAdapter('salesOrders', real.fetchSalesOrder, real.fetchSalesOrder);

/** Buat order (`POST /garmen/orders/`; nomor otomatis Sprint C) — REAL (H2.1). */
export const createOrder = pickAdapter(
  'salesOrders',
  real.createSalesOrder,
  real.createSalesOrder,
);

/** Ubah order (`PUT /garmen/orders/<id>/`, DRAFT-only) — REAL (H2.1). */
export const updateOrder = pickAdapter(
  'salesOrders',
  real.updateSalesOrder,
  real.updateSalesOrder,
);

/** Hapus order (`DELETE`, DRAFT-only, hard delete) — REAL (H2.1). */
export const deleteOrder = pickAdapter(
  'salesOrders',
  real.deleteSalesOrder,
  real.deleteSalesOrder,
);

/** Transisi state (`POST …/confirm|done|cancel/`) — REAL (H2.1). */
export const runOrderAction = pickAdapter(
  'salesOrders',
  real.runSalesOrderAction,
  real.runSalesOrderAction,
);

export {
  buildSalesOrdersPath,
  readNumArray,
  readSalesOrderDetail,
  readSalesOrderLineRow,
  readSalesOrderPage,
  readSalesOrderRow,
  readSalesOrderSaved,
  SALES_ORDERS_LIMIT_DEFAULT,
  SALES_ORDERS_LIMIT_MAX,
  SALES_ORDERS_PATH,
  SALES_ORDER_ACTIONS,
  SALES_ORDER_STATES,
  salesOrderActionPath,
  salesOrderDetailPath,
  toSalesOrderBody,
  toSalesOrderLineBody,
} from './real/salesOrders';
export type { SalesOrderAction, SalesOrderPage, SalesOrdersParams } from './real/salesOrders';
export type {
  SalesOrderDetail,
  SalesOrderInput,
  SalesOrderLineInput,
  SalesOrderLineRow,
  SalesOrderRow,
  SalesOrderSaved,
  SalesOrderState,
} from '@/types/sales-order';
