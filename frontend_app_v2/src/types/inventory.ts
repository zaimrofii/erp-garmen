/**
 * inventory.ts - kontrak Inventory (operations).
 * Field `snake_case` backend dipakai apa adanya; `id` backend = number.
 *
 * Catatan F2c.1: `Product`/`ProductType` PINDAH ke `types/inventory-product.ts`
 * (`ProductRow`) karena resource `inventoryProducts` sudah `real`.
 *
 * F5.4.CLOSE: `StockMove` DIHAPUS — endpoint mutasi stok tidak ada di kontrak v4.3;
 * `MODE.inventoryReporting` kini REAL dengan bentuk agregat per lokasi
 * (`api/real/inventoryReporting.ts` → `LocationStockRow`).
 */

export type OperationType = 'transfer' | 'adjustment' | 'scrap';

export interface Operation {
  id: number;
  code: string;
  name: string;
  type: OperationType;
  warehouse: string;
}
