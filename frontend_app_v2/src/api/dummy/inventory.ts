// @dummy - endpoint masa depan (slot pembanding `pickAdapter`): GET /inventory/products
//
// F5.4.CLOSE: `fetchStockMoves` DIHAPUS (MODE.inventoryReporting sudah REAL, bentuknya
// agregat per lokasi — `api/real/inventoryReporting.ts`). `fetchOperations` di sini hanya
// dipakai sebagai argumen dummy oleh barrel (implementasi aktif = `real/inventoryOperations`).
import type { Operation } from '@/types/inventory';
import type { ProductRow } from '@/types/inventory-product';
import { delay } from './_delay';

const PRODUCT_FIXTURE: ProductRow[] = [
  {
    id: 1,
    code: 'RM-CC24-BLK',
    name: 'Kain Cotton Combed 24s Hitam',
    odoo_id: 101,
    stock_qty: 1450,
  },
  {
    id: 2,
    code: 'RM-CC24-WHT',
    name: 'Kain Cotton Combed 24s Putih',
    odoo_id: 102,
    stock_qty: 980,
  },
  {
    id: 3,
    code: 'RM-BENANG-30S',
    name: 'Benang Jahit 30s',
    odoo_id: 103,
    stock_qty: 320,
  },
  {
    id: 4,
    code: 'WIP-TS-BLK-BODY',
    name: 'Body TS-BLK (setelah jahit)',
    odoo_id: 104,
    stock_qty: 640,
  },
  {
    id: 5,
    code: 'WIP-PO-HIT-BODY',
    name: 'Body PO-HIT (setelah jahit)',
    odoo_id: 105,
    stock_qty: 275,
  },
  {
    id: 6,
    code: 'FG-TS-BLK-M',
    name: 'Kaos TS-BLK size M',
    odoo_id: 106,
    stock_qty: 410,
  },
  {
    id: 7,
    code: 'FG-PO-HIT-L',
    name: 'Polo PO-HIT size L',
    odoo_id: 107,
    stock_qty: 168,
  },
];

const OPERATION_FIXTURE: Operation[] = [
  {
    id: 1,
    code: 'OP-TR-WH-LINEA',
    name: 'Transfer kain ke Line A',
    type: 'transfer',
    warehouse: 'Gudang Utama',
  },
  {
    id: 2,
    code: 'OP-TR-LINEA-FG',
    name: 'Transfer WIP ke Finishing',
    type: 'transfer',
    warehouse: 'Line A',
  },
  {
    id: 3,
    code: 'OP-ADJ-STOCK-OPNAME',
    name: 'Penyesuaian stock opname',
    type: 'adjustment',
    warehouse: 'Gudang Utama',
  },
  {
    id: 4,
    code: 'OP-SCRAP-KAIN',
    name: 'Scrap kain cacat',
    type: 'scrap',
    warehouse: 'Line A',
  },
];

/** Master produk (ProductsPage) - fixture dummy (shape sekarang = `ProductRow`). */
export async function fetchProducts(): Promise<ProductRow[]> {
  await delay(100 + Math.random() * 200);

  return PRODUCT_FIXTURE.map((row) => ({ ...row }));
}

/** Master operasi gudang (OperationsPage). */
export async function fetchOperations(): Promise<Operation[]> {
  await delay(100 + Math.random() * 200);

  return OPERATION_FIXTURE.map((row) => ({ ...row }));
}
