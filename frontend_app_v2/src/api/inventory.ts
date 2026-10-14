// ADAPTER - satu-satunya pintu data Inventory (TANPA logic domain).
//
// F2c.1: `fetchProducts` = REAL (`GET /api/v1/inventory/products/`, B7).
// F2C.2: `fetchOperations` = REAL (`GET /api/v1/inventory/operations/`, B8 — monitor sync).
// F5.4.CLOSE: `fetchLocationStock` = REAL (`GET /api/v1/inventory/reporting/`, B30 — agregat
// per lokasi, bukan mutasi stok) → `fetchStockMoves` (dummy) DIHAPUS dari barrel ini.
import { pickAdapter } from './_adapter';
import * as dummy from './dummy/inventory';
import * as real from './real/inventoryProducts';
import * as realOps from './real/inventoryOperations';
import * as realReporting from './real/inventoryReporting';

/** Master produk + stok WIP/FG (ProductsPage / ReportingPage / ConfigurationPage). */
export const fetchProducts = pickAdapter(
  'inventoryProducts',
  real.fetchProducts,
  dummy.fetchProducts,
);

/** Monitor operasi sync stok (OperationsPage). */
export const fetchOperations = pickAdapter(
  'inventoryOperations',
  realOps.fetchOperations,
  realOps.fetchOperations,
);

/** Laporan stok per lokasi MES (ReportingPage / ConfigurationPage) — REAL (B30). */
export const fetchLocationStock = pickAdapter(
  'inventoryReporting',
  realReporting.fetchLocationStock,
  realReporting.fetchLocationStock,
);

export {
  buildInventoryReportingPath,
  INVENTORY_REPORTING_PATH,
  readLocationStockReport,
  readLocationStockRow,
} from './real/inventoryReporting';
export type { LocationStockReport, LocationStockRow } from './real/inventoryReporting';

export {
  buildInventoryProductsPath,
  INVENTORY_PRODUCTS_PATH,
  PRODUCTS_LIMIT_DEFAULT,
  PRODUCTS_LIMIT_MAX,
  readProductPage,
  readProductRow,
  readProductRows,
} from './real/inventoryProducts';
export type { ProductPage, ProductRow } from './real/inventoryProducts';

export {
  buildInventoryOperationsPath,
  INVENTORY_OPERATIONS_PATH,
  readOperationPage,
  readOperationRow,
} from './real/inventoryOperations';
export type { OperationPage, OperationRow } from './real/inventoryOperations';

