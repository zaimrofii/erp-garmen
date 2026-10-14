/**
 * inventory-product.ts — baris produk dari `GET /api/v1/inventory/products/` (F2c.1).
 *
 * Field = PERSIS backend (B7 `InventoryProductsView`):
 *   `{rows:[{id, code, name, odoo_id, stock_qty}], total_count, has_more, next_cursor}`.
 *
 * Field lama `type`/`uom` DIBUANG (tidak ada di backend) — lihat
 * `docs/contract-gap-f1f2.md`.
 */
export interface ProductRow {
  id: number;
  code: string;
  name: string;
  odoo_id: number | null;
  stock_qty: number;
}
