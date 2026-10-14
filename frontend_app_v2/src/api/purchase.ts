// ADAPTER - satu-satunya pintu data Purchase (TANPA logic domain).
//
// F2C.2: SEMUA real — `purchaseOrders` (`/purchase/orders/`), `purchaseVendors`
// (`/purchase/vendors/`), `purchaseReporting` (`/purchase/reporting/`).
import { pickAdapter } from './_adapter';
import * as realOrders from './real/purchaseOrders';
import * as realReporting from './real/purchaseReporting';
import * as realVendors from './real/purchaseVendors';

/** Daftar PO + line-nya (PurchaseOrdersPage). */
export const fetchPurchaseOrders = pickAdapter(
  'purchaseOrders',
  realOrders.fetchPurchaseOrders,
  realOrders.fetchPurchaseOrders,
);
export {
  buildPurchaseOrdersPath,
  PURCHASE_ORDERS_PATH,
  readPurchaseOrderPage,
  readPurchaseOrderRow,
} from './real/purchaseOrders';
export type {
  PurchaseOrderLine,
  PurchaseOrderPage,
  PurchaseOrderRow,
} from './real/purchaseOrders';

/** Master vendor (VendorsPage). */
export const fetchVendors = pickAdapter(
  'purchaseVendors',
  realVendors.fetchVendors,
  realVendors.fetchVendors,
);
export {
  buildPurchaseVendorsPath,
  PURCHASE_VENDORS_PATH,
  readVendorPage,
  readVendorRow,
} from './real/purchaseVendors';
export type { VendorPage, VendorRow } from './real/purchaseVendors';

/** Agregat pembelian bulanan + top vendor (PurchaseReportingPage). */
export const fetchPurchaseReporting = pickAdapter(
  'purchaseReporting',
  realReporting.fetchPurchaseReporting,
  realReporting.fetchPurchaseReporting,
);
export { PURCHASE_REPORTING_PATH, readPurchaseReporting } from './real/purchaseReporting';
export type {
  MonthlySeriesPoint,
  PurchaseReporting,
  TopVendor,
  VendorBillSummary,
} from './real/purchaseReporting';

